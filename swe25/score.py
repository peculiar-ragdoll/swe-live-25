"""Scoring rules, shared by the runner (what to do next) and `summarize` (what the arm scored).

A *cell* is one (model, instance, seed). Its verdict is:
  solved  any real pass was graded resolved (a solve is permanent within its seed)
  miss    the latest real pass ended naturally; or it was capped and the cell is out of budget
          (Pi: cumulative agent wall >= the 4 h ceiling; Claude: single pass, a timeout is final)
  open    nothing real has run yet, or the latest pass was cut off with budget left (resumable)
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from statistics import mean
from typing import Literal

CEILING_S = 14400

Verdict = Literal["solved", "miss", "open"]


def is_real(r: dict) -> bool:
    """False for a content-free row (died at launch, or a phantom 'solve' with no work behind it)."""
    if r.get("turns"):
        return True
    if r.get("patch_nonempty"):
        return True
    return (r.get("wall_agent_s") or 0) > 0.2


def is_capped(r: dict) -> bool:
    """The pass was cut off rather than ending on its own: time cap hit, or infrastructure error."""
    return r.get("timed_out") is True or bool(r.get("error"))


def cum_wall(rows: Iterable[dict]) -> float:
    return float(sum((r.get("wall_agent_s") or 0) for r in rows if is_real(r)))


def cell_verdict(rows: list[dict], agent: str, ceiling: float = CEILING_S) -> Verdict:
    real = sorted((r for r in rows if is_real(r)), key=lambda r: r.get("ts") or 0)
    if not real:
        return "open"
    if any(r.get("resolved") is True for r in real):
        return "solved"
    last = real[-1]
    if not is_capped(last):
        return "miss"
    if agent == "claude":
        # Single pass, no resume: a timeout is final. An error that left no patch is an
        # infrastructure failure (the run never really happened), so the cell is re-run.
        return "open" if (last.get("timed_out") is not True and not last.get("patch_nonempty")) else "miss"
    if cum_wall(real) >= ceiling:
        return "miss"
    return "open"


def cell_rows(rows: Iterable[dict]) -> dict[tuple[str, str, int], list[dict]]:
    """Real rows grouped per (model, instance, seed), oldest first."""
    out: dict[tuple[str, str, int], list[dict]] = {}
    for r in sorted(rows, key=lambda r: r.get("ts") or 0):
        if not is_real(r):
            continue
        out.setdefault((r.get("model_id"), r.get("instance_id"), int(r.get("sample", 0))), []).append(r)
    return out


@dataclass
class SeedTable:
    per_seed: dict[int, tuple[int, int, int]] = field(default_factory=dict)   # seed -> (solved, settled, open)
    complete: list[int] = field(default_factory=list)   # solved counts of complete seeds, seed order
    union: int = 0                                      # instances solved in at least one seed
    open: int = 0                                       # open cells across all seeds present

    @property
    def mean(self) -> float | None:
        return round(mean(self.complete), 2) if self.complete else None

    @property
    def lo(self) -> int | None:
        return min(self.complete) if self.complete else None

    @property
    def hi(self) -> int | None:
        return max(self.complete) if self.complete else None


def seed_table(rows: Iterable[dict], model: str, ids: list[str], agent: str,
               ceiling: float = CEILING_S) -> SeedTable:
    """Per-seed scores for one arm. A seed is complete only when every instance has a settled
    verdict (solved or miss); the headline mean is over complete seeds only."""
    cells = cell_rows(r for r in rows if r.get("model_id") == model)
    seeds = sorted({s for (_, _, s) in cells})
    t = SeedTable()
    solved_any: set[str] = set()
    for s in seeds:
        solved = settled = n_open = 0
        for iid in ids:
            v = cell_verdict(cells.get((model, iid, s), []), agent, ceiling)
            if v == "solved":
                solved += 1
                settled += 1
                solved_any.add(iid)
            elif v == "miss":
                settled += 1
            else:
                n_open += 1
        t.per_seed[s] = (solved, settled, n_open)
        t.open += n_open
        if n_open == 0:
            t.complete.append(solved)
    t.union = len(solved_any)
    return t
