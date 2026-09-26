"""Score arms: mean solved over complete seeds, range, union (solved in any seed), open cells."""
from __future__ import annotations

import json
from pathlib import Path

from swe25 import instances, metrics, score
from swe25.results import read_rows

BASELINE_DIR = Path(__file__).resolve().parents[1] / "baselines"


def all_ids() -> list[str]:
    return list(instances.CANONICAL_IDS)


def load_baselines() -> dict[str, list[dict]]:
    return {p.stem: read_rows([p]) for p in sorted(BASELINE_DIR.glob("*.jsonl"))}


def baseline_meta() -> dict[str, dict]:
    p = BASELINE_DIR / "arms.json"
    return json.loads(p.read_text()) if p.exists() else {}


def load_results(results_dir: Path) -> dict[str, list[dict]]:
    """User results: every results/<arm>.jsonl, grouped by the rows' model_id."""
    out: dict[str, list[dict]] = {}
    for r in read_rows(sorted(Path(results_dir).glob("*.jsonl"))):
        if r.get("model_id"):
            out.setdefault(r["model_id"], []).append(r)
    return out


def combined(results_dir: Path, include_baselines: bool, only: list[str]) -> tuple[dict, dict]:
    """The user's arms (marked user=True) plus, optionally, the shipped baselines. A baseline whose
    name collides with a user arm is shown as '<name> (baseline)'."""
    rows = load_results(results_dir)
    meta = {arm: {"label": arm, "user": True} for arm in rows}
    if include_baselines:
        bmeta = baseline_meta()
        for arm, brows in load_baselines().items():
            key = f"{arm} (baseline)" if arm in rows else arm
            rows[key] = [{**r, "model_id": key} for r in brows]
            meta[key] = bmeta.get(arm, {"label": arm})
    if only:
        rows = {k: v for k, v in rows.items() if k in only or k.removesuffix(" (baseline)") in only}
    return rows, meta


def _universe(arm: str, rows: list[dict], meta: dict, ids: list[str]) -> tuple[str, list[str]]:
    """The task set an arm is scored on: its subset from the metadata or its rows (the full 25 = `ids`)."""
    name = meta.get("subset") or next((r.get("subset") for r in reversed(rows) if r.get("subset")),
                                      None) or instances.FULL
    return name, (list(ids) if name == instances.FULL else instances.load_subset(name).ids)


def table(rows_by_arm: dict[str, list[dict]], meta: dict[str, dict], ids: list[str],
          compare: str | None = None) -> list[dict]:
    """Score each arm over its own subset; with `compare`, score every arm whose subset contains that
    subset over it alone (arms that did not run all of it are left out)."""
    cids = None
    if compare:
        cids = list(ids) if compare == instances.FULL else instances.load_subset(compare).ids
    out = []
    for arm, rows in rows_by_arm.items():
        m = meta.get(arm, {})
        agent = m.get("agent") or next((r.get("agent") for r in rows if r.get("agent")), "pi")
        subset, universe = _universe(arm, rows, m, ids)
        if cids is not None:
            if not set(cids) <= set(universe):
                continue
            universe = cids
        t = score.seed_table(rows, arm, universe, agent=agent)
        cost = metrics.arm_metrics(rows, arm, universe, agent, set(m.get("timing_invalid_seeds", [])))
        out.append({"arm": arm, "label": m.get("label", arm), "agent": agent, "seeds_complete": len(t.complete),
                    "mean": t.mean, "lo": t.lo, "hi": t.hi, "union": t.union, "open": t.open,
                    "per_seed": t.per_seed, "user": m.get("user", False), "subset": subset,
                    "n_ids": len(universe), **cost})
    out.sort(key=lambda t: (t["mean"] is None, -((t["mean"] or 0) / t["n_ids"]), t["arm"]))
    return out


def _range(t: dict) -> str:
    return "" if t["lo"] is None else (str(t["lo"]) if t["lo"] == t["hi"] else f"{t['lo']}–{t['hi']}")


