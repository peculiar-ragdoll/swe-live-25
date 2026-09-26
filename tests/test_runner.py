import pytest

from swe25 import runner as RN
from swe25.config import Arm, Settings
from swe25.results import Row, read_rows

PI = Arm(name="arm", agent="pi", model="m", endpoint="http://127.0.0.1:8080/v1", sampling={"temp": 0.6})
CLAUDE = Arm(name="opus", agent="claude", model="claude-opus-5", effort="medium")
IDS = ["lima-vm__lima-4803"]


class FakeAgent:
    """Returns rows from `script`: a list of dicts of Row fields (or an exception to raise)."""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def __call__(self, inst, arm, tag, wd, *, cap, resume, sample):
        self.calls.append({"cap": cap, "resume": resume, "sample": sample})
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        base = {"turns": 3, "wall_agent_s": float(cap), "timed_out": False, "patch_nonempty": True}
        return Row(inst["instance_id"], arm.name, sample=sample, agent=arm.agent, **{**base, **step})


class FakeImages:
    def __init__(self):
        self.overlays, self.released = [], []

    def overlay(self, inst, kind):
        self.overlays.append(inst["instance_id"])
        return "tag"

    def release(self, inst):
        self.released.append(inst["instance_id"])


def grader(resolve_when=lambda row: False):
    def g(inst, wd, row):
        row.f2p_total = 1
        row.resolved = resolve_when(row)
    return g


def make(tmp_path, arm, script, seeds=1, grade=None, ids=IDS, subset="canonical25"):
    s = Settings(work_dir=tmp_path / "work", results_dir=tmp_path / "results", min_free_gb=20)
    agent, images = FakeAgent(script), FakeImages()
    r = RN.Runner(s, arm, ids, seeds, agent_pass=agent, grader=grade or grader(), images=images, log=lambda *a: None,
                  subset=subset)
    return r, agent, images, s.results_dir / f"{arm.name}.jsonl"


def test_natural_miss_settles_in_one_pass(tmp_path):
    r, agent, images, out = make(tmp_path, PI, [{"wall_agent_s": 300}])
    summary = r.run()
    assert summary.rows_written == 1 and summary.open == 0
    assert agent.calls == [{"cap": 1200, "resume": False, "sample": 0}]
    assert images.released == IDS
    row = read_rows([out])[0]
    assert row["pass_kind"] == "fresh" and row["cum_wall_s"] == 300 and row["sampling"] == {"temp": 0.6}


def test_capped_cell_resumes_to_the_ceiling(tmp_path):
    r, agent, _, out = make(tmp_path, PI, [{"timed_out": True}] * 5)
    r.run()
    assert [c["cap"] for c in agent.calls] == [1200, 3600, 3600, 3600, 2400]
    assert [c["resume"] for c in agent.calls] == [False, True, True, True, True]
    rows = read_rows([out])
    assert rows[-1]["cum_wall_s"] == 14400 and [x["pass_kind"] for x in rows][1:] == ["resume"] * 4


def test_capped_pass_that_grades_resolved_stops(tmp_path):
    r, agent, _, _ = make(tmp_path, PI, [{"timed_out": True}], grade=grader(lambda row: True))
    summary = r.run()
    assert len(agent.calls) == 1 and summary.settled == 1


