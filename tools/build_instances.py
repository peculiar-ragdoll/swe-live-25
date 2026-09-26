#!/usr/bin/env python3
"""One-off: freeze the canonical 25 SWE-bench-Live instance records into data/canonical_25.json.

    python tools/build_instances.py --src <bench-harness>/swebench --out data/canonical_25.json

Merges the source registry files in the same order and with the same `dict.update` semantics
(last occurrence wins) as the original harness, keeps only the fields the pipeline reads, and
writes them sorted by instance_id. Prints the sha256 to pin in swe25/instances.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swe25.instances import CANONICAL_IDS, OPTIONAL, REQUIRED  # noqa: E402

SOURCES = ("go_instances.json", "js_instances.json", "ts_instances.json", "pool_expanded.json",
           "multilang_instances.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True, help="directory holding the source registry JSONs")
    ap.add_argument("--out", type=Path, default=Path("data/canonical_25.json"))
    a = ap.parse_args()
    reg: dict[str, dict] = {}
    for name in SOURCES:
        p = a.src / name
        if p.exists():
            reg.update({r["instance_id"]: r for r in json.loads(p.read_text())})
    missing = [i for i in CANONICAL_IDS if i not in reg]
    if missing:
        raise SystemExit(f"missing from source: {missing}")
    keep = REQUIRED + OPTIONAL
    rows = [{k: reg[i][k] for k in keep if k in reg[i]} for i in sorted(CANONICAL_IDS)]
    a.out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} instances -> {a.out}")
    print("sha256", hashlib.sha256(a.out.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
