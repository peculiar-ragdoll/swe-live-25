# swe-live-25

Run a **25-instance SWE-bench-Live slice** against your own models on a Mac, and see
where it lands next to the models we have already benchmarked.

A coding agent ([Pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent) 0.80.3) works
inside each task's own Docker image, talking to your model through any OpenAI-compatible server
(llama.cpp, oMLX, LM Studio, Ollama …). A task counts as solved when the repository's own hidden
tests flip: every FAIL_TO_PASS test passes and every PASS_TO_PASS test still passes. There is no
LLM judge. Claude models can be run through Claude Code as a frontier yardstick.

The harness is extracted from the one that produced the baselines below and behaves identically,
so your number is directly comparable.

## Baselines

Solved out of 25, averaged over complete seeds (every task settled). *Union* counts tasks solved
in at least one seed. *Time per solve* is all agent time on complete seeds divided by solves; *time
per attempt* is one task's agent time in one seed (fresh pass plus resumes). Tokens are generated
tokens per task, all passes; Claude Code does not report them reliably, so they are omitted there. Details per model are in [`baselines/`](baselines/README.md).

<!-- baseline-table -->
| arm | model | agent | tasks | mean solved | range | complete seeds | union | open cells |
|---|---|---|---|---|---|---|---|---|
| `qwen3.8-27b-stock-medium` | Qwen3.8-27B stock, medium effort (MLX 6-bit) | pi | 25 | 16.00 / 25 | 16 | 1 | 16 | 0 |
| `dirk-qwen3.8-27b` | Dirk-Qwen3.8-27B (MLX 6-bit) | pi | 25 | 15.00 / 25 | 15 | 1 | 15 | 0 |
| `dirk-q4` | Dirk-Qwen3.8-27B (UD-Q4_K_XL) | pi | 25 | 14.00 / 25 | 13–15 | 3 | 18 | 0 |
| `opus-5-medium` | Claude Opus 5, medium effort | claude | 25 | 14.00 / 25 | 14 | 1 | 14 | 0 |
| `cybertiel` | CyberTiel-Coder-35B-A3B (Q4_K_M) | pi | 25 | 13.67 / 25 | 13–15 | 3 | 18 | 0 |
| `swift-q4-vendor-medium` | Swift-Qwen3.8-27B (vendor Q4_K_M, stock template, medium) | pi | 25 | 13.00 / 25 | 13 | 1 | 13 | 0 |
| `opus-4.6-medium` | Claude Opus 4.6, medium effort | claude | 25 | 12.00 / 25 | 12 | 1 | 12 | 0 |
| `tiel` | Tiel-Coder-35B-A3B (Q4_K_M) | pi | 25 | 12.00 / 25 | 12 | 1 | 12 | 0 |
| `cybertiel-fc` | CyberTiel-Coder-35B-A3B, full-corpus imatrix | pi | 25 | 11.67 / 25 | 11–12 | 3 | 17 | 0 |
| `swift-q4-sharp` | Swift-Qwen3.8-27B (vendor Q4_K_M + Sharp template) | pi | 25 | 11.00 / 25 | 11 | 1 | 11 | 0 |
| `kat-coder` | KAT-Coder-V2.5 (APEX I-Quality GGUF) | pi | 25 | 10.00 / 25 | 10 | 1 | 10 | 0 |
| `nail-qwen3.6-35b-a3b` | Nail-35B-A3B (MLX 4-bit) | pi | 25 | 9.00 / 25 | 9 | 1 | 9 | 0 |
| `spark-x25-4b-q6` | Sharp-Spark-X2.5-4B (UD-Q6_K_XL) | pi | 17 (winnable17) | 5.67 / 17 | 5–7 | 3 | 9 | 0 |
| `lynx` | Lynx (KAT-Coder-V2.5 + Sharp template) | pi | 25 | 8.00 / 25 | 8 | 1 | 8 | 0 |
| `ornith` | Ornith-1.5-35B-A3B (vendor Q4_K_M) | pi | 25 | 8.00 / 25 | 8 | 1 | 8 | 0 |
| `sonnet-5-medium` | Claude Sonnet 5, medium effort | claude | 25 | 8.00 / 25 | 8 | 1 | 8 | 0 |
| `stock-35b-a3b` | Qwen3.6-35B-A3B (Unsloth UD-Q4_K_XL) | pi | 25 | 8.00 / 25 | 8 | 1 | 8 | 0 |
| `haiku-4.5-high` | Claude Haiku 4.5, high effort | claude | 17 (winnable17) | 5.00 / 17 | 4–6 | 3 | 7 | 0 |
| `spark-x25-4b-q8-stock` | Spark-X2.5-4B (vendor Q8_0) | pi | 17 (winnable17) | 3.67 / 17 | 3–5 | 3 | 6 | 0 |

