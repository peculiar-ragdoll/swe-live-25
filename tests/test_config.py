from pathlib import Path

import pytest

from swe25 import config as C

EXAMPLE = Path(__file__).resolve().parents[1] / "arms.example.yaml"


def write(tmp_path, text):
    p = tmp_path / "arms.yaml"
    p.write_text(text)
    return p


def test_example_loads():
    settings, arms = C.load(EXAMPLE)
    assert arms and all(a.agent in ("pi", "claude") for a in arms.values())
    assert settings.work_dir.is_absolute()


def test_pi_arm_needs_endpoint(tmp_path):
    p = write(tmp_path, "arms:\n  x:\n    agent: pi\n    model: m\n")
    with pytest.raises(C.ConfigError, match="endpoint"):
        C.load(p)


def test_claude_defaults_effort_medium(tmp_path):
    _, arms = C.load(write(tmp_path, "arms:\n  opus:\n    agent: claude\n    model: claude-opus-5\n"))
    assert arms["opus"].effort == "medium"


def test_work_dir_tilde_expanded(tmp_path):
    s, _ = C.load(write(tmp_path, "work_dir: ~/somewhere\narms: {}\n"))
    assert s.work_dir == Path.home() / "somewhere"


def test_unknown_agent_rejected(tmp_path):
    with pytest.raises(C.ConfigError, match="agent"):
        C.load(write(tmp_path, "arms:\n  x:\n    agent: codex\n    model: m\n"))


@pytest.mark.parametrize("name", ["Bad Name", "-lead", "a/b", ""])
def test_arm_name_validated(tmp_path, name):
    with pytest.raises(C.ConfigError, match="name"):
        C.load(write(tmp_path, f'arms:\n  "{name}":\n    agent: claude\n    model: m\n'))


def test_sampling_keys_restricted(tmp_path):
    txt = ("arms:\n  x:\n    agent: pi\n    model: m\n    endpoint: http://127.0.0.1:8080/v1\n"
           "    sampling: {temperature: 1}\n")
    with pytest.raises(C.ConfigError, match="sampling"):
        C.load(write(tmp_path, txt))


def test_missing_file_is_config_error(tmp_path):
    with pytest.raises(C.ConfigError, match="arms.example.yaml"):
        C.load(tmp_path / "arms.yaml")


def test_defaults(tmp_path):
    s, arms = C.load(write(tmp_path, "arms:\n  x:\n    agent: pi\n    model: m\n    endpoint: http://h:1/v1\n"))
    a = arms["x"]
    assert a.context == 262144 and a.sampling is None and a.api_key_env is None
    assert s.min_free_gb == 20 and s.results_dir == Path("results").resolve()
