"""Docker plumbing: timeout-guarded calls, the toolchain image, per-instance overlays, disk guard.

Every call has a timeout. A wedged Docker daemon (e.g. a full VM disk) makes plain `docker kill`
or `docker rm` hang forever, which is how an unattended run stalls for hours.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

PLATFORM = "linux/amd64"
DOCKER_DIR = Path(__file__).resolve().parents[1] / "docker"
TOOLCHAIN_TAG = "swe25-pi-toolchain:0.80.3"
BASH_TARGET = "/usr/local/lib/node_modules/@earendil-works/pi-coding-agent/dist/core/tools/bash.js"
BASH_PATCH = DOCKER_DIR / "pi_bash_0.80.3.js"
BASH_BASE_MD5 = "8e91e32c1bf077fa87f02d9c7c6cc58e"   # stock Pi 0.80.3 bash.js the patch was built from
_DOCKERFILES = {"pi": "Dockerfile.pi-overlay", "claude": "Dockerfile.claude"}
_patch_ok: dict[str, bool] = {}


class DockerError(RuntimeError):
    pass


class DiskFull(DockerError):
    pass


class PatchMismatch(DockerError):
    pass


def sh(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def safe(args: list[str], timeout: float = 60) -> None:
    """A cleanup call that must never block or raise."""
    try:
        sh(args, timeout)
    except Exception:
        pass


def check_daemon() -> None:
    try:
        r = sh(["docker", "info", "--format", "{{.ServerVersion}}"], 30)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise DockerError(f"Docker is not usable: {e}") from e
    if r.returncode != 0:
        raise DockerError("Docker daemon not reachable — is Docker Desktop running?")


def image_exists(tag: str) -> bool:
    return sh(["docker", "image", "inspect", tag], 30).returncode == 0


def vm_free_gb() -> float:
    """Free space on the Docker VM disk in GB (the disk that fills). A failed probe returns a huge
    number so it never blocks work; a real out-of-space error still surfaces from the pull."""
    try:
        r = sh(["docker", "run", "--rm", "alpine", "df", "-Pk", "/"], 120)
        line = [ln for ln in r.stdout.splitlines() if ln.strip()][-1]
        return int(line.split()[3]) / (1024 * 1024)
    except Exception:
        return 1e9


def ensure_toolchain(rebuild: bool = False) -> str:
    if not rebuild and image_exists(TOOLCHAIN_TAG):
        return TOOLCHAIN_TAG
    r = sh(["docker", "build", "--platform", PLATFORM, "-t", TOOLCHAIN_TAG,
            "-f", str(DOCKER_DIR / "Dockerfile.pi-toolchain"), str(DOCKER_DIR)], 1800)
    if r.returncode != 0:
        raise DockerError(f"toolchain build failed: {r.stderr[-600:]}")
    return TOOLCHAIN_TAG


def _slug(inst: dict) -> str:
    return inst["instance_id"].replace("/", "_").lower()[-100:]


class ImageSession:
    """Pulls and builds images on demand and removes them again, one instance at a time.

    Only base images this session pulled are ever removed, so images the user (or another run)
    already had stay put."""

    def __init__(self, min_free_gb: float = 20.0):
        self.min_free_gb = min_free_gb
        self._pulled: set[str] = set()

    def base(self, inst: dict) -> str:
        base = inst["docker_image"]
        if image_exists(base):
            return base
        free = vm_free_gb()
        if free < self.min_free_gb:
            raise DiskFull(f"only {free:.1f} GB free on the Docker VM (< {self.min_free_gb} GB floor); "
                           f"free disk before pulling {base}")
        r = sh(["docker", "pull", "--platform", PLATFORM, base], 3600)
        if r.returncode != 0:
            raise DockerError(f"pull failed for {base}: {r.stderr[-400:]}")
        self._pulled.add(base)
        return base

    def overlay(self, inst: dict, kind: str) -> str:
        tag = f"swe25-{kind}:{_slug(inst)}"
        if image_exists(tag):
            return tag
        base = self.base(inst)
        ensure_toolchain()
        r = sh(["docker", "build", "--platform", PLATFORM, "--build-arg", f"BASE={base}", "-t", tag,
                "-f", str(DOCKER_DIR / _DOCKERFILES[kind]), str(DOCKER_DIR)], 1800)
        if r.returncode != 0:
            raise DockerError(f"overlay build failed for {inst['instance_id']}: {r.stderr[-400:]}")
        return tag

    def release(self, inst: dict) -> None:
        for kind in _DOCKERFILES:
            safe(["docker", "rmi", f"swe25-{kind}:{_slug(inst)}"], timeout=120)
        base = inst["docker_image"]
        if base in self._pulled:
            safe(["docker", "rmi", base], timeout=120)   # no -f: refuses while a container uses it
            self._pulled.discard(base)


def bash_patch_mount(tag: str) -> list[str]:
    """`-v` args mounting the timeout-patched bash.js over Pi's. Raises PatchMismatch if the image's
    stock bash.js is not the one the patch was built from (never run an unpatched agent)."""
    ok = _patch_ok.get(tag)
    if ok is None:
        r = sh(["docker", "run", "--rm", "--platform", PLATFORM, "--entrypoint", "md5sum", tag, BASH_TARGET], 120)
        out = r.stdout.split()
        ok = bool(out) and out[0] == BASH_BASE_MD5
        _patch_ok[tag] = ok
    if not ok:
        raise PatchMismatch(f"{tag}: Pi's bash.js is not the pinned 0.80.3 file; rebuild with "
                            f"`swe25 build-toolchain --rebuild`")
    return ["-v", f"{BASH_PATCH}:{BASH_TARGET}:ro"]