Cost per task (agent time; tokens generated per task, all passes):

| arm | time per solve | time per attempt (median · mean) | tokens, all tasks (median · mean) | tokens, solved (median · mean) |
|---|---|---|---|---|
| `qwen3.8-27b-stock-medium` | 1h 43m | 50m 14s · 1h 06m | 29k · 36k | 32k · 37k |
| `dirk-qwen3.8-27b` | 1h 28m | 20m 07s · 53m 01s | 15k · 26k | 12k · 18k |
| `dirk-q4` | 46m 30s | 18m 36s · 26m 03s | 15k · 20k | 14k · 19k |
| `opus-5-medium` | 11m 57s | 4m 17s · 6m 41s | — | — |
| `cybertiel` | 28m 48s | 8m 34s · 16m 08s | 15k · 27k | 14k · 26k |
| `swift-q4-vendor-medium` | 31m 25s | 13m 22s · 16m 20s | 10k · 12k | 9k · 10k |
| `opus-4.6-medium` | 14m 34s | 5m 42s · 7m 00s | — | — |
| `tiel` | 25m 43s | 8m 35s · 12m 20s | 15k · 23k | 15k · 24k |
| `cybertiel-fc` | 29m 28s | 8m 11s · 13m 45s | 14k · 26k | 11k · 19k |
| `swift-q4-sharp` | 47m 03s | 15m 59s · 20m 42s | 11k · 16k | 13k · 14k |
| `kat-coder` | 1h 08m | 6m 46s · 27m 29s | 11k · 22k | 9k · 16k |
| `nail-qwen3.6-35b-a3b` | 43m 31s | 7m 14s · 15m 40s | 6k · 15k | 3k · 5k |
| `spark-x25-4b-q6` | 1h 13m | 17m 14s · 24m 35s | 51k · 57k | 47k · 49k |
| `lynx` | 1h 22m | 6m 06s · 26m 21s | 7k · 18k | 4k · 6k |
| `ornith` | 1h 32m | 17m 12s · 29m 38s | 21k · 31k | 21k · 23k |
| `sonnet-5-medium` | 17m 44s | 1m 52s · 5m 40s | — | — |
| `stock-35b-a3b` | 44m 17s | 5m 28s · 14m 10s | 9k · 23k | 7k · 8k |
| `haiku-4.5-high` | 21m 16s | 4m 49s · 6m 15s | — | — |
| `spark-x25-4b-q8-stock` | 2h 25m | 20m 01s · 31m 22s | 59k · 73k | 49k · 50k |

Every arm that ran all 17 tasks of the `winnable17` subset, scored on those 17 alone (arms on the full 25 are restricted to the same tasks):

