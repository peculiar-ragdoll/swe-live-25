"""Real Docker runs (opt in: `uv run pytest -m docker`). Pulls the lima-vm image (~3 GB) if absent."""
import pytest

from swe25 import docker, grade, instances
from swe25.results import Row

pytestmark = pytest.mark.docker
IID = "lima-vm__lima-4803"


def test_gold_patch_resolves(tmp_path):
    (r,) = grade.gold_check([IID], tmp_path)
    assert r["resolved"], r


def test_empty_patch_does_not_resolve(tmp_path):
    inst = instances.load()[IID]
    images = docker.ImageSession()
    images.base(inst)
    try:
        row = Row(IID, "EMPTY")
        grade.grade(inst, tmp_path, row)
    finally:
        images.release(inst)
    assert not row.resolved and row.f2p_total > 0
