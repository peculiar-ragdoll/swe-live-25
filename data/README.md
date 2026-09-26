# The canonical 25

`canonical_25.json` holds the 25 SWE-bench-Live task instances every model in `baselines/` was
scored on. It is frozen: the file's sha256 is pinned in `swe25/instances.py` and checked by the
test suite, so a result produced with this repo always refers to exactly these tasks.

## Provenance

- Source dataset: [`SWE-bench-Live/MultiLang`](https://huggingface.co/datasets/SWE-bench-Live/MultiLang)
  on Hugging Face (MIT license), parquet revision of 2026-05-16.
- Instances were created on GitHub between 2026-02-13 and 2026-04-20.
- Each record keeps only what the harness reads: the problem statement, repo and base commit, the
  per-instance Docker image (`starryzhang/sweb.eval.x86_64.*` on Docker Hub), the hidden
  `test_patch`, the gold `patch` (used only by `swe25 gold-check`), the test and print commands, the
  instance's own `log_parser`, and the `FAIL_TO_PASS` / `PASS_TO_PASS` test lists.
- `tools/build_instances.py` regenerates the file from the original benchmark workspace.

## How the 25 were chosen

1. A hand-curated base of 21 JS/TS/Go instances, each **gold-clean**: applying the dataset's own
   reference patch makes every FAIL_TO_PASS test pass and keeps every PASS_TO_PASS test green
   under this harness's grader. Instances whose grader could not validate gold were never used.
2. `gohugoio__hugo-14741` was dropped: its FAIL_TO_PASS list has 2,774 tests and every model
   failed the build.
3. Four newer problems were added after gold validation (cc-connect, qwen-code,
   opentelemetry-go, karmada), plus one Java instance (floci).
4. The list was then frozen and has not changed since. Both easy and currently-unsolved tasks
   are kept on purpose, so the slice keeps headroom for stronger models.

One grading adjustment applies: eight `chimurai__http-proxy-middleware-1163` tests call
`httpbin.org` over the network and cannot pass in the offline grading sandbox, so they are
removed from that instance's FAIL_TO_PASS list (`swe25/grade.py`, `F2P_EXCLUDE`).

## Subsets

`subsets/*.json` are frozen, named subsets of the 25 (`swe25 run --subset <name>`). `winnable17` is
the 17 tasks solved by at least one model that solves 10 or fewer of the 25; it leaves out the 8 that
no weaker model has solved (NemoClaw, cc-connect, youtube, kube-vip, kops, lima, svelte, doctoc).

## The instances

| instance | language | created | FAIL_TO_PASS tests |
|---|---|---|---|
| `NVIDIA__NemoClaw-330` | JavaScript | 2026-03-18 | 3 |
| `QwenLM__qwen-code-3310` | TypeScript | 2026-04-16 | 4 |
| `RooCodeInc__Roo-Code-12135` | TypeScript | 2026-04-16 | 27 |
| `amir20__dozzle-4612` | Go | 2026-04-11 | 4 |
| `chenhg5__cc-connect-567` | Go | 2026-04-11 | 1 |
| `chimurai__http-proxy-middleware-1163` | TypeScript | 2026-02-13 | 180 |
| `code-charity__youtube-3708` | JavaScript | 2026-03-16 | 44 |
| `floci-io__floci-153` | Java | 2026-04-01 | 5 |
| `karmada-io__karmada-7365` | Go | 2026-04-04 | 1 |
| `kepano__defuddle-243` | TypeScript | 2026-04-12 | 1 |
| `kube-vip__kube-vip-1505` | Go | 2026-04-06 | 16 |
| `kubernetes-sigs__controller-runtime-3494` | Go | 2026-04-05 | 1 |
| `kubernetes__kops-18146` | Go | 2026-04-02 | 1 |
| `lima-vm__lima-4803` | Go | 2026-04-06 | 3 |
| `mikro-orm__mikro-orm-7464` | TypeScript | 2026-04-01 | 1 |
| `mnfst__manifest-1635` | TypeScript | 2026-04-20 | 2 |
| `mui__mui-x-22062` | TypeScript | 2026-04-13 | 4 |
| `nodejs__undici-5000` | JavaScript | 2026-04-08 | 1115 |
| `open-telemetry__opentelemetry-go-8133` | Go | 2026-04-03 | 1 |
| `openai__codex-plugin-cc-83` | JavaScript | 2026-04-01 | 2 |
| `reactjs__react-rails-1418` | JavaScript | 2026-04-13 | 3 |
| `sqlc-dev__sqlc-4383` | Go | 2026-04-17 | 12 |
| `sveltejs__svelte-18039` | JavaScript | 2026-03-31 | 4 |
| `thlorenz__doctoc-328` | JavaScript | 2026-03-13 | 2 |
| `wxt-dev__wxt-2267` | TypeScript | 2026-04-14 | 2 |
