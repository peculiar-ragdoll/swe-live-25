"""Build a publishable bundle of agent traces for scored cells: one folder per (arm, instance, seed).

Per cell: the agent transcripts without Pi's streaming duplicates (`message_update` events re-send
the growing message on every token, ~99.7% of the bytes; the final `message_end` and every tool
event are kept), the graded patch minus vendored dependency folders, the test logs, and a
manifest linking the folder to its result rows.

Scrubbing: the `responseModel` field (llama.cpp reports the model's local file path) is cut to the
file name, `NAME=value` pairs whose name looks secret (…API_KEY, …TOKEN, …SECRET, …PASSWORD) are
redacted, and caller-named path prefixes become `<local>`. Then everything is scanned before it is
kept; one surviving forbidden string or token-shaped secret aborts the export and removes the
partial output, so a bundle either exists clean or not at all.
"""
from __future__ import annotations

import gzip
import json
import re
import shutil
import time
from pathlib import Path

from swe25 import __version__, score
from swe25.agent_claude import parse_stream
from swe25.agent_pi import parse_transcript

MIN_SECRET_LEN = 8


class LeakFound(RuntimeError):
    pass


VENDOR_DIRS = ("node_modules", ".pnpm-store", "bower_components", "vendor/bundle", ".yarn/cache")
_VENDOR_RX = re.compile(r"^diff --git a/(?:\S*/)?(" + "|".join(re.escape(v) for v in VENDOR_DIRS) + r")/")
_RESPONSE_MODEL = re.compile(r'("responseModel"\s*:\s*")([^"]*)(")')
# Starts at a word boundary or right after a JSON-escaped newline/tab (`\nOMLX_API_KEY=...` inside a string).
_SECRET_ENV = re.compile(r"(?:(?<=\\n)|(?<=\\t)|(?<![A-Za-z0-9_]))"
                         r"([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|_KEY))=(?!<redacted>)([^\s\"'\\]+)")
_TOKEN_SHAPES = [re.compile(p) for p in (
    r"sk-ant-(?:api|oat|admin)\d{2}-[A-Za-z0-9_\-]{40,}",   # Anthropic API / OAuth keys
    r"\bhf_[A-Za-z0-9]{34,}",                               # Hugging Face
    r"\bgh[pousr]_[A-Za-z0-9]{36,}",                        # GitHub
    r"\bAKIA[0-9A-Z]{16}\b",                                # AWS access key id
    r"\bsk-(?:proj-)?[A-Za-z0-9]{40,}",                     # OpenAI-style
)]


# Credentials published in vendor documentation and copied into countless test suites.
_DOC_EXAMPLES = re.compile(r"AKIA[0-9A-Z]{9}EXAMPLE|wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")


def token_like(text: str) -> bool:
    return any(rx.search(_DOC_EXAMPLES.sub("", text)) for rx in _TOKEN_SHAPES)


def forbid_from(path: Path) -> list[str]:
    """Secret values to forbid, read from a file: string fields named like secrets in a JSON file,
    otherwise the whole stripped file content."""
    text = Path(path).read_text().strip()
    try:
        data = json.loads(text)
    except ValueError:
        return [text] if text else []
    out: list[str] = []

    def walk(x, key=""):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, str(k))
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, str) and x and re.search(r"key|token|secret|password", key, re.I):
            out.append(x)

    walk(data)
    short = [v for v in out if len(v) < MIN_SECRET_LEN]
    if short:
        import sys
        print(f"warning: {len(short)} secret value(s) in {path} are shorter than {MIN_SECRET_LEN} characters and "
              f"cannot be gated without matching ordinary words; only KEY=value redaction covers them",
              file=sys.stderr)
    return [v for v in out if len(v) >= MIN_SECRET_LEN]


def scrub(text: str, prefixes: list[str]) -> str:
    text = _RESPONSE_MODEL.sub(lambda m: m.group(1) + m.group(2).replace("\\", "/").rsplit("/", 1)[-1] + m.group(3),
                               text)
    text = _SECRET_ENV.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    for p in prefixes:
        text = text.replace(p, "<local>")
    return text


