"""Nothing in the repo may point at a maintainer's machine or private infrastructure.

The strings to guard against are personal, so they are not listed here: put one per line in a
gitignored `.hygiene-forbid` at the repo root (or in $SWE25_HYGIENE_FORBID, comma-separated).
Token-shaped secrets are always checked.
"""
import os
import subprocess
from pathlib import Path

from swe25.traces import token_like

ROOT = Path(__file__).resolve().parents[1]


def forbidden_strings(root: Path = ROOT, env: dict | None = None) -> list[str]:
    env = os.environ if env is None else env
    out = [s.strip() for s in env.get("SWE25_HYGIENE_FORBID", "").split(",") if s.strip()]
    f = root / ".hygiene-forbid"
    if f.exists():
        out += [ln.strip() for ln in f.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    return out


def hits(files: dict[str, str], forbid: list[str]) -> list[str]:
    found = [f"{name}: {s}" for name, text in files.items() for s in forbid if s in text]
    found += [f"{name}: token-shaped secret" for name, text in files.items() if token_like(text)]
    return found


def test_forbidden_strings_from_file_and_env(tmp_path):
    (tmp_path / ".hygiene-forbid").write_text("# comment\n/home/jdoe\n\njdoe-laptop\n")
    assert forbidden_strings(tmp_path, {"SWE25_HYGIENE_FORBID": "a-b, c"}) == ["a-b", "c", "/home/jdoe", "jdoe-laptop"]


def test_hits_flags_forbidden_strings_and_tokens():
    files = {"a.md": "see /home/jdoe/x", "b.py": "k = 'hf_" + "c" * 34 + "'", "c.txt": "clean"}
    assert hits(files, ["/home/jdoe"]) == ["a.md: /home/jdoe", "b.py: token-shaped secret"]


def test_no_private_strings_in_tracked_files():
    names = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    files = {n: (ROOT / n).read_text(errors="ignore") for n in names if (ROOT / n).is_file()}
    assert not hits(files, forbidden_strings()), hits(files, forbidden_strings())
