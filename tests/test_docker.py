import hashlib
import subprocess

import pytest

from swe25 import docker as D

INST = {"instance_id": "org__repo-1", "docker_image": "starryzhang/sweb.eval.x86_64.org_1776_repo-1"}


class FakeDocker:
    """Records docker invocations; `present` is the set of image tags that exist."""

    def __init__(self, present=(), free_gb=100.0, md5="8e91e32c1bf077fa87f02d9c7c6cc58e"):
        self.present, self.free_gb, self.md5, self.calls = set(present), free_gb, md5, []

    def __call__(self, cmd, timeout):
        self.calls.append(cmd)
        out, rc = "", 0
        if cmd[:3] == ["docker", "image", "inspect"]:
            rc = 0 if cmd[3] in self.present else 1
        elif cmd[:2] == ["docker", "pull"]:
            self.present.add(cmd[-1])
        elif cmd[:2] == ["docker", "build"]:
            self.present.add(cmd[cmd.index("-t") + 1])
        elif cmd[:2] == ["docker", "rmi"]:
            self.present.discard(cmd[2])
        elif "md5sum" in cmd:
            out = f"{self.md5}  /x/bash.js\n"
        elif "df" in cmd:
            kb = int(self.free_gb * 1024 * 1024)
            out = f"Filesystem 1024-blocks Used Available Capacity Mounted\nx 1 1 {kb} 1% /\n"
        return subprocess.CompletedProcess(cmd, rc, out, "")

    def ran(self, *prefix):
        return [c for c in self.calls if c[: len(prefix)] == list(prefix)]


@pytest.fixture
def fake(monkeypatch):
    f = FakeDocker(present={D.TOOLCHAIN_TAG})
    monkeypatch.setattr(D, "sh", f)
    monkeypatch.setattr(D, "safe", lambda args, timeout=60: f(args, timeout))
    D._patch_ok.clear()
    return f


def test_disk_below_floor_refuses_before_pull(fake):
    fake.free_gb = 5
    with pytest.raises(D.DiskFull):
        D.ImageSession(min_free_gb=20).overlay(INST, "pi")
    assert not fake.ran("docker", "pull")


def test_pulled_base_is_released(fake):
    s = D.ImageSession(min_free_gb=20)
    tag = s.overlay(INST, "pi")
    assert tag == "swe25-pi:org__repo-1"
    s.release(INST)
    assert INST["docker_image"] not in fake.present and tag not in fake.present


def test_preexisting_base_is_kept(fake):
    fake.present.add(INST["docker_image"])
    s = D.ImageSession(min_free_gb=20)
    s.overlay(INST, "pi")
    s.release(INST)
    assert INST["docker_image"] in fake.present
    assert not fake.ran("docker", "pull")
    assert not fake.ran("docker", "rmi", INST["docker_image"])


def test_bash_patch_mismatch_aborts(fake):
    fake.md5 = "0" * 32
    with pytest.raises(D.PatchMismatch):
        D.bash_patch_mount("swe25-pi:x")


def test_bash_patch_match_mounts(fake):
    assert D.bash_patch_mount("swe25-pi:x") == ["-v", f"{D.BASH_PATCH}:{D.BASH_TARGET}:ro"]


def test_pinned_md5_matches_shipped_original():
    orig = D.DOCKER_DIR / "pi_bash_0.80.3.orig.js"
    assert hashlib.md5(orig.read_bytes()).hexdigest() == D.BASH_BASE_MD5
    assert D.BASH_PATCH.exists()


def test_vm_free_gb_parses_df(fake):
    fake.free_gb = 42
    assert round(D.vm_free_gb()) == 42
