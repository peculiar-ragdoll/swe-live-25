"""One Claude Code pass inside an instance container: single pass, 1800 s cap, no resume, as the
Opus/Sonnet baselines were produced.

Claude Code starts with a fresh HOME (no global config or memory), sees only the problem statement
in /testbed at the base commit, and is graded by the same grader as the Pi arms. The auth secret
is passed to docker by NAME (`-e VAR`), so it never appears on a command line, in a log or in a row.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from swe25 import docker
from swe25.config import Arm, ConfigError
from swe25.results import Row

CAP = 1800
AUTH_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")

_SCRIPT = r"""
cd /testbed
export HOME=/work/.chome; mkdir -p "$HOME"
# Claude Code will not bypass permissions as root -> run it as a fresh dedicated non-root user
# with a distinct uid, its own group only, and no privileged group membership.
SWU=swagent
id -u "$SWU" >/dev/null 2>&1 || useradd -u 61234 -m -s /bin/bash "$SWU" 2>/dev/null || adduser -D -u 61234 "$SWU" 2>/dev/null
for g in docker sudo wheel root adm staff; do gpasswd -d "$SWU" "$g" 2>/dev/null || deluser "$SWU" "$g" 2>/dev/null || true; done
echo "agent-user: $(id "$SWU" 2>&1)"
chown -R "$SWU" /testbed /work 2>/dev/null || true
runuser -u "$SWU" -- env HOME=/work/.chome %(authvar)s="$%(authvar)s" \
  timeout %(cap)s claude -p "$(cat /work/problem.txt)" \
    --model %(model)s --effort %(effort)s \
    --permission-mode bypassPermissions \
    --output-format stream-json --verbose \
    > /work/claude_out.jsonl 2> /work/_claude_err.txt
echo $? > /work/_claude_rc
git config --global --add safe.directory /testbed 2>/dev/null || true
git add -A
git diff --cached HEAD > /work/model.patch 2>/dev/null || git diff HEAD > /work/model.patch
"""  # noqa: E501


def auth_var() -> str:
    for v in AUTH_VARS:
        if os.environ.get(v):
            return v
    raise ConfigError("Claude arms need CLAUDE_CODE_OAUTH_TOKEN (run `claude setup-token`) or "
                      "ANTHROPIC_API_KEY in the environment")


def render_script(model: str, effort: str, authvar: str, cap: int = CAP) -> str:
    return _SCRIPT % {"cap": cap, "model": model, "effort": effort, "authvar": authvar}


def parse_stream(text: str) -> dict:
    turns = tools = out_tok = 0
    for ln in text.splitlines():
        try:
            o = json.loads(ln)
        except Exception:
            continue
        t = o.get("type")
        if t == "assistant":
            turns += 1
            out_tok += ((o.get("message") or {}).get("usage") or {}).get("output_tokens") or 0
        elif t == "user":
            tools += 1          # tool_result messages
    return {"turns": turns or None, "tool_calls": tools or None, "output_tokens": out_tok or None,
            "total_generated": out_tok or None}


def run_pass(inst: dict, arm: Arm, tag: str, wd: Path, *, sample: int) -> Row:
    iid = inst["instance_id"]
    row = Row(iid, arm.name, sample=sample, agent="claude", pass_kind="fresh")
    authvar = auth_var()
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "problem.txt").write_text(inst["problem_statement"])
    for stale in ("model.patch", "_claude_rc", "claude_out.jsonl", "_claude_err.txt"):
        (wd / stale).unlink(missing_ok=True)
    cname = f"swe25-claude-{iid}-{arm.name}-s{sample}"[:120]
    docker.safe(["docker", "rm", "-f", cname])
    cmd = ["docker", "run", "--rm", "--name", cname, "--platform", docker.PLATFORM,
           "-e", "HOME=/work/.chome", "-e", authvar,
           "-v", f"{wd}:/work", "--add-host=host.docker.internal:host-gateway",
           "--security-opt", "no-new-privileges", "--pids-limit", "1024", "--memory", "6g",
           tag, "bash", "-lc", render_script(arm.model, arm.effort or "medium", authvar)]
    print(f"    -> claude pass cap={CAP}s ({arm.model}, effort={arm.effort})", flush=True)
    t0 = time.perf_counter()
    docker_rc = None
    try:
        docker_rc = subprocess.run(cmd, capture_output=True, text=True, timeout=CAP + 300).returncode
    except KeyboardInterrupt:
        docker.safe(["docker", "kill", cname])
        raise
    except subprocess.TimeoutExpired:
        docker.safe(["docker", "kill", cname])
        row.error = "claude: host backstop timeout"
    finally:
        docker.safe(["docker", "rm", "-f", cname])
    row.wall_agent_s = round(time.perf_counter() - t0, 1)
    rc_file = wd / "_claude_rc"
    rc = rc_file.read_text().strip() if rc_file.exists() else ""
    row.timed_out = rc == "124"
    mp = wd / "model.patch"
    row.patch_nonempty = mp.exists() and mp.stat().st_size > 0
    if not row.patch_nonempty and not row.timed_out and not row.error and (docker_rc or (rc and rc != "0")):
        err = wd / "_claude_err.txt"
        tail = err.read_text(errors="replace")[-300:] if err.exists() else ""
        row.error = f"claude: rc={rc or docker_rc} {tail}".strip()
    for k, v in parse_stream((wd / "claude_out.jsonl").read_text(errors="replace")
                             if (wd / "claude_out.jsonl").exists() else "").items():
        if v is not None:
            setattr(row, k, v)
    return row