def strip_vendor(patch: str) -> tuple[str, int, list[str]]:
    parts = re.split(r"(?=^diff --git )", patch, flags=re.M)
    kept, dirs, n = [], set(), 0
    for p in parts:
        m = _VENDOR_RX.match(p)
        if m:
            n += 1
            dirs.add(m.group(1))
        else:
            kept.append(p)
    return "".join(kept), n, sorted(dirs)


def _drop_streaming(lines) -> str:
    """Keep every event except Pi's `message_update` streaming deltas. Takes any line iterable, so a
    multi-hundred-MB transcript is streamed from disk rather than loaded whole."""
    out = []
    for line in lines:
        head = line[:48].replace(" ", "")
        if head.startswith('{"type":"message_update"'):
            continue
        out.append(line)
    return "".join(out)


class _Gate:
    def __init__(self, forbid: list[str], secrets: list[tuple[str, str]], prefixes: list[str],
                 survey: bool = False):
        self.survey, self.hits = survey, []
        self.checks: list[tuple[re.Pattern | str, str]] = []
        for s in forbid:
            self.checks.append((self._rx(s), s))
        for value, label in secrets:
            self.checks.append((self._rx(value), label))
        for p in prefixes:
            self.checks.append((p, "a scrubbed path prefix"))

    @staticmethod
    def _rx(s: str):
        if len(s) >= 16:
            return s                                    # long secret: exact substring
        return re.compile(r"(?<![A-Za-z0-9])" + re.escape(s) + r"(?![A-Za-z0-9])", re.I)

    def check(self, text: str, where: str) -> None:
        found = [f"{label} survives scrubbing in {where}" for pat, label in self.checks
                 if ((pat in text) if isinstance(pat, str) else pat.search(text))]
        if token_like(text):
            found.append(f"a token-shaped secret survives scrubbing in {where}")
        if found and not self.survey:
            raise LeakFound(found[0])
        self.hits += found


def _find_cell(work_dirs: list[Path], arm: str, iid: str, seed: int) -> Path | None:
    for w in work_dirs:
        for d in (Path(w) / arm / f"{iid}__s{seed}",          # this repo's layout
                  Path(w) / f"{iid}__{arm}__s{seed}"):       # the original harness's flat layout
            if d.is_dir():
                return d
    return None