def test_interrupt_leaves_cell_open(tmp_path):
    r, agent, _, out = make(tmp_path, PI, [{"timed_out": True}, KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        r.run()
    assert len(read_rows([out])) == 1
    r2, agent2, _, _ = make(tmp_path, PI, [{"wall_agent_s": 100}])
    r2.run()
    assert agent2.calls == [{"cap": 3600, "resume": True, "sample": 0}]


NOISE = {"turns": None, "wall_agent_s": 0.0, "patch_nonempty": False, "error": "agent: container cut short"}
DEAD = {"turns": None, "wall_agent_s": 4.0, "patch_nonempty": False,
        "error": "agent: no model turns in this pass"}
WEDGED = {"turns": None, "wall_agent_s": 1500.0, "patch_nonempty": False,
          "error": "agent: deadline watchdog fired | agent: no model turns in this pass"}
TWO = ["lima-vm__lima-4803", "thlorenz__doctoc-328"]


def test_noise_rows_strike_out_the_cell_but_not_the_run(tmp_path):
    r, agent, images, out = make(tmp_path, PI, [NOISE] * 3 + [{"wall_agent_s": 50}], ids=TWO)
    summary = r.run()
    assert len(agent.calls) == 4 and summary.open == 1 and summary.settled == 1
    assert images.released == TWO and len(read_rows([out])) == 1


def test_two_struck_out_cells_in_a_row_abort(tmp_path):
    r, agent, _, _ = make(tmp_path, PI, [NOISE] * 6, ids=TWO)
    with pytest.raises(RN.RunAborted, match="consecutive"):
        r.run()
    assert len(agent.calls) == 6


def test_wall_burning_zero_turn_passes_are_failures_not_misses(tmp_path):
    r, agent, _, out = make(tmp_path, PI, [WEDGED] * 3)
    summary = r.run()
    assert len(agent.calls) == 3 and summary.open == 1
    assert all(c["cap"] == 1200 and c["resume"] is False for c in agent.calls)


def test_retry_after_zero_turn_pass_is_fresh(tmp_path):
    r, agent, _, _ = make(tmp_path, PI, [DEAD, {"wall_agent_s": 50}])
    r.run()
    assert [(c["cap"], c["resume"]) for c in agent.calls] == [(1200, False), (1200, False)]


def test_second_interrupt_abandons_running_grades(tmp_path, monkeypatch):
    import threading
    import time
    release = threading.Event()
    kills = []

    def slow_grader(inst, wd, row):
        release.wait(10)

    def fake_wait(fs, return_when=None):
        raise KeyboardInterrupt                      # the user's second Ctrl-C

    monkeypatch.setattr(RN.docker, "safe", lambda args, timeout=60: kills.append(args))
    r, agent, _, _ = make(tmp_path, PI, [{"wall_agent_s": 50}, KeyboardInterrupt()], seeds=2, grade=slow_grader)
    monkeypatch.setattr(RN.cf, "wait", fake_wait)
    t0 = time.time()
    with pytest.raises(KeyboardInterrupt):
        r.run()
    assert time.time() - t0 < 5
    assert ["docker", "kill", "swe25-grade-arm-lima-vm__lima-4803-s0"] in kills
    release.set()


def test_claude_timeout_is_final(tmp_path):
    r, agent, _, _ = make(tmp_path, CLAUDE, [{"timed_out": True, "wall_agent_s": 1800}])
    summary = r.run()
    assert len(agent.calls) == 1 and agent.calls[0]["resume"] is False and summary.open == 0


def test_claude_infra_failure_is_rerun_fresh(tmp_path):
    fail = {"error": "claude: rc=1", "patch_nonempty": False, "wall_agent_s": 20}
    r, agent, _, _ = make(tmp_path, CLAUDE, [fail, {"wall_agent_s": 900}])
    r.run()
    assert [c["resume"] for c in agent.calls] == [False, False]


def test_seeds_and_rerun_of_settled_arm(tmp_path):
    r, agent, _, _ = make(tmp_path, PI, [{"wall_agent_s": 50}] * 3, seeds=3)
    assert r.run().rows_written == 3
    assert sorted(c["sample"] for c in agent.calls) == [0, 1, 2]
    r2, agent2, images2, _ = make(tmp_path, PI, [], seeds=3)
    summary = r2.run()
    assert summary.rows_written == 0 and agent2.calls == [] and images2.overlays == []


def test_extending_seeds_runs_only_new_ones(tmp_path):
    make(tmp_path, PI, [{"wall_agent_s": 50}])[0].run()
    r, agent, _, _ = make(tmp_path, PI, [{"wall_agent_s": 50}] * 2, seeds=3)
    r.run()
    assert sorted(c["sample"] for c in agent.calls) == [1, 2]


def test_zero_rows_after_attempts_is_not_done(tmp_path, monkeypatch):
    # Rows that never reach the results file (a silently failing sink) must fail the run loudly.
    monkeypatch.setattr(RN, "append_row", lambda path, row: row.to_dict())
    r, _, _, _ = make(tmp_path, PI, [{"wall_agent_s": 50}])
    with pytest.raises(RN.RunAborted, match="0 rows"):
        r.run()


def test_grader_crash_records_row_with_error_and_resumes(tmp_path):
    calls = []

    def flaky_grader(inst, wd, row):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        row.f2p_total = 1

    r, agent, _, out = make(tmp_path, PI, [{"wall_agent_s": 50}, {"wall_agent_s": 60}], grade=flaky_grader)
    r.run()
    rows = read_rows([out])
    assert "grade_error" in rows[0]["error"] and rows[1]["pass_kind"] == "resume"
    assert [c["resume"] for c in agent.calls] == [False, True]


def test_runconfig_sidecar_has_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("MYKEY", "sekrit")
    arm = Arm(name="arm", agent="pi", model="m", endpoint="http://h:1/v1", api_key_env="MYKEY")
    r, _, _, _ = make(tmp_path, arm, [{"wall_agent_s": 50}])
    r.run()
    (cfg,) = (tmp_path / "results").glob("arm.runconfig.*.json")
    text = cfg.read_text()
    assert "sekrit" not in text and '"api_key_env": "MYKEY"' in text and "bash_patch_md5" in text


def test_rows_record_the_subset_and_a_conflicting_subset_is_refused(tmp_path):
    r, _, _, out = make(tmp_path, PI, [{"wall_agent_s": 50}], subset="winnable17")
    r.run()
    assert read_rows([out])[0]["subset"] == "winnable17"
    with pytest.raises(RN.SubsetConflict, match="winnable17"):
        make(tmp_path, PI, [], subset="canonical25")[0].run()
