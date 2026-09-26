"""Checks run before any Docker work: is the model server there, and does it serve what the arm
declares? Used by `swe25 run` (hard failures stop the run) and `swe25 doctor` (reported)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from swe25.config import Arm


class PreflightError(RuntimeError):
    pass


def _get(url: str, arm: Arm, timeout: float = 10.0):
    req = urllib.request.Request(url)
    if arm.api_key_env and os.environ.get(arm.api_key_env):
        req.add_header("Authorization", f"Bearer {os.environ[arm.api_key_env]}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def _root(endpoint: str) -> str:
    e = endpoint.rstrip("/")
    return e[: -len("/v1")] if e.endswith("/v1") else e


def endpoint_models(arm: Arm) -> list[str]:
    url = arm.endpoint.rstrip("/") + "/models"
    try:
        d = _get(url, arm)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise PreflightError(f"arm {arm.name}: model server not reachable at {url} ({e})") from e
    return [m.get("id") for m in (d or {}).get("data", []) if isinstance(m, dict)]


def server_ctx(arm: Arm) -> int | None:
    """The context size a llama.cpp server is actually running with, or None if unknown."""
    try:
        p = _get(_root(arm.endpoint) + "/props", arm, timeout=5)
    except Exception:
        return None
    if not isinstance(p, dict):
        return None
    n = (p.get("default_generation_settings") or {}).get("n_ctx") or p.get("n_ctx")
    return int(n) if n else None


def check_pi_arm(arm: Arm) -> list[str]:
    """Raise PreflightError on a hard problem; return warnings otherwise."""
    warnings = []
    ids = endpoint_models(arm)
    if ids and arm.model not in ids:
        warnings.append(f"arm {arm.name}: server lists {ids}, not {arm.model!r} (fine for single-model "
                        f"servers such as llama.cpp, which answer any name)")
    n_ctx = server_ctx(arm)
    if n_ctx is None:
        warnings.append(f"arm {arm.name}: cannot verify the server's context size; make sure it is "
                        f"{arm.context} or the agent will overflow it mid-run")
    elif n_ctx != arm.context:
        raise PreflightError(f"arm {arm.name}: server context is {n_ctx} but the arm declares {arm.context}; "
                             f"restart the server with -c {arm.context} or change `context`")
    return warnings
