# Baselines

Result rows for every model we benchmarked on the canonical 25 that has at least one **complete
seed** (every instance settled: solved, or a miss that can no longer change). Only complete seeds
are included. Most arms ran all 25; the small-model probes and Haiku ran (or are scored on) the
17-task `winnable17` subset (`subset` in `arms.json` and in every row). `swe25 summarize` scores these rows next to yours with the same code.

| file | contents |
|---|---|
| `<arm>.jsonl` | one row per agent pass (fresh or resume), same schema as your `results/<arm>.jsonl`, without transcripts or patches |
| `arms.json` | per arm: model, weights, quantization, serving backend, whether the bash-tool patch was active, notes |

## How these were produced

Same harness logic as this repo (it was extracted from it): the Pi 0.80.3 agent with the problem
statement as the only prompt, a 1200 s first pass, 3600 s resume passes up to 4 h per cell, the
same grader and test exclusions. Claude arms: Claude Code, one 1800 s pass, no resume. All local
models served with a 262,144-token context. Sampling per row is in the `sampling` field.

Caveats, all visible in the data:

- **Bash-tool timeout patch.** Arms that settled before 2026-08-31 ran on stock Pi, whose bash
  tool has no default per-command timeout (`bash_patch: "no"` in `arms.json`). A hung test command
  could burn a pass's whole time budget. Verdicts are comparable; wall-clock times less so.
- **Backends differ.** The Qwen3.8-27B MLX arms and Nail ran on oMLX (MLX quantization); the rest
  on llama.cpp GGUF. Quantization and backend are part of what each row measures.
- **Timing.** Instance containers run amd64 under Rosetta on an Apple-Silicon Mac (64 GB), so
  wall-clock numbers are only comparable within this setup, and some seeds shared the box with
  other work. Treat `wall_agent_s` as indicative.
- **Row order.** Rows written before 2026-08-18 had no timestamp; their `ts` is an ordinal that
  preserves the original write order, not a wall-clock time.
- **Scoring rule.** A cell whose resume passes reached the 4 h ceiling is a settled miss. The
  original dashboard left such seeds open, so `kat-coder` and `ornith` (one ceiling cell each) show
  a complete seed here but not there. Every other arm scores identically under both.

Regenerate from the original benchmark workspace with `tools/export_baselines.py`.
