import subprocess
import sys


def test_help_lists_subcommands():
    out = subprocess.run([sys.executable, "-m", "swe25", "--help"], capture_output=True, text=True).stdout
    for sub in ["doctor", "build-toolchain", "gold-check", "run", "summarize", "serve-llamacpp"]:
        assert sub in out


def test_run_with_missing_arms_file_is_a_clean_error(tmp_path):
    r = subprocess.run([sys.executable, "-m", "swe25", "--arms-file", str(tmp_path / "arms.yaml"), "run",
                        "--arm", "x"], capture_output=True, text=True)
    assert r.returncode == 1 and "arms.example.yaml" in r.stdout and "Traceback" not in r.stderr


def test_run_unknown_instance_is_a_clean_error(tmp_path):
    p = tmp_path / "arms.yaml"
    p.write_text("arms:\n  x:\n    agent: pi\n    model: m\n    endpoint: http://127.0.0.1:1/v1\n")
    r = subprocess.run([sys.executable, "-m", "swe25", "--arms-file", str(p), "run", "--arm", "x",
                        "--only", "nope__nope-1"], capture_output=True, text=True)
    assert r.returncode == 1 and "not in the canonical 25" in r.stdout
