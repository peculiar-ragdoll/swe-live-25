import json
import subprocess

from swe25 import grade as G
from swe25.results import Row

TEXT_PARSER = '''
def parser(log):
    out = {}
    for line in log.splitlines():
        if line.startswith(("PASS ", "FAIL ")):
            status, name = line.split(" ", 1)
            out[name] = "passed" if status == "PASS" else "failed"
    return out
'''
JSON_PARSER = '''
import json
def parser(log):
    return {t["name"]: t["status"] for t in json.loads(log)["tests"]}
'''


def inst(parser=TEXT_PARSER, f2p=("t1",), p2p=("t2",), iid="org__repo-1"):
    return {"instance_id": iid, "log_parser": parser, "FAIL_TO_PASS": list(f2p), "PASS_TO_PASS": list(p2p),
            "docker_image": "img", "test_patch": "diff", "test_cmds": ["go test ./..."], "print_cmds": []}


def test_best_candidate_wins():
    status, err = G.score_logs(inst(), ["PASS t1", "PASS t1\nPASS t2\nFAIL t3"])
    assert status == {"t1": "passed", "t2": "passed", "t3": "failed"} and err is None


def test_json_parser_skips_non_json_candidate():
    blob = json.dumps({"tests": [{"name": "t1", "status": "PASSED"}]})
    status, _ = G.score_logs(inst(JSON_PARSER), ["not json at all", blob])
    assert status == {"t1": "PASSED"}


def test_parser_error_reported_when_nothing_parses():
    status, err = G.score_logs(inst(JSON_PARSER), ["nope"])
    assert status == {} and "JSONDecodeError" in err


def test_verdict_counts_and_resolution():
    r = Row("x", "m")
    G.apply_verdict(inst(f2p=("a", "b"), p2p=("c",)), {"a": "pass", "b": "PASSED", "c": "passed"}, r)
    assert (r.f2p_pass, r.f2p_total, r.p2p_pass, r.p2p_total, r.resolved) == (2, 2, 1, 1, True)
    r2 = Row("x", "m")
    G.apply_verdict(inst(f2p=("a",), p2p=("c",)), {"a": "pass", "c": "failed"}, r2)
    assert r2.resolved is False


def test_resolution_needs_a_fail_to_pass_test():
    r = Row("x", "m")
    G.apply_verdict(inst(f2p=(), p2p=()), {}, r)
    assert r.resolved is False


def test_string_encoded_test_lists():
    i = inst()
    i["FAIL_TO_PASS"], i["PASS_TO_PASS"] = json.dumps(["a"]), json.dumps([])
    r = Row("x", "m")
    G.apply_verdict(i, {"a": "pass"}, r)
    assert r.resolved and r.f2p_total == 1


def test_chimurai_network_tests_excluded():
    iid = "chimurai__http-proxy-middleware-1163"
    assert len(G.F2P_EXCLUDE[iid]) == 8
    net = sorted(G.F2P_EXCLUDE[iid])[0]
    r = Row(iid, "m")
    G.apply_verdict(inst(f2p=("ok", net), p2p=(), iid=iid), {"ok": "passed", net: "failed"}, r)
    assert r.resolved and r.f2p_total == 1


def test_grade_runs_container_and_reads_logs(tmp_path, monkeypatch):
    calls = []

    def fake_sh(cmd, timeout):
        calls.append(cmd)
        (tmp_path / "_parser_input.log").write_text("PASS t1\nPASS t2\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(G.docker, "sh", fake_sh)
    r = Row("org__repo-1", "m")
    G.grade(inst(), tmp_path, r)
    assert r.resolved and (tmp_path / "test.patch").read_text() == "diff"
    cmd = calls[0]
    assert cmd[:4] == ["docker", "run", "--rm", "--platform"] and "img" in cmd
    assert "--cap-drop" in cmd and "8g" in cmd
    script = cmd[-1]
    assert "git apply --3way /work/model.patch" in script and "go test ./..." in script


def test_grade_timeout_is_loud(tmp_path, monkeypatch, capsys):
    def fake_sh(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(G.docker, "sh", fake_sh)
    r = Row("org__repo-1", "m")
    G.grade(inst(), tmp_path, r, timeout=5)
    assert "grade_timeout:5s" in r.error and "GRADE TIMEOUT" in capsys.readouterr().out


def test_grade_container_is_named(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(G.docker, "sh", lambda cmd, timeout: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    G.grade(inst(), tmp_path, Row("org__repo-1", "m"), name="swe25-grade-x")
    run = next(c for c in calls if c[:2] == ["docker", "run"])
    assert run[run.index("--name") + 1] == "swe25-grade-x"
    assert G.container_name("arm", "org__repo-1", 2) == "swe25-grade-arm-org__repo-1-s2"
