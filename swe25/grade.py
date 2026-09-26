"""Grading: a fresh instance container, the model's patch plus the hidden test patch, the repo's own
test commands, and the instance's embedded log parser.

resolved = at least one FAIL_TO_PASS test, every FAIL_TO_PASS test passes and every PASS_TO_PASS
test still passes (standard SWE-bench resolution).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from swe25 import docker
from swe25.results import Row

GRADE_TIMEOUT = 3600
GOPATH_EXPORT = "export PATH=$PATH:/usr/local/go/bin"

# Tests dropped from FAIL_TO_PASS before scoring: live-network integration tests (httpbin.org) that
# cannot pass in the offline grading sandbox whatever the fix. Two different models produced
# 172/180 with every PASS_TO_PASS green and only these eight failing.
F2P_EXCLUDE: dict[str, set[str]] = {
    "chimurai__http-proxy-middleware-1163": {
        "http integration should work with raw node http RequestHandler",
        "responseInterceptor() intercept responses should return totally different response from "
        "http://httpbin.org/json",
        "responseInterceptor() intercept compressed responses should return decompressed gzipped response from "
        "http://httpbin.org/gzip",
        "responseInterceptor() intercept responses with original headers should proxy and return original "
        "headers from http://httpbin.org/cookies/set/cookie/monster",
        "responseInterceptor() intercept compressed responses should return decompressed deflated response from "
        "http://httpbin.org/deflate",
        "responseInterceptor() intercept responses should return totally different response from "
        "http://httpbin.org/image",
        "responseInterceptor() intercept compressed responses should return decompressed brotli response "
        "http://httpbin.org/brotli",
        "responseInterceptor() intercept responses should support double bytes characters "
        "http://httpbin.org/json",
    },
}

_GRADE_SCRIPT = r"""
%(gopath)s
cd /testbed
git checkout -- . 2>/dev/null; git clean -fd 2>/dev/null
[ -s /work/model.patch ] && (git apply /work/model.patch 2>/work/_apply_model.err || git apply --3way /work/model.patch 2>>/work/_apply_model.err || echo MODEL_APPLY_FAIL >/work/_model_apply_fail)
git apply /work/test.patch 2>/work/_apply_test.err || git apply --3way /work/test.patch 2>>/work/_apply_test.err
{ %(testcmds)s ; } > /work/_test_stdout.log 2>&1 || true
{ %(printcmds)s ; } > /work/_parser_input.log 2>&1 || true
mkdir -p /work/reports
cp -r /testbed/reports/. /work/reports/ 2>/dev/null || true
find /testbed -maxdepth 3 -name '*.json' -path '*report*' -exec cp {} /work/reports/ \; 2>/dev/null || true
"""  # noqa: E501


def _joincmds(v) -> str:
    if not v:
        return "true"
    return "\n".join(v) if isinstance(v, list) else str(v)


def _apply_parser(parser_src: str, log: str) -> dict:
    ns: dict = {}
    exec(parser_src, ns)  # the dataset's own parser (json/re/xml only)
    fn = ns.get("parser") or next((v for v in ns.values() if callable(v)), None)
    return fn(log) if fn else {}


def _tests(v) -> list[str]:
    if isinstance(v, str):
        v = json.loads(v)
    return list(v or [])


def score_logs(inst: dict, candidates: list[str]) -> tuple[dict, str | None]:
    """Feed each candidate log to the instance's parser separately (JSON parsers need one clean
    blob) and keep the parse with the most statuses; earlier candidates win ties."""
    status: dict = {}
    last_err = None
    for cand in candidates:
        try:
            s = _apply_parser(inst["log_parser"], cand)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue
        if isinstance(s, dict) and len(s) > len(status):
            status = s
    return status, (last_err if not status else None)


def apply_verdict(inst: dict, status: dict, row: Row) -> None:
    drop = F2P_EXCLUDE.get(inst["instance_id"], set())
    f2p = [t for t in _tests(inst.get("FAIL_TO_PASS")) if t not in drop]
    p2p = _tests(inst.get("PASS_TO_PASS"))

    def ok(t):
        return str(status.get(t)).lower() in ("pass", "passed")

    row.f2p_total, row.p2p_total = len(f2p), len(p2p)
    row.f2p_pass = sum(1 for t in f2p if ok(t))
    row.p2p_pass = sum(1 for t in p2p if ok(t))
    row.resolved = row.f2p_total > 0 and row.f2p_pass == row.f2p_total and row.p2p_pass == row.p2p_total


def _candidates(wd: Path) -> list[str]:
    out = []
    pin = wd / "_parser_input.log"          # print_cmds output: the parser's canonical input
    if pin.exists():
        out.append(pin.read_text(errors="replace"))
    rep = wd / "reports"                     # collected *report*.json files
    if rep.exists():
        blob = "".join(p.read_text(errors="replace") + "\n" for p in sorted(rep.rglob("*.json")))
        if blob.strip():
            out.append(blob)
    tout = wd / "_test_stdout.log"           # raw test output
    if tout.exists():
        out.append(tout.read_text(errors="replace"))
    return out


def _add_error(row: Row, msg: str) -> None:
    row.error = f"{row.error} | {msg}" if row.error else msg


def container_name(arm: str, iid: str, sample: int) -> str:
    return f"swe25-grade-{arm}-{iid}-s{sample}"[:120]


def grade(inst: dict, wd: Path, row: Row, timeout: int = GRADE_TIMEOUT, name: str | None = None) -> None:
    """Grade `wd/model.patch` for `inst`, filling the test counts and `resolved` on `row`. A named
    container can be killed from outside (the runner does so when the user abandons a run)."""
    for stale in ("_parser_input.log", "_test_stdout.log"):
        (wd / stale).unlink(missing_ok=True)
    shutil.rmtree(wd / "reports", ignore_errors=True)
    (wd / "test.patch").write_text(inst["test_patch"])
    script = _GRADE_SCRIPT % {"gopath": GOPATH_EXPORT, "testcmds": _joincmds(inst.get("test_cmds")),
                              "printcmds": _joincmds(inst.get("print_cmds"))}
    named = ["--name", name] if name else []
    if name:
        docker.safe(["docker", "rm", "-f", name])
    cmd = ["docker", "run", "--rm", *named, "--platform", docker.PLATFORM, "-v", f"{wd}:/work",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "8g",
           inst["docker_image"], "bash", "-lc", script]
    t0 = time.perf_counter()
    try:
        docker.sh(cmd, timeout)
    except subprocess.TimeoutExpired:
        if name:
            docker.safe(["docker", "kill", name])
        _add_error(row, f"grade_timeout:{timeout}s")
        print(f"!! GRADE TIMEOUT {row.instance_id} [{row.model_id}] after {timeout}s: scored on partial "
              f"output (treat as needs-regrade)", flush=True)
    except Exception as e:
        _add_error(row, f"grade: {type(e).__name__}: {e}")
    row.wall_grade_s = round(time.perf_counter() - t0, 1)
    status, err = score_logs(inst, _candidates(wd))
    if err:
        _add_error(row, f"parser: {err}")
    apply_verdict(inst, status, row)


def gold_check(ids: list[str], work_dir: Path, min_free_gb: float = 20.0) -> list[dict]:
    """Grade the dataset's own gold patch: every instance must come out resolved, or the local
    Docker/grading setup is broken and model results would be meaningless."""
    from swe25 import instances

    insts = instances.load()
    images = docker.ImageSession(min_free_gb)
    out = []
    for iid in ids:
        inst = insts[iid]
        wd = work_dir / f"__gold__{iid}"
        shutil.rmtree(wd, ignore_errors=True)
        wd.mkdir(parents=True)
        (wd / "model.patch").write_text(inst["patch"])
        row = Row(iid, "GOLD", patch_nonempty=True)
        try:
            images.base(inst)
            grade(inst, wd, row)
        finally:
            images.release(inst)
        out.append({"id": iid, "resolved": row.resolved, "f2p": f"{row.f2p_pass}/{row.f2p_total}",
                    "p2p": f"{row.p2p_pass}/{row.p2p_total}", "grade_s": row.wall_grade_s, "error": row.error})
    return out
