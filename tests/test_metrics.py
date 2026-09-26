from swe25 import metrics as M


def R(iid, sample, wall, tok=None, ts=1, **k):
    return {"model_id": "m", "instance_id": iid, "sample": sample, "wall_agent_s": wall, "turns": 3,
            "timed_out": k.pop("timed_out", False), "output_tokens": tok, "ts": ts, **k}


def test_cell_tokens_undo_cumulative_counts():
    rows = [R("a", 0, 1200, 12864, ts=1), R("a", 0, 3600, 42890, ts=2), R("a", 0, 900, 49463, ts=3)]
    assert M.cell_tokens(rows) == 49463


def test_cell_tokens_new_chain_after_fresh_restart_adds_up():
    rows = [R("a", 0, 100, 10000, ts=1), R("a", 0, 100, 25000, ts=2), R("a", 0, 100, 4000, ts=3)]
    assert M.cell_tokens(rows) == 29000                     # counter reset -> a new chain


def test_time_per_solve_and_attempt_over_complete_seeds():
    ids = ["a", "b"]
    rows = [R("a", 0, 600, resolved=True), R("b", 0, 1200, timed_out=True), R("b", 0, 300, ts=2),
            R("a", 1, 100, resolved=True), R("b", 1, 500, resolved=True),
            R("a", 2, 50, resolved=True)]                   # seed 2 incomplete: b never ran
    m = M.arm_metrics(rows, "m", ids, agent="pi")
    assert m["sec_per_solve"] == (600 + 1500 + 100 + 500) / 3
    assert m["attempts"] == 4 and m["sec_per_attempt_median"] == (600 + 500) / 2
    assert m["sec_per_attempt_mean"] == (600 + 1500 + 100 + 500) / 4


def test_seed_without_solves_counts_for_attempts_not_per_solve():
    rows = [R("a", 0, 1000), R("a", 1, 200, resolved=True)]
    m = M.arm_metrics(rows, "m", ["a"], agent="pi")
    assert m["sec_per_solve"] == 200 and m["attempts"] == 2


def test_timing_invalid_seed_dropped_from_time_but_not_tokens():
    rows = [R("a", 0, 100, 1000, resolved=True), R("a", 1, 9999, 3000, resolved=True)]
    m = M.arm_metrics(rows, "m", ["a"], agent="pi", timing_invalid={1})
    assert m["sec_per_solve"] == 100 and m["attempts"] == 1
    assert m["tok_all_median"] == 2000 and m["tok_solved_mean"] == 2000


def test_tokens_all_and_solved():
    rows = [R("a", 0, 10, 1000, resolved=True), R("b", 0, 10, 5000), R("c", 0, 10, 3000, resolved=True)]
    m = M.arm_metrics(rows, "m", ["a", "b", "c"], agent="pi")
    assert (m["tok_all_median"], m["tok_all_mean"]) == (3000, 3000)
    assert (m["tok_solved_median"], m["tok_solved_mean"]) == (2000, 2000)


def test_claude_arms_report_no_tokens():
    m = M.arm_metrics([R("a", 0, 10, 1000, resolved=True)], "m", ["a"], agent="claude")
    assert m["tok_all_median"] is None and m["sec_per_solve"] == 10


def test_no_complete_seed_gives_none():
    m = M.arm_metrics([R("a", 0, 1200, timed_out=True)], "m", ["a"], agent="pi")
    assert m["sec_per_solve"] is None and m["sec_per_attempt_median"] is None


def test_formatting():
    assert M.fmt_duration(2790) == "46m 30s" and M.fmt_duration(59) == "0m 59s"
    assert M.fmt_duration(3725) == "1h 02m" and M.fmt_duration(None) == "—"
    assert M.fmt_tokens(15234) == "15k" and M.fmt_tokens(850) == "850" and M.fmt_tokens(1_250_000) == "1.2M"
    assert M.fmt_tokens(None) == "—"
