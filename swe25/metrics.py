"""Cost metrics, as on the original dashboard: time per solve, time per attempt, tokens per cell.

Time figures use only complete seeds (every cell settled) and skip seeds whose timing is known to be
invalid. A cell's time is its agent wall summed over the fresh pass and every resume. Token counts
use every settled cell. Per-row token counts are cumulative across a cell's pass chain (each pass
re-reads the whole session), so a cell's tokens are the sum of the increases, not the sum of rows.
Claude arms get no token figures: Claude Code's stream does not report per-turn usage reliably.
"""
from __future__ import annotations

from statistics import mean, median

from swe25 import score


def cell_tokens(rows: list[dict]) -> int | None:
    total, prev, seen = 0, 0, False
    for r in sorted(rows, key=lambda r: r.get("ts") or 0):
        t = r.get("output_tokens")
        if t is None:
            continue
        seen = True
        total += t - prev if t >= prev else t       # a drop means a new chain (fresh restart)
        prev = t
    return total if seen else None


def _med_mean(xs: list[float]) -> tuple[float | None, float | None]:
    return (median(xs), mean(xs)) if xs else (None, None)


def arm_metrics(rows, model: str, ids: list[str], agent: str, timing_invalid: set[int] | frozenset = frozenset(),
                ceiling: float = score.CEILING_S) -> dict:
    cells = score.cell_rows(r for r in rows if r.get("model_id") == model)
    seeds = sorted({s for (_, _, s) in cells})
    work = solves = 0.0
    walls: list[float] = []
    tok_all: list[int] = []
    tok_solved: list[int] = []
    for s in seeds:
        verdicts = {iid: score.cell_verdict(cells.get((model, iid, s), []), agent, ceiling) for iid in ids}
        for iid, v in verdicts.items():
            if v == "open":
                continue
            t = cell_tokens(cells[(model, iid, s)])
            if t is not None and agent != "claude":
                tok_all.append(t)
                if v == "solved":
                    tok_solved.append(t)
        if s in timing_invalid or any(v == "open" for v in verdicts.values()):
            continue
        seed_walls = [score.cum_wall(cells[(model, iid, s)]) for iid in ids]
        walls += seed_walls
        n = sum(1 for v in verdicts.values() if v == "solved")
        if n:
            work += sum(seed_walls)
            solves += n
    am, aa = _med_mean(walls)
    tm, ta = _med_mean(tok_all)
    sm, sa = _med_mean(tok_solved)
    return {"sec_per_solve": work / solves if solves else None, "attempts": len(walls),
            "sec_per_attempt_median": am, "sec_per_attempt_mean": aa,
            "tok_all_median": tm, "tok_all_mean": ta, "tok_solved_median": sm, "tok_solved_mean": sa}


def fmt_duration(s: float | None) -> str:
    if s is None:
        return "—"
    s = int(round(s))
    if s >= 3600:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    return f"{s // 60}m {s % 60:02d}s"


def fmt_tokens(n: float | None) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{round(n / 1000)}k"
    return str(int(round(n)))
