"""One Pi agent pass (fresh or resume) inside an instance container.

The model sees only the task's problem statement. It is never told about any time limit: when a
pass hits its cap, `timeout` kills Pi, its edits are kept as model.patch, and a later resume pass
restores them and continues the same session with RESUME_NUDGE as the next user message.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from swe25 import docker
from swe25.config import Arm
from swe25.results import Row

MAX_TOKENS = 16000
PI_BASH_IDLE_S = 600
PI_BASH_WALL_S = 1800
GOPATH_EXPORT = "export PATH=$PATH:/usr/local/go/bin"
RESUME_NUDGE = ("You have more time now. Continue exactly where you left off and "
                "finish making the failing test(s) pass. Do not restart from scratch.")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}

_SCRIPT = r"""
%(gopath)s
cd /testbed
%(pre)s
timeout %(cap)s pi --print --mode json --provider swe25 --model "$PI_MODEL" \
   --no-context-files --approve --session-id run --name "%(name)s" \
   "$(cat %(promptfile)s)" 2> /work/_pi_err.txt
echo $? > /work/_pi_rc
git add -A
git diff --cached HEAD > /work/model.patch 2>/dev/null || git diff HEAD > /work/model.patch
"""
_RESTORE = ("[ -s /work/model.patch ] && (git apply /work/model.patch 2>/dev/null "
            "|| git apply --3way /work/model.patch 2>/dev/null || true)")


def container_url(endpoint: str) -> str:
    """The endpoint as seen from inside a container: loopback -> host.docker.internal, and a bare
    host:port gets the conventional /v1."""
    u = urlsplit(endpoint.strip())
    host = u.hostname or ""
    netloc = u.netloc
    if host in _LOCAL_HOSTS:
        netloc = "host.docker.internal" + (f":{u.port}" if u.port else "")
    path = u.path.rstrip("/") or "/v1"
    return urlunsplit((u.scheme, netloc, path, "", ""))


def models_json(arm: Arm) -> dict:
    return {"providers": {"swe25": {
        "baseUrl": container_url(arm.endpoint),
        "api": "openai-completions",
        "apiKey": "$SWE25_API_KEY",
        "authHeader": True,
        "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": True},
        "models": [{"id": arm.model, "reasoning": True, "contextWindow": arm.context, "maxTokens": MAX_TOKENS}],
    }}}


def render_script(cap: int, resume: bool, name: str) -> str:
    return _SCRIPT % {"gopath": GOPATH_EXPORT, "cap": int(cap), "pre": _RESTORE if resume else "",
                      "promptfile": "/work/resume.txt" if resume else "/work/problem.txt", "name": name[:60]}


def parse_transcript(text: str) -> dict:
    """Token/turn/tool metrics from Pi's `--mode json` event stream (usage summed per assistant
    message_end, never from streaming updates)."""
    turns = tool_calls = invalid = pf = out = cached = 0
    saw = False
    for ln in text.splitlines():
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if not isinstance(o, dict):
            continue
        saw = True
        t = o.get("type")
        if t == "tool_execution_start":
            tool_calls += 1
        elif t == "tool_execution_end" and o.get("isError"):
            invalid += 1
        elif t == "message_end" and (o.get("message") or {}).get("role") == "assistant":
            turns += 1
            u = o["message"].get("usage") or {}
            pf += u.get("input", 0) or 0
            out += u.get("output", 0) or 0
            cached += u.get("cacheRead", 0) or 0
    if not saw:
        return {}
    return {"turns": turns or None, "tool_calls": tool_calls or None, "tool_calls_invalid": invalid,
            "prefill_tokens": pf or None, "output_tokens": out or None, "total_generated": out or None,
            "prefill_cache_hit": round(cached / pf, 4) if pf else None}


TOUCH_EVERY_S = 30


def _live_read(proc, out_path: Path, label: str, t0: float) -> None:
    """Tee Pi's stdout JSONL into the transcript while printing a short live feed.

    `message_update` events are not written: each re-sends the whole reply-in-progress on every
    streamed chunk (~99.7% of the bytes), and the finished reply is in the following `message_end`.
    While a reply streams, the transcript's mtime is still refreshed so watchers can see the pass is live.
    """
    turns = tools = 0
    last_touch = time.monotonic()
    with out_path.open("w") as fh:
        for line in proc.stdout:
            if line.startswith('{"type":"message_update"'):
                now = time.monotonic()
                if now - last_touch >= TOUCH_EVERY_S:
                    fh.flush()
                    os.utime(out_path)
                    last_touch = now
                continue
            fh.write(line)
            last_touch = time.monotonic()
            try:
                o = json.loads(line)
            except Exception:
                continue
            ty, el = o.get("type"), int(time.perf_counter() - t0)
            if ty == "tool_execution_start":
                tools += 1
                print(f"      [{el}s] {label} tool#{tools} {o.get('toolName')}: {str(o.get('args'))[:70]}", flush=True)
            elif ty == "message_end" and (o.get("message") or {}).get("role") == "assistant":
                turns += 1
                u = o["message"].get("usage") or {}
                print(f"      [{el}s] {label} turn#{turns} out={u.get('output')}", flush=True)
            elif ty == "agent_end":
                print(f"      [{el}s] {label} agent finished ({turns} turns, {tools} tools)", flush=True)


def _prepare_fresh(inst: dict, arm: Arm, wd: Path, tdir: Path, agent_dir: Path) -> None:
    """Archive any earlier attempt (history is never deleted), then set up a clean session."""
    if tdir.exists() and any(tdir.glob("*.jsonl")):
        arch = wd / "archive" / str(time.time_ns())
        arch.mkdir(parents=True)
        for p in tdir.glob("*.jsonl"):
            shutil.move(str(p), str(arch / p.name))
        if (wd / "model.patch").exists():
            shutil.move(str(wd / "model.patch"), str(arch / "model.patch"))
    shutil.rmtree(agent_dir / "sessions", ignore_errors=True)
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "models.json").write_text(json.dumps(models_json(arm)))
    (wd / "problem.txt").write_text(inst["problem_statement"])
    (wd / "model.patch").unlink(missing_ok=True)


def run_pass(inst: dict, arm: Arm, tag: str, wd: Path, *, cap: int, resume: bool, sample: int) -> Row:
    """Run one agent pass and return its (ungraded) row. KeyboardInterrupt kills the container and
    propagates; the runner then records nothing for this pass."""
    iid = inst["instance_id"]
    row = Row(iid, arm.name, sample=sample, agent="pi", pass_kind="resume" if resume else "fresh",
              sampling=arm.sampling)
    wd.mkdir(parents=True, exist_ok=True)
    agent_dir = wd / ".pihome" / ".pi" / "agent"
    tdir = wd / "transcripts"
    if resume:
        (wd / "resume.txt").write_text(RESUME_NUDGE)
    else:
        _prepare_fresh(inst, arm, wd, tdir, agent_dir)
    (wd / "_pi_rc").unlink(missing_ok=True)
    tdir.mkdir(parents=True, exist_ok=True)
    transcript = tdir / f"{len(list(tdir.glob('*.jsonl'))):03d}_{row.pass_kind}.jsonl"
    cname = f"swe25-pi-{iid}-{arm.name}-s{sample}"[:120]
    key = os.environ.get(arm.api_key_env, "") if arm.api_key_env else ""
    mount = docker.bash_patch_mount(tag)          # raises PatchMismatch: never run an unpatched agent
    docker.safe(["docker", "rm", "-f", cname])
    cmd = ["docker", "run", "--rm", "--name", cname, "--platform", docker.PLATFORM,
           "-e", "HOME=/work/.pihome", "-e", "SWE25_API_KEY", "-e", f"PI_MODEL={arm.model}",
           "-e", f"PI_BASH_IDLE_TIMEOUT={PI_BASH_IDLE_S}", "-e", f"PI_BASH_WALL_TIMEOUT={PI_BASH_WALL_S}",
           "-v", f"{wd}:/work", *mount,
           "--add-host=host.docker.internal:host-gateway",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "1024", "--memory", "6g",
           tag, "bash", "-lc", render_script(cap, resume, iid)]
    label = f"s{sample}·{iid.split('__')[-1][:24]}"
    print(f"    -> {row.pass_kind} pass cap={cap}s transcript={transcript.name}", flush=True)
    t0 = time.perf_counter()
    # The key goes to docker by name through the environment, never on the command line.
    env = {**os.environ, "SWE25_API_KEY": key or "none"}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
    # Hard deadline: a wedged daemon can keep the container alive but silent, which would block the
    # stdout read forever. Killing the docker client EOFs the pipe whatever the daemon's state.
    deadline = cap + 300
    fired = threading.Event()

    def _kill():
        fired.set()
        docker.safe(["docker", "kill", cname])
        try:
            proc.kill()
        except Exception:
            pass

    wdog = threading.Timer(deadline, _kill)
    wdog.daemon = True
    wdog.start()
    try:
        _live_read(proc, transcript, label, t0)
        proc.wait(timeout=deadline)
    except KeyboardInterrupt:
        _kill()
        raise
    except subprocess.TimeoutExpired:
        _kill()
        row.error = "agent: host backstop timeout"
    except Exception as e:
        row.error = f"agent: {type(e).__name__}: {e}"
    finally:
        wdog.cancel()
        docker.safe(["docker", "rm", "-f", cname])
    if fired.is_set() and not row.error:
        row.error = "agent: deadline watchdog fired (daemon wedged / silent container)"
    row.wall_agent_s = round(time.perf_counter() - t0, 1)
    rc_file = wd / "_pi_rc"
    rc = rc_file.read_text().strip() if rc_file.exists() else ""
    row.timed_out = rc == "124"
    # The script writes _pi_rc as its last step before the diff, so a normal end or a timeout always
    # leaves one. Missing means the container was cut short externally: resumable, never a clean miss.
    if not rc and not row.error:
        row.error = "agent: container cut short (no exit code recorded)"
    # No assistant turn at all in THIS pass means the model was never reached (server down, wrong
    # model name, context error). That is an infrastructure failure, never a natural-end miss.
    this_pass = parse_transcript(transcript.read_text(errors="replace")) if transcript.exists() else {}
    if not this_pass.get("turns") and not row.timed_out:
        marker = f"agent: no model turns in this pass (pi rc={rc or '?'}; is the model server up?)"
        row.error = f"{row.error} | {marker}" if row.error else marker
    mp = wd / "model.patch"
    row.patch_nonempty = mp.exists() and mp.stat().st_size > 0
    combined = "".join(p.read_text(errors="replace") for p in sorted(tdir.glob("*.jsonl")))
    for k, v in parse_transcript(combined).items():
        if v is not None:
            setattr(row, k, v)
    return row