def _mean(t: dict, n: int | None = None) -> str:
    return "—" if t["mean"] is None else f"{t['mean']:.2f} / {t.get('n_ids', n)}"


def _tasks(t: dict) -> str:
    return str(t["n_ids"]) if t["subset"] == instances.FULL else f"{t['n_ids']} ({t['subset']})"


def render_markdown(tbl: list[dict], n_ids: int) -> str:
    lines = ["| arm | model | agent | tasks | mean solved | range | complete seeds | union | open cells |",
             "|---|---|---|---|---|---|---|---|---|"]
    for t in tbl:
        lines.append(f"| `{t['arm']}` | {t['label']} | {t['agent']} | {_tasks(t)} | {_mean(t, n_ids)} | "
                     f"{_range(t)} | {t['seeds_complete']} | {t['union']} | {t['open']} |")
    lines += ["", "Cost per task (agent time; tokens generated per task, all passes):", "",
              "| arm | time per solve | time per attempt (median · mean) | tokens, all tasks (median · mean) "
              "| tokens, solved (median · mean) |", "|---|---|---|---|---|"]
    for t in tbl:
        lines.append(f"| `{t['arm']}` | {_d(t['sec_per_solve'])} | {_pair(t, 'sec_per_attempt', _d)} | "
                     f"{_pair(t, 'tok_all', _k)} | {_pair(t, 'tok_solved', _k)} |")
    return "\n".join(lines) + "\n"


def _d(x):
    return metrics.fmt_duration(x)


def _k(x):
    return metrics.fmt_tokens(x)


def _pair(t: dict, key: str, fmt) -> str:
    a, b = t[f"{key}_median"], t[f"{key}_mean"]
    return "—" if a is None else f"{fmt(a)} · {fmt(b)}"


def render_text(tbl: list[dict], n_ids: int) -> str:
    w = max([len(t["arm"]) for t in tbl] + [3])
    lines = [f"{'arm':<{w + 2}}{'mean':>10}  {'tasks':>5}  {'range':>6}  {'seeds':>5}  {'union':>5}  {'open':>4}  "
             f"per-seed solved"]
    for t in tbl:
        per = " ".join(f"s{s}:{v[0]}" + ("" if v[2] == 0 else f"(+{v[2]} open)")
                       for s, v in sorted(t["per_seed"].items()))
        star = " *" if t["user"] else ""
        lines.append(f"{t['arm'] + star:<{w + 2}}{_mean(t, n_ids):>10}  {t['n_ids']:>5}  {_range(t):>6}  "
                     f"{t['seeds_complete']:>5}  "
                     f"{t['union']:>5}  {t['open']:>4}  {per}")
    lines += ["", f"{'arm':<{w + 2}}{'time/solve':>10}  {'time/attempt med·mean':>21}  "
                  f"{'tokens all med·mean':>19}  {'tokens solved med·mean':>22}"]
    for t in tbl:
        lines.append(f"{t['arm']:<{w + 2}}{_d(t['sec_per_solve']):>10}  {_pair(t, 'sec_per_attempt', _d):>21}  "
                     f"{_pair(t, 'tok_all', _k):>19}  {_pair(t, 'tok_solved', _k):>22}")
    return "\n".join(lines) + "\n"


def readme_block() -> str:
    """The baseline tables embedded in README.md (a test keeps them in sync with baselines/)."""
    rows, meta, ids = load_baselines(), baseline_meta(), all_ids()
    main = render_markdown(table(rows, meta, ids), n_ids=len(ids))
    sub = render_markdown(table(rows, meta, ids, compare="winnable17"), n_ids=17).split("\n\nCost per task")[0]
    return (main + "\nEvery arm that ran all 17 tasks of the `winnable17` subset, scored on those 17 alone "
            "(arms on the full 25 are restricted to the same tasks):\n\n" + sub.rstrip("\n") + "\n")
