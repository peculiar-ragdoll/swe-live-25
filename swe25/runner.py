"""The run loop: every (instance, seed) cell of one arm, driven until it settles.

Instance-outer, so each instance's images are pulled once, used for all its seeds and passes, and
removed before the next instance (the Docker VM disk stays flat). Within an instance, a cell whose
grade is still running waits; other seeds' passes run meanwhile on the model server.

Cell state is always derived from the rows in results/<arm>.jsonl, so an interrupted run is resumed
by running the same command again.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import platform
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from swe25 import __version__, docker, instances, score
from swe25.config import Arm, Settings
from swe25.results import Row, append_row, read_rows

FRESH_CAP = 1200
RESUME_CAP = 3600
CEILING = score.CEILING_S
MAX_CONSECUTIVE_FAILURES = 3      # per cell: then the cell is left open for this run
MAX_STRUCK_CELLS_IN_A_ROW = 2     # two cells struck out back to back = an outage: stop the run
PI_VERSION = "0.80.3"


class RunAborted(RuntimeError):
    pass


class SubsetConflict(ValueError):
    pass


@dataclass
class RunSummary:
    rows_written: int
    settled: int
    open: int


def _default_agent(inst, arm, tag, wd, *, cap, resume, sample):
    if arm.agent == "claude":
        from swe25 import agent_claude
        return agent_claude.run_pass(inst, arm, tag, wd, sample=sample)
    from swe25 import agent_pi
    return agent_pi.run_pass(inst, arm, tag, wd, cap=cap, resume=resume, sample=sample)


def _default_grader(inst, wd, row):
    from swe25 import grade
    grade.grade(inst, wd, row, name=grade.container_name(row.model_id, row.instance_id, row.sample))


def _is_failure(row: Row) -> bool:
    """A pass that did no real work: counts toward the abort guard."""
    d = row.to_dict()
    if not score.is_real(d):
        return True
    err = row.error or ""
    if "no model turns" in err:
        return True
    return row.agent == "claude" and bool(err) and not row.timed_out and not row.patch_nonempty


def _git_sha() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                           cwd=Path(__file__).resolve().parent)
        return r.stdout.strip() or None
    except Exception:
        return None


def _host_ram_gb() -> float | None:
    try:
        r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
        return round(int(r.stdout.strip()) / 2**30, 1)
    except Exception:
        return None


class Runner:
    def __init__(self, settings: Settings, arm: Arm, ids: list[str], seeds: int, *,
                 agent_pass: Callable | None = None, grader: Callable | None = None, images=None,
                 log: Callable = print, subset: str = "canonical25"):
        self.s, self.arm, self.ids, self.seeds, self.subset = settings, arm, ids, seeds, subset
        self.agent_pass = agent_pass or _default_agent
        self.grader = grader or _default_grader
        self.images = images or docker.ImageSession(settings.min_free_gb)
        self.log = log
        self.path = settings.results_dir / f"{arm.name}.jsonl"
        self._lock = threading.Lock()
        self._abandoned = False
        self._struck_in_a_row = 0
        self.rows = [r for r in read_rows([self.path]) if r.get("model_id") == arm.name]

    # --- state -------------------------------------------------------------------------------
    def _cell_rows(self, iid: str, sample: int) -> list[dict]:
        with self._lock:
            return [r for r in self.rows if r.get("instance_id") == iid and int(r.get("sample", 0)) == sample]

    def verdict(self, iid: str, sample: int) -> str:
        return score.cell_verdict(self._cell_rows(iid, sample), self.arm.agent, CEILING)

    def _record(self, row: Row) -> None:
        d = append_row(self.path, row)
        with self._lock:
            self.rows.append(d)

    # --- run ---------------------------------------------------------------------------------
    def _write_runconfig(self, t0: float) -> Path:
        cfg = {
            "ts": t0, "harness_version": __version__, "git_sha": _git_sha(), "pi_version": PI_VERSION,
            "bash_patch_md5": docker.BASH_BASE_MD5, "arm": asdict(self.arm), "seeds": self.seeds,
            "subset": self.subset, "instances": self.ids,
            "caps": {"fresh": FRESH_CAP, "resume": RESUME_CAP, "ceiling": CEILING},
            "host": {"platform": platform.platform(), "machine": platform.machine(), "ram_gb": _host_ram_gb()},
        }
        p = self.s.results_dir / f"{self.arm.name}.runconfig.{int(t0)}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, indent=2))
        return p

    def _cap_for(self, rows: list[dict]) -> tuple[int, bool]:
        if self.arm.agent == "claude":
            return 1800, False
        real = [r for r in rows if score.is_real(r)]
        if not any(r.get("turns") for r in real):
            return FRESH_CAP, False          # nothing to continue: no model turn has happened yet
        return min(RESUME_CAP, max(60, int(CEILING - score.cum_wall(real)))), True

    def _grade_and_record(self, inst: dict, wd: Path, row: Row) -> None:
        try:
            self.grader(inst, wd, row)
        except Exception as e:
            row.error = f"{row.error} | grade_error:{type(e).__name__}" if row.error else \
                f"grade_error:{type(e).__name__}: {e}"
        self._record(row)
        self.log(f"  graded {row.instance_id} s{row.sample}: resolved={row.resolved} "
                 f"f2p={row.f2p_pass}/{row.f2p_total} p2p={row.p2p_pass}/{row.p2p_total}")

    def _abandon(self, iid: str, grading: dict[int, cf.Future]) -> None:
        """Second Ctrl-C: kill the running grade containers and stop waiting for them. Their passes
        are not recorded, so those cells simply run again next time."""
        from swe25 import grade
        self._abandoned = True
        for s in grading:
            docker.safe(["docker", "kill", grade.container_name(self.arm.name, iid, s)])
        self.log(f"abandoned {len(grading)} grade(s); their passes will be redone on the next run")

    def _run_instance(self, inst: dict, pool: cf.ThreadPoolExecutor) -> int:
        iid = inst["instance_id"]
        cells = [s for s in range(self.seeds) if self.verdict(iid, s) == "open"]
        if not cells:
            return 0
        self.log(f"[{iid}] seeds {cells}")
        tag = self.images.overlay(inst, self.arm.agent)
        grading: dict[int, cf.Future] = {}
        failures = dict.fromkeys(cells, 0)
        struck: set[int] = set()
        attempts = 0
        try:
            while True:
                for s, f in list(grading.items()):
                    if f.done():
                        f.result()
                        del grading[s]
                actionable = [s for s in cells
                              if s not in grading and s not in struck and self.verdict(iid, s) == "open"]
                if not actionable:
                    if not grading:
                        break
                    cf.wait(list(grading.values()), return_when=cf.FIRST_COMPLETED)
                    continue
                s = actionable[0]
                rows = self._cell_rows(iid, s)
                cap, resume = self._cap_for(rows)
                cum = score.cum_wall(rows)
                wd = self.s.work_dir / self.arm.name / f"{iid}__s{s}"
                attempts += 1
                row = self.agent_pass(inst, self.arm, tag, wd, cap=cap, resume=resume, sample=s)
                row.agent, row.sampling, row.subset = self.arm.agent, self.arm.sampling, self.subset
                row.pass_kind = "resume" if resume else "fresh"
                row.cum_wall_s = round(cum + row.wall_agent_s, 1)
                self.log(f"  s{s} {row.pass_kind} pass: {row.wall_agent_s}s timed_out={row.timed_out} "
                         f"patch={row.patch_nonempty} turns={row.turns}{' err=' + row.error if row.error else ''}")
                if _is_failure(row):
                    failures[s] += 1
                    if failures[s] >= MAX_CONSECUTIVE_FAILURES:
                        struck.add(s)
                        self._struck_in_a_row += 1
                        self.log(f"!! {iid} s{s}: {MAX_CONSECUTIVE_FAILURES} consecutive passes did no work "
                                 f"(last error: {row.error}); leaving this cell open and moving on")
                        if self._struck_in_a_row >= MAX_STRUCK_CELLS_IN_A_ROW:
                            if score.is_real(row.to_dict()):
                                self._record(row)
                            raise RunAborted(f"{MAX_STRUCK_CELLS_IN_A_ROW} consecutive cells did no work (last: "
                                             f"{iid} s{s}: {row.error}). Check the model server and Docker, "
                                             f"then re-run the same command to resume.")
                    if not score.is_real(row.to_dict()):
                        continue                      # content-free: never recorded
                else:
                    failures[s] = 0
                    self._struck_in_a_row = 0
                if not row.error or row.patch_nonempty:
                    grading[s] = pool.submit(self._grade_and_record, inst, wd, row)
                else:
                    self._record(row)
        except KeyboardInterrupt:
            if grading:
                self.log(f"interrupted: finishing {len(grading)} running grade(s) (Ctrl-C again to abandon)")
                try:
                    cf.wait(list(grading.values()))
                except KeyboardInterrupt:
                    self._abandon(iid, grading)
            raise
        finally:
            if not self._abandoned:
                for f in grading.values():
                    f.result()
            self.images.release(inst)
        return attempts

    def run(self) -> RunSummary:
        used = {r.get("subset") or "canonical25" for r in self.rows}
        if used - {self.subset}:
            raise SubsetConflict(f"arm {self.arm.name} was run on subset {', '.join(sorted(used))}, not "
                                 f"{self.subset}; results must stay on one task set (use a new arm name)")
        t0 = time.time()
        self._write_runconfig(t0)
        insts = instances.load()
        attempts = 0
        pool = cf.ThreadPoolExecutor(max_workers=2)
        try:
            for iid in self.ids:
                attempts += self._run_instance(insts[iid], pool)
        finally:
            pool.shutdown(wait=not self._abandoned, cancel_futures=True)
        written = sum(1 for r in read_rows([self.path])
                      if r.get("model_id") == self.arm.name and (r.get("ts") or 0) >= t0)
        if attempts and not written:
            raise RunAborted(f"{attempts} agent passes ran but 0 rows were written to {self.path}: "
                             f"this is a failed run, not a finished one")
        settled = open_ = 0
        for iid in self.ids:
            for s in range(self.seeds):
                if self.verdict(iid, s) == "open":
                    open_ += 1
                else:
                    settled += 1
        return RunSummary(rows_written=written, settled=settled, open=open_)
