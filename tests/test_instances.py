import hashlib

from swe25 import instances as I


def test_ids_are_the_canonical_25():
    d = I.load()
    assert len(I.CANONICAL_IDS) == 25
    assert set(d) == set(I.CANONICAL_IDS)


def test_file_hash_pinned():
    assert hashlib.sha256(I.DATA_PATH.read_bytes()).hexdigest() == I.DATA_SHA256


def test_required_fields_present():
    for r in I.load().values():
        for k in I.REQUIRED:
            assert r.get(k) not in (None, ""), (r["instance_id"], k)
        assert r["docker_image"].startswith("starryzhang/sweb.eval.x86_64.")


def test_resolve_ids_subset_and_unknown():
    assert I.resolve_ids("") == list(I.CANONICAL_IDS)
    assert I.resolve_ids("lima-vm__lima-4803, thlorenz__doctoc-328") == [
        "lima-vm__lima-4803", "thlorenz__doctoc-328"]
    import pytest
    with pytest.raises(ValueError, match="not in the canonical 25"):
        I.resolve_ids("gohugoio__hugo-14741")


def test_builtin_subsets():
    full = I.load_subset("canonical25")
    assert full.name == "canonical25" and full.ids == list(I.CANONICAL_IDS)
    w = I.load_subset("winnable17")
    assert len(w.ids) == 17 and set(w.ids) <= set(I.CANONICAL_IDS) and w.description


def test_custom_subset_from_path_and_subsets_dir(tmp_path, monkeypatch):
    p = tmp_path / "mine.json"
    p.write_text('{"name": "mine", "instances": ["lima-vm__lima-4803", "thlorenz__doctoc-328"]}')
    assert I.load_subset(str(p)).ids == ["lima-vm__lima-4803", "thlorenz__doctoc-328"]
    (tmp_path / "subsets").mkdir()
    (tmp_path / "subsets" / "mine.json").write_text(p.read_text())
    monkeypatch.chdir(tmp_path)
    assert I.load_subset("mine").name == "mine"


def test_bad_subsets_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="unknown subset"):
        I.load_subset("nope")
    p = tmp_path / "bad.json"
    p.write_text('{"name": "bad", "instances": ["gohugoio__hugo-14741"]}')
    with pytest.raises(ValueError, match="not in the canonical 25"):
        I.load_subset(str(p))
    p.write_text('{"name": "Bad Name", "instances": ["lima-vm__lima-4803"]}')
    with pytest.raises(ValueError, match="name"):
        I.load_subset(str(p))


def test_only_must_be_inside_the_subset():
    import pytest
    w = I.load_subset("winnable17")
    assert I.resolve_ids("", w.ids) == w.ids
    with pytest.raises(ValueError, match="not in this arm's subset"):
        I.resolve_ids("thlorenz__doctoc-328", w.ids)        # one of the 8 skipped tasks
