"""The frozen canonical-25 SWE-bench-Live slice (see data/README.md for provenance)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "canonical_25.json"
SUBSET_DIR = DATA_PATH.parent / "subsets"
FULL = "canonical25"
DATA_SHA256 = "927f2cfef10514e1893664c698a462503afaa68349a115ebf6b23b2d6df64ece"

CANONICAL_IDS: tuple[str, ...] = (
    "NVIDIA__NemoClaw-330", "QwenLM__qwen-code-3310", "RooCodeInc__Roo-Code-12135",
    "amir20__dozzle-4612", "chenhg5__cc-connect-567", "chimurai__http-proxy-middleware-1163",
    "code-charity__youtube-3708", "floci-io__floci-153", "karmada-io__karmada-7365",
    "kepano__defuddle-243", "kube-vip__kube-vip-1505", "kubernetes-sigs__controller-runtime-3494",
    "kubernetes__kops-18146", "lima-vm__lima-4803", "mikro-orm__mikro-orm-7464",
    "mnfst__manifest-1635", "mui__mui-x-22062", "nodejs__undici-5000",
    "open-telemetry__opentelemetry-go-8133", "openai__codex-plugin-cc-83", "reactjs__react-rails-1418",
    "sqlc-dev__sqlc-4383", "sveltejs__svelte-18039", "thlorenz__doctoc-328", "wxt-dev__wxt-2267",
)

REQUIRED = ("instance_id", "repo", "base_commit", "problem_statement", "docker_image", "test_patch",
            "patch", "test_cmds", "print_cmds", "log_parser", "FAIL_TO_PASS", "PASS_TO_PASS", "created_at")
OPTIONAL = ("_lang", "pull_number", "commit_url")


@cache
def load() -> dict[str, dict]:
    rows = json.loads(DATA_PATH.read_text())
    return {r["instance_id"]: r for r in rows}


@dataclass(frozen=True)
class Subset:
    name: str
    ids: list[str] = field(default_factory=list)
    description: str = ""


def load_subset(name_or_path: str) -> Subset:
    """A named task subset: `canonical25` (all), a built-in from data/subsets/, one from ./subsets/,
    or a path to a JSON file {"name", "description", "instances": [...]}."""
    if name_or_path == FULL:
        return Subset(FULL, list(CANONICAL_IDS), "all 25 tasks")
    p = Path(name_or_path)
    if not (p.suffix == ".json" and p.exists()):
        cands = [d / f"{name_or_path}.json" for d in (SUBSET_DIR, Path.cwd() / "subsets")]
        p = next((c for c in cands if c.exists()), None)
        if p is None:
            raise ValueError(f"unknown subset {name_or_path!r}: not built in (data/subsets/) and no "
                             f"subsets/{name_or_path}.json here")
    d = json.loads(p.read_text())
    name = d.get("name", p.stem)
    if not re.match(r"^[a-z0-9][a-z0-9._-]*$", str(name)):
        raise ValueError(f"subset name {name!r} must be lowercase letters, digits, '.', '_' or '-'")
    ids = list(d.get("instances") or [])
    bad = [i for i in ids if i not in CANONICAL_IDS]
    if bad:
        raise ValueError(f"subset {name}: {', '.join(bad)} not in the canonical 25")
    if not ids or len(set(ids)) != len(ids):
        raise ValueError(f"subset {name}: needs a non-empty list of distinct instance ids")
    keep = set(ids)
    return Subset(name, [i for i in CANONICAL_IDS if i in keep], d.get("description", ""))


def resolve_ids(only: str, universe: list[str] | None = None) -> list[str]:
    """`--only` value -> ordered instance ids within `universe` (default: all 25); empty means all."""
    universe = list(CANONICAL_IDS) if universe is None else universe
    if not only.strip():
        return list(universe)
    ids = [s.strip() for s in only.split(",") if s.strip()]
    bad = [i for i in ids if i not in CANONICAL_IDS]
    if bad:
        raise ValueError(f"{', '.join(bad)} not in the canonical 25")
    outside = [i for i in ids if i not in universe]
    if outside:
        raise ValueError(f"{', '.join(outside)} not in this arm's subset")
    return ids
