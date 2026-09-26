from pathlib import Path

from swe25 import doctor as D
from swe25.config import Arm, Settings

S = Settings(work_dir=Path("/tmp/w"), results_dir=Path("/tmp/r"), min_free_gb=20)


def test_all_checks_reported_and_failure_sets_rc(monkeypatch):
    monkeypatch.setattr(D, "CHECKS", [lambda s, a: [(True, "one ok")],
                                      lambda s, a: [(False, "two broken")],
                                      lambda s, a: [(None, "three warns")]])
    lines = []
    rc = D.run(S, {}, out=lines.append)
    assert rc == 1 and len(lines) == 3 and lines[1].startswith("✗")


def test_crashing_check_is_a_failure_not_a_traceback(monkeypatch):
    def boom(s, a):
        raise RuntimeError("docker exploded")
    monkeypatch.setattr(D, "CHECKS", [boom])
    lines = []
    assert D.run(S, {}, out=lines.append) == 1 and "docker exploded" in lines[0]


def test_claude_arm_without_auth_fails(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = D.check_arms(S, {"o": Arm(name="o", agent="claude", model="x", effort="medium")})
    assert res[0][0] is False and "setup-token" in res[0][1]
