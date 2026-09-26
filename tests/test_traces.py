import gzip
import json

import pytest

from swe25 import traces as T

ARM, IID = "arm-x", "org__repo-1"


def ev(t, **k):
    return json.dumps({"type": t, **k}) + "\n"


def make_cell(root, arm=ARM, iid=IID, seed=0, patch=None, env_line=None):
    d = root / f"{iid}__{arm}__s{seed}"
    (d / "transcripts").mkdir(parents=True)
    tool_out = "ok" if env_line is None else env_line
    (d / "transcripts" / "000_fresh.jsonl").write_text(
        ev("message_update", message={"content": "partial " * 50})
        + ev("message_end", message={"role": "assistant", "usage": {"output": 10},
                                     "responseModel": "/Volumes/Priv/ai/models/local/Model-Q4.gguf"})
        + ev("tool_execution_end", result={"content": [{"type": "text", "text": tool_out}]}))
    (d / "transcripts" / "001_resume.jsonl").write_text(
        ev("message_update", message={"content": "x"})
        + ev("message_end", message={"role": "assistant", "usage": {"output": 5}}))
    (d / "model.patch").write_text(patch if patch is not None else
                                   "diff --git a/src/a.go b/src/a.go\n+fix\n"
                                   "diff --git a/node_modules/x/i.js b/node_modules/x/i.js\n+junk\n")
    (d / "_test_stdout.log").write_text("PASS t1\n")
    (d / "_parser_input.log").write_text('{"t1":"pass"}')
    return d


ROWS = [{"model_id": ARM, "instance_id": IID, "sample": 0, "ts": 1, "turns": 1, "resolved": False,
         "timed_out": True, "agent": "pi"},
        {"model_id": ARM, "instance_id": IID, "sample": 0, "ts": 2, "turns": 2, "resolved": True,
         "timed_out": False, "agent": "pi"}]


def export(tmp_path, rows=ROWS, **kw):
    work = tmp_path / "work"
    out = tmp_path / "out"
    return T.export({ARM: rows}, [work], out, **kw), out


def read(p):
    return gzip.decompress(p.read_bytes()).decode() if p.suffix == ".gz" else p.read_text()


def test_streaming_duplicates_dropped_other_events_kept(tmp_path):
    make_cell(tmp_path / "work")
    _, out = export(tmp_path)
    cell = out / ARM / f"{IID}__s0"
    t0 = read(cell / "transcripts" / "000_fresh.jsonl.gz")
    assert "message_update" not in t0 and "message_end" in t0 and "tool_execution_end" in t0
    assert (cell / "transcripts" / "001_resume.jsonl.gz").exists()


def test_response_model_path_reduced_to_file_name(tmp_path):
    make_cell(tmp_path / "work")
    _, out = export(tmp_path)
    t0 = read(out / ARM / f"{IID}__s0" / "transcripts" / "000_fresh.jsonl.gz")
    assert '"responseModel": "Model-Q4.gguf"' in t0 and "/Volumes/" not in t0


def test_env_dump_secrets_redacted(tmp_path):
    make_cell(tmp_path / "work", env_line="=== env ===\nPWD=/testbed\nOMLX_API_KEY=test\nGH_TOKEN=abc123\nHOME=/w\n")
    _, out = export(tmp_path)
    t0 = read(out / ARM / f"{IID}__s0" / "transcripts" / "000_fresh.jsonl.gz")
    assert "OMLX_API_KEY=<redacted>" in t0 and "GH_TOKEN=<redacted>" in t0 and "HOME=/w" in t0
    assert "=test" not in t0 and "abc123" not in t0


def test_scrub_prefix_replaced_everywhere(tmp_path):
    make_cell(tmp_path / "work", patch="diff --git a/x b/x\n+path /Volumes/Priv/ai/thing\n")
    _, out = export(tmp_path, scrub_prefixes=["/Volumes/Priv"])
    assert "<local>/ai/thing" in read(out / ARM / f"{IID}__s0" / "model.patch.gz")


def test_vendored_dirs_stripped_and_recorded(tmp_path):
    make_cell(tmp_path / "work")
    _, out = export(tmp_path)
    cell = out / ARM / f"{IID}__s0"
    p = read(cell / "model.patch.gz")
    assert "src/a.go" in p and "node_modules" not in p
    m = json.loads((cell / "manifest.json").read_text())
    assert m["patch"]["stripped_vendor_files"] == 1 and m["patch"]["stripped_dirs"] == ["node_modules"]


