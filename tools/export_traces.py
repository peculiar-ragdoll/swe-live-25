#!/usr/bin/env python3
"""Export a scrubbed, publishable bundle of agent traces for scored cells.

    # the shipped baselines, from the original benchmark workspace
    python tools/export_traces.py --work <old>/sweb_work --work <old>/sweb_work_archive \\
        --scrub-prefix /Volumes/MyDisk --forbid my-name --forbid-from ~/.config/some-token --out traces

    # your own runs with this repo
    python tools/export_traces.py --source results --work ~/swe25-work --forbid my-name --out traces

One folder per (arm, instance, seed) with transcripts (streaming duplicates dropped), the graded
patch (vendored dependency folders stripped), test logs and a manifest. See swe25/traces.py for the
scrubbing rules. Nothing is written unless the whole bundle passes the leak scan: every --forbid
string, every secret read by --forbid-from, every --scrub-prefix, and token-shaped secrets.
Forbid your name, username, hostname and email; point --forbid-from at your API-key/token files.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swe25 import summarize, traces  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["baselines", "results"], default="baselines",
                    help="which rows to export traces for (default: the shipped baselines)")
    ap.add_argument("--results-dir", type=Path, default=Path("results"), help="for --source results")
    ap.add_argument("--arms", default="", help="comma-separated subset of arms")
    ap.add_argument("--work", type=Path, action="append", required=True,
                    help="work directory holding the cells' transcripts (repeatable; searched in order)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scrub-prefix", action="append", default=[], help="local path prefix to replace with <local>")
    ap.add_argument("--forbid", action="append", default=[], help="string that must not appear (name, host, …)")
    ap.add_argument("--forbid-from", type=Path, action="append", default=[],
                    help="file holding secrets that must not appear (JSON: secret-named fields; else the content)")
    ap.add_argument("--no-logs", action="store_true", help="skip the test logs (about half the bundle)")
    ap.add_argument("--no-compress", action="store_true", help="write plain text instead of .gz")
    ap.add_argument("--survey", action="store_true",
                    help="write nothing; scrub and scan everything and list every leak-scan hit")
    a = ap.parse_args()

    rows = summarize.load_baselines() if a.source == "baselines" else summarize.load_results(a.results_dir)
    only = {x.strip() for x in a.arms.split(",") if x.strip()}
    if only:
        rows = {k: v for k, v in rows.items() if k in only}
    if not rows:
        print("no rows to export", file=sys.stderr)
        return 1
    secrets = [(v, f"a secret from {p}") for p in a.forbid_from for v in traces.forbid_from(p)]
    try:
        s = traces.export(rows, a.work, a.out, scrub_prefixes=a.scrub_prefix, forbid=a.forbid,
                          forbid_secrets=secrets, include_logs=not a.no_logs, compress=not a.no_compress,
                          survey=a.survey)
    except traces.LeakFound as e:
        print(f"REFUSED, nothing written: {e}", file=sys.stderr)
        return 2
    if a.survey:
        for h in s["hits"]:
            print("HIT", h)
        print(f"survey: {s['exported']} cells scanned, {len(s['hits'])} hit(s); nothing written")
        return 2 if s["hits"] else 0
    print(f"exported {s['exported']} cells ({s['missing']} without traces) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
