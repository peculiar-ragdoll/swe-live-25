from swe25 import score as S


def R(**k):
    base = {"model_id": "m", "instance_id": "a", "sample": 0, "ts": k.pop("ts", 1)}
    return {**base, **k}


def test_phantom_not_real():
    assert not S.is_real(R(resolved=True, patch_nonempty=False, turns=None, wall_agent_s=0))


def test_real_by_turns_patch_or_wall():
    assert S.is_real(R(turns=3))
    assert S.is_real(R(patch_nonempty=True))
    assert S.is_real(R(wall_agent_s=0.3))


def test_capped_flags():
    assert S.is_capped(R(timed_out=True))
    assert S.is_capped(R(error="x"))
    assert not S.is_capped(R(timed_out=False, wall_agent_s=5000))


def test_resolved_is_sticky():
    rows = [R(ts=1, resolved=True, turns=5), R(ts=2, resolved=False, turns=5)]
    assert S.cell_verdict(rows, "pi") == "solved"


def test_natural_end_is_miss():
    assert S.cell_verdict([R(turns=4, timed_out=False, wall_agent_s=300)], "pi") == "miss"


def test_no_rows_is_open():
    assert S.cell_verdict([], "pi") == "open"
    assert S.cell_verdict([R(error="x", wall_agent_s=0)], "pi") == "open"   # only noise


def test_cap_under_ceiling_is_open():
    assert S.cell_verdict([R(turns=4, timed_out=True, wall_agent_s=1200)], "pi") == "open"


def test_cap_at_ceiling_is_miss():
    rows = [R(ts=i, turns=4, timed_out=True, wall_agent_s=w)
            for i, w in enumerate([1200, 3600, 3600, 3600, 2400])]
    assert S.cum_wall(rows) == 14400
    assert S.cell_verdict(rows, "pi") == "miss"


def test_latest_row_decides_by_ts_not_list_order():
    rows = [R(ts=5, turns=4, timed_out=False, wall_agent_s=100), R(ts=1, turns=4, timed_out=True, wall_agent_s=1200)]
    assert S.cell_verdict(rows, "pi") == "miss"


def test_claude_cap_is_settled():
    assert S.cell_verdict([R(turns=4, timed_out=True, wall_agent_s=1800)], "claude") == "miss"


def test_cell_rows_groups_real_rows_chronologically():
    rows = [R(ts=2, turns=1), R(ts=1, turns=1, sample=1), R(ts=0, turns=1), R(ts=3, wall_agent_s=0, error="x")]
    g = S.cell_rows(rows)
    assert [r["ts"] for r in g[("m", "a", 0)]] == [0, 2]
    assert set(g) == {("m", "a", 0), ("m", "a", 1)}


def test_complete_seed_mean_and_union():
    ids = ["a", "b"]
    rows = [R(instance_id="a", sample=0, resolved=True, turns=1), R(instance_id="b", sample=0, turns=1),
            R(instance_id="a", sample=1, turns=1), R(instance_id="b", sample=1, resolved=True, turns=1),
            R(instance_id="a", sample=2, turns=1, timed_out=True, wall_agent_s=1200)]
    t = S.seed_table(rows, "m", ids, agent="pi")
    assert t.complete == [1, 1]
    assert t.mean == 1.0 and (t.lo, t.hi) == (1, 1)
    assert t.union == 2
    assert t.per_seed[2] == (0, 0, 2)          # seed 2: a open (cap), b never run
    assert t.open == 2


def test_no_complete_seed_mean_is_none():
    t = S.seed_table([R(turns=1, timed_out=True, wall_agent_s=1200)], "m", ["a"], agent="pi")
    assert t.complete == [] and t.mean is None


def test_claude_infra_failure_without_patch_is_open():
    assert S.cell_verdict([R(turns=2, error="claude: rc=125", wall_agent_s=40)], "claude") == "open"


def test_claude_error_with_patch_is_a_miss():
    rows = [R(turns=2, error="claude: x", patch_nonempty=True, wall_agent_s=900)]
    assert S.cell_verdict(rows, "claude") == "miss"