def export(rows_by_arm: dict[str, list[dict]], work_dirs: list[Path], out: Path, *, scrub_prefixes=(),
           forbid=(), forbid_secrets=(), include_logs: bool = True, compress: bool = True,
           survey: bool = False) -> dict:
    """Write the bundle to `out`, or with survey=True write nothing and return every leak-scan hit."""
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"{out} already exists; remove it or choose another --out")
    prefixes = [p for p in scrub_prefixes if p]
    gate = _Gate(list(forbid), list(forbid_secrets), prefixes, survey)
    tmp = out.with_name(out.name + f".partial-{int(time.time())}")
    index = {"generated": time.strftime("%Y-%m-%d"), "harness_version": __version__, "cells": [], "missing": []}
    try:
        for arm, rows in sorted(rows_by_arm.items()):
            for (_, iid, seed), crows in sorted(score.cell_rows(rows).items()):
                src = _find_cell(work_dirs, arm, iid, seed)
                if src is None:
                    index["missing"].append({"arm": arm, "instance_id": iid, "seed": seed})
                    continue
                dst = tmp / arm / f"{iid}__s{seed}"
                agent = crows[-1].get("agent", "pi")
                index["cells"].append(_export_cell(src, dst, arm, iid, seed, agent, crows, gate, prefixes,
                                                   include_logs, compress))
        gate.check(json.dumps(index), "index.json")
        if survey:
            shutil.rmtree(tmp, ignore_errors=True)
            return {"exported": len(index["cells"]), "missing": len(index["missing"]), "hits": gate.hits}
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / "index.json").write_text(json.dumps(index, indent=1) + "\n")
        (tmp / "README.md").write_text(_README)
        tmp.rename(out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {"exported": len(index["cells"]), "missing": len(index["missing"])}


def _write(dst: Path, name: str, text: str, gate: _Gate, where: str, compress: bool) -> str:
    gate.check(text, where)
    dst.mkdir(parents=True, exist_ok=True)
    if compress:
        name += ".gz"
        (dst / name).write_bytes(gzip.compress(text.encode(), 6))
    else:
        (dst / name).write_text(text)
    return name


def _export_cell(src, dst, arm, iid, seed, agent, crows, gate, prefixes, include_logs, compress) -> dict:
    where = f"{arm}/{iid}__s{seed}"
    files, trace_turns = [], None
    if agent == "claude":
        p = src / "claude_out.jsonl"
        text = p.read_text(errors="replace") if p.exists() else ""
        trace_turns = parse_stream(text).get("turns")
        files.append(_write(dst, "claude_out.jsonl", scrub(text, prefixes), gate, where, compress))
    else:
        combined = ""
        for p in sorted((src / "transcripts").glob("*.jsonl")) if (src / "transcripts").is_dir() else []:
            with p.open(errors="replace") as fh:
                text = _drop_streaming(fh)
            combined += text
            files.append("transcripts/" + _write(dst / "transcripts", p.name, scrub(text, prefixes), gate,
                                                 f"{where}/{p.name}", compress))
        trace_turns = parse_transcript(combined).get("turns")
    patch_info = None
    mp = src / "model.patch"
    if mp.exists():
        patch, n, dirs = strip_vendor(mp.read_text(errors="replace"))
        files.append(_write(dst, "model.patch", scrub(patch, prefixes), gate, f"{where}/model.patch", compress))
        patch_info = {"stripped_vendor_files": n, "stripped_dirs": dirs}
    if include_logs:
        for srcname, name in (("_test_stdout.log", "test_stdout.log"), ("_parser_input.log", "parser_input.log")):
            p = src / srcname
            if p.exists():
                files.append(_write(dst, name, scrub(p.read_text(errors="replace"), prefixes), gate,
                                    f"{where}/{name}", compress))
    last = crows[-1]
    manifest = {"arm": arm, "instance_id": iid, "seed": seed, "agent": agent,
                "verdict": score.cell_verdict(crows, agent), "rows": crows,
                "trace_turns": trace_turns, "turns_match": trace_turns == last.get("turns"),
                "patch": patch_info, "files": files}
    gate.check(json.dumps(manifest), f"{where}/manifest.json")
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return {"arm": arm, "instance_id": iid, "seed": seed, "verdict": manifest["verdict"],
            "turns_match": manifest["turns_match"], "path": f"{arm}/{iid}__s{seed}"}


_README = """# Agent traces

One folder per (arm, instance, seed) behind the swe-live-25 baseline table: `<arm>/<instance>__s<seed>/`.

| file | contents |
|---|---|
| `manifest.json` | the cell's result rows, its verdict, the files below, and a check that the trace's turn count matches the recorded row (`turns_match`) |
| `transcripts/NNN_fresh.jsonl`, `NNN_resume.jsonl` | Pi agent event streams, one per pass, in order (Pi arms) |
| `claude_out.jsonl` | Claude Code `stream-json` output (Claude arms) |
| `model.patch` | the patch that was graded, minus vendored dependency folders (`node_modules` etc.; counts in the manifest) |
| `test_stdout.log`, `parser_input.log` | the grading run's test output and the log fed to the instance's parser |

Files are gzip-compressed (`.gz`). Pi's `message_update` streaming events are omitted: each one re-sends
the partial message on every token; the complete message is in the following `message_end`.

Scrubbing applied: local model file paths are reduced to the file name, secret-looking environment values
(`…_API_KEY=`, `…TOKEN=`, …) are replaced with `<redacted>`, and local path prefixes with `<local>`.
Tasks missing from `index.json`'s `cells` are listed under `missing`: their traces were not kept.
"""  # noqa: E501
