"""`swe25 doctor`: everything a run needs, checked up front and reported in one list."""
from __future__ import annotations

import platform
import subprocess

from swe25 import docker, preflight
from swe25.config import Arm, ConfigError, Settings

RECOMMENDED_FREE_GB = 150
Result = tuple[bool | None, str]          # True ok, False failure, None warning


def check_host(s: Settings, arms: dict[str, Arm]) -> list[Result]:
    out: list[Result] = []
    mac = platform.system() == "Darwin" and platform.machine() == "arm64"
    out.append((True if mac else None, f"host: {platform.system()} {platform.machine()}"
                + ("" if mac else " (only Apple-Silicon macOS is tested)")))
    try:
        r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
        gb = int(r.stdout.strip()) / 2**30
        out.append((True if gb >= 60 else None, f"RAM: {gb:.0f} GB" + ("" if gb >= 60 else
                    " (27B-35B models plus agent containers want ~64 GB; small models are fine)")))
    except Exception:
        out.append((None, "RAM: unknown"))
    return out


def check_docker(s: Settings, arms: dict[str, Arm]) -> list[Result]:
    try:
        docker.check_daemon()
    except docker.DockerError as e:
        return [(False, str(e))]
    out: list[Result] = [(True, "Docker daemon reachable")]
    r = docker.sh(["docker", "run", "--rm", "--platform", docker.PLATFORM, "alpine", "uname", "-m"], 180)
    amd = r.stdout.strip() == "x86_64"
    out.append((amd, "amd64 emulation works" if amd else
                "amd64 containers do not run: enable 'Use Rosetta for x86_64/amd64 emulation' in Docker Desktop"))
    free = docker.vm_free_gb()
    if free >= 1e8:
        out.append((None, "Docker VM free disk: could not measure"))
    else:
        ok = True if free >= RECOMMENDED_FREE_GB else (None if free >= s.min_free_gb else False)
        out.append((ok, f"Docker VM free disk: {free:.0f} GB (recommended >= {RECOMMENDED_FREE_GB}, "
                        f"floor {s.min_free_gb:g})"))
    if docker.image_exists(docker.TOOLCHAIN_TAG):
        r = docker.sh(["docker", "run", "--rm", "--platform", docker.PLATFORM, "--entrypoint", "md5sum",
                       docker.TOOLCHAIN_TAG, docker.BASH_TARGET], 120)
        good = r.stdout.split()[:1] == [docker.BASH_BASE_MD5]
        out.append((good, f"toolchain {docker.TOOLCHAIN_TAG}: " + ("Pi bash.js matches the pinned patch base"
                    if good else "Pi bash.js does NOT match; run `swe25 build-toolchain --rebuild`")))
    else:
        out.append((None, f"toolchain {docker.TOOLCHAIN_TAG} not built yet (run `swe25 build-toolchain`)"))
    return out


def check_arms(s: Settings, arms: dict[str, Arm]) -> list[Result]:
    out: list[Result] = []
    if not arms:
        out.append((None, "no arms configured (copy arms.example.yaml to arms.yaml)"))
    for arm in arms.values():
        if arm.agent == "claude":
            from swe25 import agent_claude
            try:
                out.append((True, f"arm {arm.name}: Claude auth via {agent_claude.auth_var()}"))
            except ConfigError as e:
                out.append((False, f"arm {arm.name}: {e}"))
            continue
        try:
            warnings = preflight.check_pi_arm(arm)
            out.append((True, f"arm {arm.name}: {arm.endpoint} serving, context {arm.context}"))
            out.extend((None, w) for w in warnings)
        except preflight.PreflightError as e:
            out.append((False, str(e)))
    return out


CHECKS = [check_host, check_docker, check_arms]


def run(s: Settings, arms: dict[str, Arm], out=print) -> int:
    failed = False
    for check in CHECKS:
        try:
            results = check(s, arms)
        except Exception as e:
            results = [(False, f"{getattr(check, '__name__', 'check')} crashed: {type(e).__name__}: {e}")]
        for ok, msg in results:
            failed |= ok is False
            out(f"{'✓' if ok else ('✗' if ok is False else '!')} {msg}")
    return 1 if failed else 0