def test_manifest_links_rows_and_checks_turns(tmp_path):
    make_cell(tmp_path / "work")
    _, out = export(tmp_path)
    m = json.loads((out / ARM / f"{IID}__s0" / "manifest.json").read_text())
    assert m["arm"] == ARM and m["seed"] == 0 and m["verdict"] == "solved" and len(m["rows"]) == 2
    assert m["trace_turns"] == 2 and m["turns_match"] is True


def test_forbidden_string_aborts_and_writes_nothing(tmp_path):
    make_cell(tmp_path / "work", env_line="hello from jdoe-laptop")
    with pytest.raises(T.LeakFound, match="jdoe-laptop"):
        export(tmp_path, forbid=["jdoe-laptop"])
    assert not (tmp_path / "out").exists()


def test_short_forbidden_strings_match_whole_words_only(tmp_path):
    make_cell(tmp_path / "work", env_line="blob xxJdoeq9 and /Users/jdoe/x")
    with pytest.raises(T.LeakFound, match="jdoe"):
        export(tmp_path, forbid=["jdoe"])
    make_cell(tmp_path / "work2", env_line="blob xxJdoeq9 only")
    T.export({ARM: ROWS}, [tmp_path / "work2"], tmp_path / "out2", forbid=["jdoe"])


def test_real_token_shapes_caught_dummy_ones_not(tmp_path):
    real = "sk-ant-oat01-" + "A1b2C3d4" * 10
    assert T.token_like(f"key: {real}") and not T.token_like("apiKey: 'sk-ant-test'")
    assert T.token_like("hf_" + "a" * 34)


def test_forbid_from_json_takes_secret_fields_only(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"auth": {"secret_key": "s3cr3t-value-123"}, "model_dir": "Dirk"}))
    assert T.forbid_from(p) == ["s3cr3t-value-123"]
    q = tmp_path / "token"
    q.write_text("tok-abcdefgh\n")
    assert T.forbid_from(q) == ["tok-abcdefgh"]


def test_missing_cells_listed_in_index(tmp_path):
    (tmp_path / "work").mkdir()
    summary, out = export(tmp_path)
    idx = json.loads((out / "index.json").read_text())
    assert idx["missing"] == [{"arm": ARM, "instance_id": IID, "seed": 0}] and summary["exported"] == 0


def test_claude_cell_exports_stream(tmp_path):
    d = tmp_path / "work" / f"{IID}__{ARM}__s0"
    d.mkdir(parents=True)
    (d / "claude_out.jsonl").write_text(ev("assistant", message={"usage": {"output_tokens": 3}}))
    (d / "model.patch").write_text("")
    rows = [{**ROWS[1], "agent": "claude", "turns": 1}]
    _, out = export(tmp_path, rows=rows)
    cell = out / ARM / f"{IID}__s0"
    assert "assistant" in read(cell / "claude_out.jsonl.gz")
    assert json.loads((cell / "manifest.json").read_text())["turns_match"] is True


def test_finds_cells_in_this_repos_work_layout(tmp_path):
    flat = make_cell(tmp_path / "tmp")
    nested = tmp_path / "work" / ARM / f"{IID}__s0"
    nested.parent.mkdir(parents=True)
    flat.rename(nested)
    summary, _ = export(tmp_path)
    assert summary["exported"] == 1


def test_forbid_from_skips_values_too_short_to_gate(tmp_path, capsys):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"auth": {"api_key": "test", "secret_key": "long-enough-secret"}}))
    assert T.forbid_from(p) == ["long-enough-secret"]
    assert "shorter than 8" in capsys.readouterr().err


def test_documented_example_credentials_are_not_secrets():
    assert not T.token_like('Credential=AKIAIOSFODNN7EXAMPLE/20130524')
    assert T.token_like("key " + "AKIA" + "Z7XQ3PLMN4RT2WVB" + " here")


def test_survey_collects_every_hit_and_writes_nothing(tmp_path):
    make_cell(tmp_path / "work", env_line="first jdoe-laptop then " + "hf_" + "b" * 34)
    hits = T.export({ARM: ROWS}, [tmp_path / "work"], tmp_path / "out", forbid=["jdoe-laptop"], survey=True)
    assert len(hits["hits"]) == 2 and not (tmp_path / "out").exists()
    assert any("jdoe-laptop" in h for h in hits["hits"]) and any("token-shaped" in h for h in hits["hits"])