| arm | model | agent | tasks | mean solved | range | complete seeds | union | open cells |
|---|---|---|---|---|---|---|---|---|
| `dirk-qwen3.8-27b` | Dirk-Qwen3.8-27B (MLX 6-bit) | pi | 17 | 14.00 / 17 | 14 | 1 | 14 | 0 |
| `opus-5-medium` | Claude Opus 5, medium effort | claude | 17 | 14.00 / 17 | 14 | 1 | 14 | 0 |
| `qwen3.8-27b-stock-medium` | Qwen3.8-27B stock, medium effort (MLX 6-bit) | pi | 17 | 14.00 / 17 | 14 | 1 | 14 | 0 |
| `dirk-q4` | Dirk-Qwen3.8-27B (UD-Q4_K_XL) | pi | 17 | 13.33 / 17 | 13–14 | 3 | 16 | 0 |
| `cybertiel` | CyberTiel-Coder-35B-A3B (Q4_K_M) | pi | 17 | 13.00 / 17 | 11–15 | 3 | 16 | 0 |
| `swift-q4-vendor-medium` | Swift-Qwen3.8-27B (vendor Q4_K_M, stock template, medium) | pi | 17 | 13.00 / 17 | 13 | 1 | 13 | 0 |
| `opus-4.6-medium` | Claude Opus 4.6, medium effort | claude | 17 | 12.00 / 17 | 12 | 1 | 12 | 0 |
| `cybertiel-fc` | CyberTiel-Coder-35B-A3B, full-corpus imatrix | pi | 17 | 11.33 / 17 | 10–12 | 3 | 16 | 0 |
| `swift-q4-sharp` | Swift-Qwen3.8-27B (vendor Q4_K_M + Sharp template) | pi | 17 | 11.00 / 17 | 11 | 1 | 11 | 0 |
| `tiel` | Tiel-Coder-35B-A3B (Q4_K_M) | pi | 17 | 11.00 / 17 | 11 | 1 | 11 | 0 |
| `kat-coder` | KAT-Coder-V2.5 (APEX I-Quality GGUF) | pi | 17 | 10.00 / 17 | 10 | 1 | 10 | 0 |
| `nail-qwen3.6-35b-a3b` | Nail-35B-A3B (MLX 4-bit) | pi | 17 | 9.00 / 17 | 9 | 1 | 9 | 0 |
| `lynx` | Lynx (KAT-Coder-V2.5 + Sharp template) | pi | 17 | 8.00 / 17 | 8 | 1 | 8 | 0 |
| `ornith` | Ornith-1.5-35B-A3B (vendor Q4_K_M) | pi | 17 | 8.00 / 17 | 8 | 1 | 8 | 0 |
| `sonnet-5-medium` | Claude Sonnet 5, medium effort | claude | 17 | 8.00 / 17 | 8 | 1 | 8 | 0 |
| `stock-35b-a3b` | Qwen3.6-35B-A3B (Unsloth UD-Q4_K_XL) | pi | 17 | 8.00 / 17 | 8 | 1 | 8 | 0 |
| `spark-x25-4b-q6` | Sharp-Spark-X2.5-4B (UD-Q6_K_XL) | pi | 17 (winnable17) | 5.67 / 17 | 5–7 | 3 | 9 | 0 |
| `haiku-4.5-high` | Claude Haiku 4.5, high effort | claude | 17 (winnable17) | 5.00 / 17 | 4–6 | 3 | 7 | 0 |
| `spark-x25-4b-q8-stock` | Spark-X2.5-4B (vendor Q8_0) | pi | 17 (winnable17) | 3.67 / 17 | 3–5 | 3 | 6 | 0 |
<!-- /baseline-table -->

## Requirements

- Apple-Silicon Mac, macOS 14 or newer. Other hosts may work but are untested.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with **Settings → General →
  "Use Rosetta for x86_64/amd64 emulation"** turned on. The task images are amd64.
- Docker VM disk: **150 GB free** recommended. Task images are 2–12 GB each; the harness holds one
  task's images at a time and refuses to pull below a 20 GB floor.
- RAM: about 64 GB for 27B–35B models alongside the agent containers; small (~4–9B) models are fine
  on much less.
