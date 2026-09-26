"""`swe25 serve-llamacpp`: start llama-server with exactly an arm's context and sampling.

The agent sends no sampling parameters, so whatever the server was started with is what the model
samples at (llama-server's own default temperature is 0.8). Runs in the foreground: start it in its
own terminal and stop it with Ctrl-C.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from swe25.config import Arm, ConfigError

_LOCAL = {"127.0.0.1", "localhost", "0.0.0.0"}


def resolve(arm: Arm, gguf: str | None, binary: str | None) -> tuple[str, str]:
    serve = arm.serve or {}
    g = gguf or serve.get("gguf")
    if not g:
        raise ConfigError(f"arm {arm.name}: pass --gguf or set serve.gguf in arms.yaml")
    return str(g), binary or serve.get("bin") or "llama-server"


def build_cmd(arm: Arm, gguf: str, binary: str) -> list[str]:
    if arm.agent != "pi":
        raise ConfigError(f"arm {arm.name} is a {arm.agent} arm; only pi arms are served locally")
    if not arm.sampling or set(arm.sampling) != {"temp", "top_p", "top_k", "min_p"}:
        raise ConfigError(f"arm {arm.name}: declare all four sampling values (temp, top_p, top_k, min_p)")
    u = urlsplit(arm.endpoint)
    if u.hostname not in _LOCAL or not u.port:
        raise ConfigError(f"arm {arm.name}: endpoint must be a local http://127.0.0.1:<port>/v1 to serve it here")
    s = arm.sampling
    # --host 0.0.0.0 so the agent containers reach it via host.docker.internal
    return [binary, "-m", gguf, "--port", str(u.port), "--host", "0.0.0.0", "-c", str(arm.context), "-ngl", "99",
            "--jinja", "--temp", str(s["temp"]), "--top-p", str(s["top_p"]), "--top-k", str(s["top_k"]),
            "--min-p", str(s["min_p"])]


def serve(arm: Arm, gguf: str | None, binary: str | None) -> None:
    g, b = resolve(arm, gguf, binary)
    cmd = build_cmd(arm, g, b)
    print("exec:", " ".join(cmd), flush=True)
    os.execvp(cmd[0], cmd)
