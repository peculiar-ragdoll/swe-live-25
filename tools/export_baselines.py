#!/usr/bin/env python3
"""One-off: export the published arms' result rows on the canonical 25 into baselines/.

    python tools/export_baselines.py --src <bench-harness>/results [--out baselines]

Reads each arm's rows from the same result files the original dashboard scored, keeps only rows
for the 25 instances, stamps an explicit `ts` (older rows were ordered by the file name's epoch),
drops content-free rows, refuses any row without a `timed_out` flag, keeps only scoring and metric
fields, and writes baselines/<arm>.jsonl for every arm with at least one complete seed (only its
complete seeds are kept, so every baseline number comes from fully settled seeds).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swe25 import instances, score  # noqa: E402
from swe25.results import Row  # noqa: E402

LOCAL = "sweb_dirk_*.jsonl"
# (arm, result-file glob, agent[, subset]) -- the published arms; subset defaults to the canonical 25
ARMS = [
    ("dirk-qwen3.8-27b", LOCAL, "pi"), ("qwen3.8-27b-stock-medium", LOCAL, "pi"),
    ("nail-qwen3.6-35b-a3b", LOCAL, "pi"), ("tiel", LOCAL, "pi"), ("cybertiel", LOCAL, "pi"),
    ("cybertiel-loose", LOCAL, "pi"), ("cybertiel-fc", LOCAL, "pi"), ("ornith", LOCAL, "pi"),
    ("kat-coder", LOCAL, "pi"), ("lynx", LOCAL, "pi"), ("stock-35b-a3b", LOCAL, "pi"),
    ("tiel-mini", LOCAL, "pi"), ("swift-q4-vendor-medium", LOCAL, "pi"), ("swift-q4-sharp", LOCAL, "pi"),
    ("qwen38-q4-stock-medium", LOCAL, "pi"), ("dirk-q4", LOCAL, "pi"),
    ("opus-4.6-medium", "sweb_opus46_*.jsonl", "claude"), ("opus-5-medium", "sweb_opus5_*.jsonl", "claude"),
    ("sonnet-5-medium", "sweb_sonnet_*.jsonl", "claude"),
    # small-model floor probes and Haiku, run (or settled) on the 17-task winnable subset only
    ("spark-x25-4b-q6", LOCAL, "pi", "winnable17"), ("spark-x25-4b-q8-stock", LOCAL, "pi", "winnable17"),
    ("haiku-4.5-high", "sweb_haiku_*.jsonl", "claude", "winnable17"),
]
KEEP = [f.name for f in fields(Row)]
# Declared sampling for arms whose older rows predate the per-row sampling stamp (the original
# dashboard's fallback table). The model server applied these; the agent sends none.
REC = {"temp": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0}
LOOSE = {"temp": 0.6, "top_p": 0.95, "top_k": 40, "min_p": 0.05}
T10 = {"temp": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0}
DECLARED = {"cybertiel-loose": LOOSE, "swift-q4-vendor-medium": T10, "swift-q4-sharp": T10,
            "qwen38-q4-stock-medium": T10, "dirk-q4": T10}


def sampling_of(arm: str, agent: str, stamped: dict | None) -> dict | None:
    if agent == "claude":
        return None
    if stamped:
        return {k: float(stamped[k]) if k != "top_k" else int(stamped[k]) for k in REC if k in stamped}
    return dict(DECLARED.get(arm, REC))


def file_epoch(path: str) -> float:
    """Chronological rank of a pre-`ts` results file from its name (the original n=1 file first)."""
    b = os.path.basename(path)
    if "_n1" in b:
        return 0.0
    m = re.findall(r"(\d{10})", b)
    return float(m[-1]) if m else 1.0


def arm_rows(src: Path, arm: str, pattern: str, agent: str, subset: str = instances.FULL) -> list[dict]:
    ids = set(instances.load_subset(subset).ids)
    raw = []
    for path in sorted(glob.glob(str(src / pattern)), key=lambda p: (file_epoch(p), p)):
        for n, line in enumerate(open(path)):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("model_id") != arm or r.get("instance_id") not in ids:
                continue
            t = r.get("ts") if isinstance(r.get("ts"), (int, float)) and r.get("ts") else file_epoch(path)
            raw.append((t, path, n, r))
    raw.sort(key=lambda x: (x[0], file_epoch(x[1]), x[1], x[2]))
    out = []
    for i, (t, path, n, r) in enumerate(raw):
        if not score.is_real(r):
            continue
        if "timed_out" not in r:
            raise SystemExit(f"{arm}: row without timed_out in {os.path.basename(path)}:{n + 1}; refusing to guess")
        d = {k: r.get(k) for k in KEEP if k in r}
        d.update(agent=agent, ts=round(t + i * 1e-6, 6), harness_version="bench-qwen36", subset=subset)
        d["sampling"] = sampling_of(arm, agent, r.get("sampling"))
        if d.get("error"):
            d["error"] = str(d["error"])[:80]
        out.append(d)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True, help="the original harness results directory")
    ap.add_argument("--out", type=Path, default=Path("baselines"))
    a = ap.parse_args()
    a.out.mkdir(exist_ok=True)
    for arm, pattern, agent, *rest in ARMS:
        subset = rest[0] if rest else instances.FULL
        ids = instances.load_subset(subset).ids
        rows = arm_rows(a.src, arm, pattern, agent, subset)
        t = score.seed_table(rows, arm, ids, agent=agent)
        status = f"{arm:28s} {subset:12s} rows={len(rows):4d} complete={t.complete} open={t.open} union={t.union}"
        if not t.complete:
            print(f"SKIP {status}")
            continue
        done = [s for s, v in sorted(t.per_seed.items()) if v[2] == 0]
        rows = [d for d in rows if int(d.get("sample", 0)) in done]      # complete seeds only
        (a.out / f"{arm}.jsonl").write_text("".join(json.dumps(d) + "\n" for d in rows))
        status += f" -> kept seeds {done}"
        print(f"OK   {status}")


if __name__ == "__main__":
    main()
