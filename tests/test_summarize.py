import re
from pathlib import Path

from swe25 import summarize as SM

ROOT = Path(__file__).resolve().parents[1]


def row(iid, sample, **k):
    return {"model_id": k.pop("model", "a"), "instance_id": iid, "sample": sample, "turns": 3,
            "timed_out": False, "ts": k.pop("ts", 1), **k}


def test_table_scores_complete_seeds_only():
    ids = ["i1", "i2"]
    rows = {"a": [row("i1", 0, resolved=True), row("i2", 0),
                  row("i1", 1, resolved=True), row("i2", 1, resolved=True),
                  row("i1", 2, timed_out=True, wall_agent_s=1200)]}
    (t,) = SM.table(rows, {"a": {"agent": "pi", "label": "A"}}, ids)
    assert (t["arm"], t["seeds_complete"], t["mean"], t["lo"], t["hi"], t["union"], t["open"]) == \
        ("a", 2, 1.5, 1, 2, 2, 2)
    assert t["per_seed"] == {0: (1, 2, 0), 1: (2, 2, 0), 2: (0, 0, 2)}


def test_table_sorts_by_mean_then_name():
    ids = ["i1"]
    rows = {"b": [row("i1", 0, model="b")], "a": [row("i1", 0, model="a", resolved=True)],
            "c": [row("i1", 0, model="c", timed_out=True, wall_agent_s=1200)]}
    names = [t["arm"] for t in SM.table(rows, {}, ids)]
    assert names == ["a", "b", "c"]            # c has no complete seed: last


def test_render_markdown_has_header_and_rows():
    rows = {"a": [row("i1", 0, resolved=True)]}
    md = SM.render_markdown(SM.table(rows, {"a": {"label": "Model A", "agent": "pi"}}, ["i1"]), n_ids=1)
    assert md.splitlines()[0].startswith("| arm |") and "Model A" in md and "1.00 / 1" in md


def test_readme_table_matches_baselines():
    md = SM.readme_block()
    readme = (ROOT / "README.md").read_text()
    m = re.search(r"<!-- baseline-table -->\n(.*?)<!-- /baseline-table -->", readme, re.S)
    assert m, "README.md is missing the baseline-table markers"
    assert m.group(1).strip() == md.strip(), "run `uv run swe25 summarize --markdown` and paste into README"


def test_combined_marks_user_arms_and_keeps_colliding_baseline(tmp_path):
    (tmp_path / "tiel.jsonl").write_text(
        '{"model_id":"tiel","instance_id":"lima-vm__lima-4803","sample":0,"turns":2,"timed_out":false,"ts":5}\n')
    rows, meta = SM.combined(tmp_path, include_baselines=True, only=[])
    assert meta["tiel"]["user"] is True and "tiel (baseline)" in rows and "opus-4.6-medium" in rows
    rows2, _ = SM.combined(tmp_path, include_baselines=False, only=["tiel"])
    assert list(rows2) == ["tiel"]


def test_table_carries_cost_metrics_and_markdown_shows_them():
    rows = {"a": [row("i1", 0, resolved=True, wall_agent_s=600, output_tokens=12000)]}
    (t,) = SM.table(rows, {"a": {"agent": "pi", "label": "A"}}, ["i1"])
    assert t["sec_per_solve"] == 600 and t["tok_all_median"] == 12000
    md = SM.render_markdown([t], n_ids=1)
    assert "10m 00s" in md and "12k" in md
    assert "10m 00s" in SM.render_text([t], n_ids=1)


def test_timing_invalid_seeds_come_from_meta():
    rows = {"a": [row("i1", 0, resolved=True, wall_agent_s=100), row("i1", 1, resolved=True, wall_agent_s=900)]}
    (t,) = SM.table(rows, {"a": {"agent": "pi", "timing_invalid_seeds": [1]}}, ["i1"])
    assert t["sec_per_solve"] == 100



def _w17():
    from swe25 import instances
    return instances.load_subset("winnable17").ids


def test_subset_arm_scored_over_its_own_tasks():
    ids = _w17()
    rows = {"small": [row(i, 0, model="small", resolved=(n < 5), subset="winnable17") for n, i in enumerate(ids)]}
    (t,) = SM.table(rows, {}, SM.all_ids())
    assert t["subset"] == "winnable17" and t["n_ids"] == 17 and t["mean"] == 5 and t["open"] == 0
    assert "5.00 / 17" in SM.render_markdown([t], n_ids=25)


def test_compare_on_subset_restricts_full_arms_and_skips_narrower_ones():
    ids = _w17()
    full = [row(i, 0, model="big", resolved=True) for i in SM.all_ids()]
    small = [row(i, 0, model="small", subset="winnable17") for i in ids]
    rows = {"big": full, "small": small}
    tbl = SM.table(rows, {}, SM.all_ids(), compare="winnable17")
    assert {t["arm"]: t["mean"] for t in tbl} == {"big": 17, "small": 0}
    assert all(t["n_ids"] == 17 for t in tbl)
    # an arm run on 17 tasks cannot be scored on all 25: it is left out of that comparison
    assert [t["arm"] for t in SM.table(rows, {}, SM.all_ids(), compare="canonical25")] == ["big"]
