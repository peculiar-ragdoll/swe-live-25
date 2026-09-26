"""arms.yaml: which models to run and where they are served."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SAMPLING_KEYS = {"temp", "top_p", "top_k", "min_p"}
DEFAULT_CONTEXT = 262144


class ConfigError(Exception):
    pass


@dataclass
class Arm:
    name: str
    agent: str                          # "pi" | "claude"
    model: str                          # model id sent to the server / Claude model id
    endpoint: str | None = None         # OpenAI-compatible base URL (pi arms)
    api_key_env: str | None = None      # env var holding a bearer token for the endpoint, if any
    context: int = DEFAULT_CONTEXT      # advertised to Pi; must equal the server's context size
    sampling: dict | None = None        # declared; the server applies it (Pi sends none)
    effort: str | None = None           # claude arms
    serve: dict | None = None           # optional llama.cpp launch block: {gguf, bin}
    meta: dict = field(default_factory=dict)


@dataclass
class Settings:
    work_dir: Path
    results_dir: Path
    min_free_gb: float


def _arm(name: str, d: dict) -> Arm:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ConfigError(f"arm name {name!r} must be lowercase letters, digits, '.', '_' or '-'")
    if not isinstance(d, dict):
        raise ConfigError(f"arm {name}: expected a mapping")
    agent = d.get("agent")
    if agent not in ("pi", "claude"):
        raise ConfigError(f"arm {name}: agent must be 'pi' or 'claude', got {agent!r}")
    if not d.get("model"):
        raise ConfigError(f"arm {name}: model is required")
    sampling = d.get("sampling")
    if sampling is not None:
        if not isinstance(sampling, dict) or set(sampling) - SAMPLING_KEYS:
            raise ConfigError(f"arm {name}: sampling keys must be among {sorted(SAMPLING_KEYS)}")
    a = Arm(name=name, agent=agent, model=str(d["model"]), endpoint=d.get("endpoint"),
            api_key_env=d.get("api_key_env"), context=int(d.get("context", DEFAULT_CONTEXT)),
            sampling=sampling, effort=d.get("effort"), serve=d.get("serve"), meta=d.get("meta") or {})
    if agent == "pi" and not a.endpoint:
        raise ConfigError(f"arm {name}: pi arms need an endpoint (e.g. http://127.0.0.1:8080/v1)")
    if agent == "claude":
        a.effort = a.effort or "medium"
    return a


def load(path: Path) -> tuple[Settings, dict[str, Arm]]:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"{path} not found — copy arms.example.yaml to arms.yaml and edit it")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML: {e}") from e
    settings = Settings(
        work_dir=Path(os.path.expanduser(str(raw.get("work_dir", "~/swe25-work")))).resolve(),
        results_dir=Path(os.path.expanduser(str(raw.get("results_dir", "results")))).resolve(),
        min_free_gb=float(os.environ.get("SWE25_MIN_FREE_GB", raw.get("min_free_gb", 20))),
    )
    arms = {name: _arm(name, d) for name, d in (raw.get("arms") or {}).items()}
    return settings, arms
