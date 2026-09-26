"""`swe25` command line: doctor, build-toolchain, gold-check, run, summarize, serve-llamacpp."""
from __future__ import annotations

import argparse
from pathlib import Path


def _settings(args: argparse.Namespace):
    """Settings from arms.yaml when present; defaults otherwise (gold-check needs no arms)."""
    from swe25 import config

    if args.arms_file.exists():
        return config.load(args.arms_file)[0]
    return config.Settings(work_dir=(Path.home() / "swe25-work").resolve(),
                           results_dir=Path("results").resolve(), min_free_gb=20.0)


def _gold_check(args: argparse.Namespace) -> int:
    from swe25 import docker, grade, instances

    docker.check_daemon()
    ids = instances.resolve_ids(",".join(args.ids) or "lima-vm__lima-4803")
    s = _settings(args)
    failed = 0
    for r in grade.gold_check(ids, s.work_dir, s.min_free_gb):
        ok = r["resolved"]
        failed += not ok
        print(f"{'OK  ' if ok else 'GOLD FAILED'}  {r['id']}  f2p={r['f2p']} p2p={r['p2p']} "
              f"grade={r['grade_s']}s{'  err=' + r['error'] if r['error'] else ''}", flush=True)
    return 1 if failed else 0


def _run(args: argparse.Namespace) -> int:
    from swe25 import config, docker, instances, preflight, runner

    settings, arms = config.load(args.arms_file)
    if args.arm not in arms:
        raise SystemExit(f"no arm {args.arm!r} in {args.arms_file} (have: {', '.join(arms) or 'none'})")
    arm = arms[args.arm]
    subset = instances.load_subset(args.subset)
    ids = instances.resolve_ids(args.only, subset.ids)
    if args.seeds < 1:
        raise SystemExit("--seeds must be >= 1")
    if arm.agent == "pi":
        for w in preflight.check_pi_arm(arm):
            print(f"warning: {w}")
    else:
        from swe25 import agent_claude
        agent_claude.auth_var()
    docker.check_daemon()
    docker.ensure_toolchain()
    print(f"[run] arm={arm.name} agent={arm.agent} model={arm.model} subset={subset.name} instances={len(ids)} "
          f"seeds={args.seeds} "
          f"sampling={arm.sampling} -> {settings.results_dir / (arm.name + '.jsonl')}", flush=True)
    try:
        summary = runner.Runner(settings, arm, ids, args.seeds, subset=subset.name).run()
    except KeyboardInterrupt:
        print("\ninterrupted; re-run the same command to resume", flush=True)
        return 130
    except runner.RunAborted as e:
        print(f"ABORTED: {e}", flush=True)
        return 2
    print(f"[done] {summary.rows_written} rows written; {summary.settled} cells settled, "
          f"{summary.open} open. Score with: swe25 summarize --arms {arm.name}", flush=True)
    return 0 if summary.open == 0 else 3


def _summarize(args: argparse.Namespace) -> int:
    from swe25 import summarize

    results_dir = args.results_dir or _settings(args).results_dir
    only = [a.strip() for a in args.arms.split(",") if a.strip()]
    rows, meta = summarize.combined(results_dir, not args.no_baselines, only)
    if not rows:
        print(f"no results in {results_dir}" + ("" if args.no_baselines else " and no baselines"))
        return 1
    ids = summarize.all_ids()
    tbl = summarize.table(rows, meta, ids, compare=args.subset)
    if args.subset:
        print(f"scored on the {args.subset} subset only (arms that did not run all of it are left out)\n")
    print(summarize.render_markdown(tbl, len(ids)) if args.markdown else summarize.render_text(tbl, len(ids)), end="")
    if not args.markdown:
        print("\nmean = solved per complete seed (every cell settled); union = solved in any seed; * = your arms")
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from swe25 import config, doctor

    if args.arms_file.exists():
        settings, arms = config.load(args.arms_file)
    else:
        settings, arms = _settings(args), {}
    return doctor.run(settings, arms)


def _serve_llamacpp(args: argparse.Namespace) -> int:
    from swe25 import config, llamacpp

    _, arms = config.load(args.arms_file)
    if args.arm not in arms:
        raise SystemExit(f"no arm {args.arm!r} in {args.arms_file}")
    llamacpp.serve(arms[args.arm], str(args.gguf) if args.gguf else None, args.bin)
    return 0


def _build_toolchain(args: argparse.Namespace) -> int:
    from swe25 import docker

    docker.check_daemon()
    print(f"building {docker.TOOLCHAIN_TAG} ..." if args.rebuild or not docker.image_exists(docker.TOOLCHAIN_TAG)
          else f"{docker.TOOLCHAIN_TAG} already present (use --rebuild to force)")
    print(docker.ensure_toolchain(rebuild=args.rebuild))
    return 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="swe25", description=__doc__)
    ap.add_argument("--arms-file", type=Path, default=Path("arms.yaml"),
                    help="arm definitions (default: ./arms.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check Docker, Rosetta, disk, RAM and every arm's endpoint")
    b = sub.add_parser("build-toolchain", help="build the pinned Pi toolchain image")
    b.add_argument("--rebuild", action="store_true")
    g = sub.add_parser("gold-check", help="grade the dataset's gold patch (proves Docker + grading work)")
    g.add_argument("ids", nargs="*", help="instance ids (default: lima-vm__lima-4803)")
    r = sub.add_parser("run", help="run an arm on the 25 instances until every cell settles")
    r.add_argument("--arm", required=True)
    r.add_argument("--seeds", type=int, default=3)
    r.add_argument("--subset", default="canonical25",
                   help="task set this arm is scored on: canonical25 (default), a built-in such as winnable17, "
                        "subsets/<name>.json, or a path")
    r.add_argument("--only", default="", help="run just these instance ids now (must be in the subset)")
    s = sub.add_parser("summarize", help="score your arms next to the shipped baselines")
    s.add_argument("--arms", default="", help="comma-separated arm names (default: all)")
    s.add_argument("--no-baselines", action="store_true")
    s.add_argument("--markdown", action="store_true")
    s.add_argument("--subset", default=None,
                   help="compare every arm whose tasks include this subset, scored on it alone (e.g. winnable17)")
    s.add_argument("--results-dir", type=Path, default=None)
    v = sub.add_parser("serve-llamacpp", help="start llama-server with an arm's context + sampling")
    v.add_argument("--arm", required=True)
    v.add_argument("--gguf", type=Path, default=None)
    v.add_argument("--bin", default=None)
    return ap


def main(argv: list[str] | None = None) -> int:
    from swe25.config import ConfigError
    from swe25.docker import DockerError
    from swe25.preflight import PreflightError

    args = _parser().parse_args(argv)
    try:
        return _dispatch(args)
    except (ConfigError, DockerError, PreflightError, ValueError) as e:
        print(f"error: {e}")
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    handlers = {"build-toolchain": _build_toolchain, "gold-check": _gold_check, "run": _run, "summarize": _summarize,
                "doctor": _doctor, "serve-llamacpp": _serve_llamacpp}
    return handlers[args.cmd](args)
