"""Result rows: one JSON line per agent pass, appended to results/<arm>.jsonl.

Rows are the single source of truth. The runner derives every cell's state from them, and
`summarize` scores them, so an interrupted run resumes by simply being run again.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from swe25 import __version__

_LOCK = threading.Lock()


@dataclass
class Row:
    instance_id: str
    model_id: str
    sample: int = 0
    resolved: bool = False              # every FAIL_TO_PASS and PASS_TO_PASS test passes
    patch_nonempty: bool = False
    wall_agent_s: float = 0.0
    wall_grade_s: float = 0.0
    timed_out: bool = False             # the agent hit this pass's time cap (exit 124)
    turns: int | None = None
    tool_calls: int | None = None
    tool_calls_invalid: int | None = None
    prefill_tokens: int | None = None
    output_tokens: int | None = None
    total_generated: int | None = None
    prefill_cache_hit: float | None = None
    f2p_pass: int = 0
    f2p_total: int = 0
    p2p_pass: int = 0
    p2p_total: int = 0
    error: str | None = None
    ts: float = 0.0                     # write time; the only ordering key ("which pass is latest")
    agent: str = "pi"                   # "pi" | "claude"
    pass_kind: str = "fresh"            # "fresh" | "resume"
    cum_wall_s: float = 0.0             # agent wall summed over this cell's passes, this one included
    sampling: dict | None = None        # the arm's declared sampling (applied by the model server)
    subset: str = "canonical25"         # the task subset this arm is scored on
    harness_version: str = __version__

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d["ts"]:
            d["ts"] = time.time()
        return d


def append_row(path: Path, row: Row | dict) -> dict:
    d = row.to_dict() if isinstance(row, Row) else dict(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.open("a") as fh:
        fh.write(json.dumps(d) + "\n")
        fh.flush()
    return d


def read_rows(paths: Iterable[Path]) -> list[dict]:
    """All rows from `paths`, oldest first by `ts`. Blank or corrupt lines (e.g. a write cut off
    by a crash) are skipped, never fatal."""
    rows = []
    for p in paths:
        try:
            text = Path(p).read_text()
        except FileNotFoundError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict):
                rows.append(d)
    rows.sort(key=lambda r: r.get("ts") or 0)
    return rows