- [uv](https://docs.astral.sh/uv/) and a model server. For llama.cpp, `brew install llama.cpp`.

## Quick start

```bash
git clone <this repo> && cd swe-live-25
uv sync
cp arms.example.yaml arms.yaml            # describe your model: endpoint, context, sampling
uv run swe25 serve-llamacpp --arm my-model-q4 --gguf /path/to/model.gguf   # in its own terminal
uv run swe25 doctor                       # Docker, Rosetta, disk, RAM, endpoint, context size
uv run swe25 build-toolchain              # the pinned Pi image (once)
uv run swe25 gold-check                   # grade a reference patch: proves Docker + grading work
uv run swe25 run --arm my-model-q4 --seeds 3
uv run swe25 summarize                    # your arm next to the baselines
```

`run` is safe to interrupt (Ctrl-C) and resumes where it left off when run again. `--seeds 1`
gives a first number sooner; running again with `--seeds 3` adds seeds 1 and 2 only. `--only
id1,id2` restricts to a subset of the 25.

## Subsets for smaller models

A weak model spends most of its hours on tasks it will not solve. A **subset** runs, and scores,
an arm on part of the 25:

```bash
uv run swe25 run --arm my-small-model --subset winnable17 --seeds 3
uv run swe25 summarize --subset winnable17   # every arm that ran those 17, scored on them alone
```

`winnable17` (built in) is the 17 tasks that at least one weaker model (10 or fewer of 25) has
solved. Define your own as `subsets/<name>.json` next to your `arms.yaml`:

```json
{"name": "easy-go", "description": "why these tasks", "instances": ["lima-vm__lima-4803", "amir20__dozzle-4612"]}
```

An arm's subset is recorded in every row and fixed for that arm: its seeds are complete when its
subset's tasks are settled, and its score reads `x / 17`. Scores on different subsets are not
comparable. `summarize --subset` restricts every arm that ran all of a subset's tasks to exactly
those tasks, which is the fair comparison. `--only` is different: it runs some of the arm's tasks
now, and the rest remain open.

## What a run does

Each **cell** is one (task, seed). For every cell:

1. The task's image gets an overlay with node and Pi. The agent starts in `/testbed` (the repo at
   the task's base commit, dependencies installed) with **only the issue text** as its prompt, on
   Pi's default system prompt.
2. **First pass: 1200 s.** If the agent ends on its own, the pass is over. If the time cap cuts
   it off, its edits are kept.
3. **Resume passes: 3600 s each, up to 4 h in total.** The edits are restored and the same agent
   session continues with one extra user message, verbatim:
   > You have more time now. Continue exactly where you left off and finish making the failing
   > test(s) pass. Do not restart from scratch.
4. After every pass the patch is **graded** in a fresh container: model patch plus hidden test
   patch, the repo's own test commands, the task's own log parser.
5. A cell **settles** when it is solved, when a pass ends on its own without solving it, or when
   it reaches the 4 h ceiling. Only settled cells count. A seed is complete when all 25 are settled.

The model is never told about time limits. Besides the resume message above, the only time
signal it ever sees is per command. Pi's bash tool is patched so that a single command with no
output for 600 s, or running past 1800 s, is killed, and the model sees `Command timed out after N
seconds` (see [`docker/README.md`](docker/README.md)). Without the patch a hung test can burn a whole
pass.

Infrastructure trouble never counts against the model. A pass that dies without an exit code, or
that produced no model turn at all (server down), stays open and is retried with a fresh pass.
After three such failures in a row, a cell is left open for the next run and the run moves on. If
two cells in a row fail this way, the run stops with a message: that is an outage, not a task.

## Sampling and context

Pi sends **no sampling parameters**, so the model samples at whatever the **server** was started
with. `sampling` in `arms.yaml` is a declaration: it is recorded in every result row, and
`swe25 serve-llamacpp` starts llama-server with exactly those values. If you use another server,
configure it to match.

`context` is advertised to the agent as its window and **must equal the server's context size**.
Otherwise the agent grows its context past what the server holds and fails mid-run. `doctor` and
`run` read llama.cpp's `/props` and refuse a mismatch. Other servers can't be checked, so make
sure yourself.

The baselines used a 262,144-token context, top_p 0.95, top_k 20, min_p 0, and temperature 0.6
(Qwen3.6-family models) or 1.0 (Qwen3.8-family models).

## Claude arms

```yaml
opus-5-medium: {agent: claude, model: claude-opus-5, effort: medium}
```

Needs `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) or `ANTHROPIC_API_KEY` in the
environment. The secret is passed to Docker by name and is never written to disk or into a result.
Claude Code runs in the same task images with a fresh home directory and the same prompt and
grader. Like the Opus/Sonnet baselines, it gets **one 1800 s pass with no resume**, while local
models get up to 4 h. Keep that asymmetry in mind when comparing.

## Results

- `results/<arm>.jsonl`: one row per pass. Fields: `instance_id, model_id, sample, resolved,
  patch_nonempty, wall_agent_s, wall_grade_s, timed_out, turns, tool_calls, tool_calls_invalid,
  prefill_tokens, output_tokens, total_generated, prefill_cache_hit, f2p_pass, f2p_total, p2p_pass,
  p2p_total, error, ts, agent, pass_kind, cum_wall_s, sampling, harness_version`.
- `results/<arm>.runconfig.<ts>.json`: the arm (no secrets), versions, caps and host, per launch.
- `work_dir/<arm>/<instance>__s<seed>/`: transcripts, the model's patch and grade logs. This can
  grow to tens of GB; delete it freely once a cell is settled, because scores live in the jsonl.

## Sharing traces

`tools/export_traces.py` turns a work directory into a publishable bundle: one folder per task and
seed with the agent's transcripts, the graded patch, the test logs and a manifest tying it to the
result rows. It drops Pi's streaming duplicates (over 99% of the raw bytes), strips vendored
dependency folders from patches, reduces local model paths to file names, and redacts
`…_API_KEY=`/`…TOKEN=` values. It then refuses to write anything if one of your forbidden strings or
secrets, or anything shaped like an API token, survives:

```bash
uv run python tools/export_traces.py --source results --work ~/swe25-work --out traces \
    --scrub-prefix "$HOME" --forbid "$(whoami)" --forbid "$(scutil --get LocalHostName)" \
    --forbid-from ~/.config/my-api-token
```

Pass your own name, username, hostname and email with `--forbid`, and your key/token files with
`--forbid-from`. Review a few folders before you publish.

## Time

On the 64 GB Apple-Silicon Mac that produced the baselines, one seed of a 27B–35B local model took
roughly **5 to 13 hours of agent time plus about an hour of grading**. A Claude seed took about
4 hours. A task's grades overlap the agent passes of its other seeds, but not the next task, so
expect wall-clock somewhat above the agent time, and closer to agent plus grading with \`--seeds 1\`.

## Limitations

- The task containers run amd64 under emulation, so wall-clock times reflect this setup, not the
  model alone.
- Sampling is stochastic and unseeded. Seeds are independent repeat samples, which is why the
  table reports a mean and a range.
- Baseline arms that settled before 2026-08-31 ran without the bash-tool patch (see
  [`baselines/README.md`](baselines/README.md)).
- 25 tasks is a small slice: one task is 4 points. Compare arms over several seeds.

## The 25 tasks

Frozen in `data/canonical_25.json` (sha256-pinned). Provenance and how they were chosen:
[`data/README.md`](data/README.md). Source: [SWE-bench-Live](https://huggingface.co/datasets/SWE-bench-Live/MultiLang) (MIT).

## Development

```bash
uv run pytest               # unit tests (no Docker)
uv run pytest -m docker     # also grades a real task in Docker (~3 GB image)
uv run ruff check .
```

MIT license.
