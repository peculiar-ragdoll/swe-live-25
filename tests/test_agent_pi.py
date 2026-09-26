import json
from pathlib import Path

import pytest

from swe25 import agent_pi as A
from swe25.config import Arm

FIX = Path(__file__).parent / "fixtures" / "pi_transcript.jsonl"
INST = {"instance_id": "org__repo-1", "problem_statement": "Fix the bug.", "docker_image": "img"}


def arm(**k):
    return Arm(name="my-arm", agent="pi", model="my-model", endpoint="http://127.0.0.1:8080/v1", **k)


@pytest.mark.parametrize("given,want", [
    ("http://localhost:8080", "http://host.docker.internal:8080/v1"),
    ("http://127.0.0.1:8080/v1/", "http://host.docker.internal:8080/v1"),
    ("http://0.0.0.0:1234/v1", "http://host.docker.internal:1234/v1"),
    ("https://models.example.com/v1", "https://models.example.com/v1"),
    ("http://10.0.0.5:8000/api/v1", "http://10.0.0.5:8000/api/v1"),
])
def test_container_url_normalizes(given, want):
    assert A.container_url(given) == want


def test_models_json():
    m = A.models_json(arm(context=131072))
    p = m["providers"]["swe25"]
    assert p["baseUrl"] == "http://host.docker.internal:8080/v1" and p["api"] == "openai-completions"
    assert p["apiKey"] == "$SWE25_API_KEY"
    assert p["compat"] == {"supportsDeveloperRole": False, "supportsReasoningEffort": True}
    assert p["models"] == [{"id": "my-model", "reasoning": True, "contextWindow": 131072, "maxTokens": 16000}]


def test_resume_nudge_verbatim():
    assert A.RESUME_NUDGE == ("You have more time now. Continue exactly where you left off and finish making "
                              "the failing test(s) pass. Do not restart from scratch.")


def test_fresh_script():
    s = A.render_script(cap=1200, resume=False, name="org__repo-1")
    assert s.lstrip().startswith("export PATH=$PATH:/usr/local/go/bin")
    assert 'timeout 1200 pi --print --mode json --provider swe25 --model "$PI_MODEL"' in s
    assert "--no-context-files --approve --session-id run" in s
    assert '"$(cat /work/problem.txt)"' in s and "git apply" not in s.split("timeout")[0]
    assert "--append-system-prompt" not in s
    assert "git diff --cached HEAD > /work/model.patch" in s


def test_resume_script_restores_edits():
    s = A.render_script(cap=3600, resume=True, name="x")
    head = s.split("timeout 3600")[0]
    assert "git apply /work/model.patch" in head and "git apply --3way /work/model.patch" in head
    assert '"$(cat /work/resume.txt)"' in s


def test_parse_transcript():
    m = A.parse_transcript(FIX.read_text())
    assert m == {"turns": 2, "tool_calls": 2, "tool_calls_invalid": 1, "prefill_tokens": 2500,
                 "output_tokens": 500, "total_generated": 500, "prefill_cache_hit": 0.4}
    assert A.parse_transcript("") == {}


class FakePopen:
    rc = "124"

    def __init__(self, cmd, **kw):
        FakePopen.cmd = cmd
        wd = Path(cmd[cmd.index("-v") + 1].split(":")[0])
        if self.rc is not None:
            (wd / "_pi_rc").write_text(self.rc + "\n")
        (wd / "model.patch").write_text("diff --git a b\n")
        self.stdout = iter(FIX.read_text().splitlines(keepends=True))
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


