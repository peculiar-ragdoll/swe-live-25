from swe25.results import Row, append_row, read_rows


def test_reader_skips_corrupt_line(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text('{"ts":2,"a":1}\n\n{"ts":1,"a":0}\n{"ts":3,"a"')
    assert [r["a"] for r in read_rows([p])] == [0, 1]


def test_reader_ignores_missing_file(tmp_path):
    assert read_rows([tmp_path / "nope.jsonl"]) == []


def test_append_roundtrip(tmp_path):
    p = tmp_path / "sub" / "r.jsonl"
    append_row(p, Row("i", "m", sample=1, turns=2))
    r = read_rows([p])[0]
    assert r["sample"] == 1 and r["ts"] > 0 and r["agent"] == "pi" and r["pass_kind"] == "fresh"
    assert r["harness_version"]
