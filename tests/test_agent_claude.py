from pathlib import Path

import pytest

from swe25 import agent_claude as A
from swe25.config import Arm, ConfigError

FIX = Path(__file__).parent / "fixtures" / "claude_stream.jsonl"
INST = {"instance_id": "org__repo-1", "problem_statement": "Fix it.", "docker_image": "img"}
ARM = Arm(name="opus-5-medium", agent="claude", model="claude-opus-5", effort="medium")


def test_auth_prefers_oauth_token(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    assert A.auth_var() == "CLAUDE_CODE_OAUTH_TOKEN"


def test_auth_falls_back_to_api_key(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    assert A.auth_var() == "ANTHROPIC_API_KEY"


def test_missing_auth_is_config_error(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="claude setup-token"):
        A.auth_var()


def test_script():
    s = A.render_script("claude-opus-5", "medium", "CLAUDE_CODE_OAUTH_TOKEN")
    assert "timeout 1800 claude -p \"$(cat /work/problem.txt)\"" in s
    assert "--model claude-opus-5 --effort medium" in s
    assert "--permission-mode bypassPermissions" in s and "--output-format stream-json" in s
    assert 'runuser -u "$SWU"' in s and 'CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN"' in s
    assert "ANTHROPIC_API_KEY" not in s


def test_parse_stream():
    assert A.parse_stream(FIX.read_text()) == {"turns": 2, "tool_calls": 1, "output_tokens": 200,
                                                "total_generated": 200}


class FakeRun:
    def __init__(self, rc="0", docker_rc=0):
        self.rc, self.docker_rc = rc, docker_rc

    def __call__(self, cmd, **kw):
        FakeRun.cmd = cmd
        wd = Path(cmd[cmd.index("-v") + 1].split(":")[0])
        if self.rc is not None:
            (wd / "_claude_rc").write_text(self.rc)
        (wd / "claude_out.jsonl").write_text(FIX.read_text())
        import subprocess
        return subprocess.CompletedProcess(cmd, self.docker_rc, "", "")


def test_run_pass_keeps_secret_out_of_argv_and_row(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sekrit-token")
    monkeypatch.setattr(A.subprocess, "run", FakeRun(rc="124"))
    monkeypatch.setattr(A.docker, "safe", lambda *a, **k: None)
    row = A.run_pass(INST, ARM, "swe25-claude:x", tmp_path, sample=1)
    assert row.timed_out and row.agent == "claude" and row.turns == 2 and row.sample == 1
    assert "sekrit-token" not in " ".join(FakeRun.cmd) and "sekrit-token" not in str(row.to_dict())
    assert "CLAUDE_CODE_OAUTH_TOKEN" in FakeRun.cmd            # passed by name, value from the environment
    assert (tmp_path / "problem.txt").read_text() == "Fix it."


def test_run_pass_docker_failure_without_patch_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
    monkeypatch.setattr(A.subprocess, "run", FakeRun(rc=None, docker_rc=125))
    monkeypatch.setattr(A.docker, "safe", lambda *a, **k: None)
    row = A.run_pass(INST, ARM, "t", tmp_path, sample=0)
    assert row.error and not row.patch_nonempty and not row.timed_out