@pytest.fixture
def fake_docker(monkeypatch):
    monkeypatch.setattr(A.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(A.docker, "bash_patch_mount", lambda tag: ["-v", "patch:target:ro"])
    monkeypatch.setattr(A.docker, "safe", lambda *a, **k: None)
    FakePopen.rc = "124"


def test_run_pass_fresh_timeout(tmp_path, fake_docker, monkeypatch):
    monkeypatch.setenv("MYKEY", "sekrit")
    a = arm(api_key_env="MYKEY", sampling={"temp": 0.6})
    row = A.run_pass(INST, a, "swe25-pi:org__repo-1", tmp_path, cap=1200, resume=False, sample=2)
    assert row.timed_out and row.patch_nonempty and row.error is None
    assert (row.sample, row.turns, row.tool_calls, row.agent) == (2, 2, 2, "pi")
    assert (tmp_path / "problem.txt").read_text() == "Fix the bug."
    mj = json.loads((tmp_path / ".pihome/.pi/agent/models.json").read_text())
    assert mj["providers"]["swe25"]["models"][0]["id"] == "my-model"
    cmd = FakePopen.cmd
    assert "PI_MODEL=my-model" in cmd
    assert "PI_BASH_IDLE_TIMEOUT=600" in cmd and "PI_BASH_WALL_TIMEOUT=1800" in cmd
    for flag in ("--cap-drop", "--pids-limit", "--add-host=host.docker.internal:host-gateway"):
        assert flag in cmd
    assert cmd[cmd.index("--memory") + 1] == "6g" and "patch:target:ro" in cmd
    assert any(n.startswith("swe25-pi-org__repo-1-my-arm-s2") for n in cmd)
    assert len(list((tmp_path / "transcripts").glob("*_fresh.jsonl"))) == 1


def test_run_pass_missing_rc_is_error(tmp_path, fake_docker):
    FakePopen.rc = None
    row = A.run_pass(INST, arm(), "t", tmp_path, cap=1200, resume=False, sample=0)
    assert not row.timed_out and "container cut short" in row.error


def test_resume_keeps_history_and_fresh_archives_it(tmp_path, fake_docker):
    A.run_pass(INST, arm(), "t", tmp_path, cap=1200, resume=False, sample=0)
    r2 = A.run_pass(INST, arm(), "t", tmp_path, cap=3600, resume=True, sample=0)
    assert (tmp_path / "resume.txt").read_text() == A.RESUME_NUDGE
    assert r2.turns == 4                         # metrics span the fresh + resume transcripts
    A.run_pass(INST, arm(), "t", tmp_path, cap=1200, resume=False, sample=0)
    assert len(list((tmp_path / "archive").glob("*/*.jsonl"))) == 2
    assert len(list((tmp_path / "transcripts").glob("*.jsonl"))) == 1


def test_pass_without_model_turns_is_infra_error(tmp_path, fake_docker, monkeypatch):
    # Pi exits at once when the model server is unreachable: rc 1, no assistant turns. That must not
    # read as a natural-end miss.
    FakePopen.rc = "1"
    orig = FakePopen.__init__

    def init(self, cmd, **kw):
        orig(self, cmd, **kw)
        self.stdout = iter(['{"type":"agent_start"}\n', '{"type":"agent_end"}\n'])

    monkeypatch.setattr(FakePopen, "__init__", init)
    row = A.run_pass(INST, arm(), "t", tmp_path, cap=1200, resume=False, sample=0)
    assert row.error.startswith("agent: no model turns")


def test_timed_out_pass_without_turns_is_a_normal_cap(tmp_path, fake_docker, monkeypatch):
    FakePopen.rc = "124"            # a slow model still mid-generation when the cap hit
    orig = FakePopen.__init__

    def init(self, cmd, **kw):
        orig(self, cmd, **kw)
        self.stdout = iter(['{"type":"agent_start"}\n'])

    monkeypatch.setattr(FakePopen, "__init__", init)
    row = A.run_pass(INST, arm(), "t", tmp_path, cap=1200, resume=False, sample=0)
    assert row.timed_out and row.error is None


def test_zero_turn_marker_added_even_when_error_already_set(tmp_path, fake_docker, monkeypatch):
    FakePopen.rc = None                      # container cut short AND the model never answered
    orig = FakePopen.__init__

    def init(self, cmd, **kw):
        orig(self, cmd, **kw)
        self.stdout = iter([])

    monkeypatch.setattr(FakePopen, "__init__", init)
    row = A.run_pass(INST, arm(), "t", tmp_path, cap=1200, resume=False, sample=0)
    assert "container cut short" in row.error and "no model turns" in row.error


def test_api_key_passed_by_name_not_in_argv(tmp_path, fake_docker, monkeypatch):
    seen = {}
    orig = FakePopen.__init__

    def init(self, cmd, **kw):
        seen["env"] = kw.get("env")
        orig(self, cmd, **kw)

    monkeypatch.setattr(FakePopen, "__init__", init)
    monkeypatch.setenv("MYKEY", "sekrit")
    A.run_pass(INST, arm(api_key_env="MYKEY"), "t", tmp_path, cap=1200, resume=False, sample=0)
    assert "sekrit" not in " ".join(FakePopen.cmd) and "SWE25_API_KEY" in FakePopen.cmd
    assert seen["env"]["SWE25_API_KEY"] == "sekrit"
