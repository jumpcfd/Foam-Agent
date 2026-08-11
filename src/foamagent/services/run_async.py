"""Starting a solver run and asking about it later.

A CFD run lasts minutes to hours. The MCP `run` tool blocked for all of it, which no
client's timeout survives, so the caller learned the outcome only if it happened to be
quick. Here the run is started, an identifier comes back at once, and progress is read from
the log the same way a person reads it: tail the file.

State lives in this process, since the server outlives any single run, and is mirrored to
`<case_dir>/.foamagent/runs/<id>.json` so a run that outlived a server restart can still be
identified. The logs themselves are the case directory's own `Allrun.out` and `log.*`.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from foamagent.execution import get_execution_backend
from foamagent.locking import CaseLock
from foamagent.logger import get_logger
from foamagent.utils import check_foam_errors, remove_numeric_folders

logger = get_logger(__name__)

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
TIMED_OUT = "timed_out"
STOPPED = "stopped"

RUNS_SUBDIR = os.path.join(".foamagent", "runs")


@dataclass
class RunRecord:
    """One invocation of a case's Allrun script."""

    run_id: str
    case_dir: str
    state: str = RUNNING
    started_at: float = 0.0
    finished_at: Optional[float] = None
    returncode: Optional[int] = None
    errors: List[str] = field(default_factory=list)
    detail: str = ""

    @property
    def seconds(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    @property
    def done(self) -> bool:
        return self.state != RUNNING

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["seconds"] = round(self.seconds, 1)
        return data


class RunRegistry:
    """The runs this process knows about."""

    def __init__(self) -> None:
        self._runs: Dict[str, RunRecord] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._stopping: Dict[str, threading.Event] = {}
        # run_id -> (backend, plan, process), so a stop can reach the process group and,
        # under docker, the container.
        self._processes: Dict[str, tuple] = {}
        self._lock = threading.Lock()

    # -- starting ------------------------------------------------------------------

    def start(self, case_dir: str, *, timeout: float = 3600.0, clean: bool = True) -> RunRecord:
        case_dir = os.path.abspath(case_dir)
        allrun = os.path.join(case_dir, "Allrun")
        if not os.path.isfile(allrun):
            raise FileNotFoundError(f"No Allrun script in {case_dir}")

        # Claimed here, synchronously, in the calling thread -- not inside `_execute` on its
        # background thread -- so a caller whose case_dir is already owned by another live
        # session (a second `foamagent-mcp` process, or anything else that goes through this
        # registry) gets `CaseDirectoryBusy` back from `run_start` itself, immediately,
        # rather than the collision being silently deferred into the clean-then-run step
        # below. Released in `_execute`'s `finally`, once this run genuinely finishes.
        lock = CaseLock(case_dir)
        lock.acquire()

        run_id = uuid.uuid4().hex[:12]
        record = RunRecord(run_id=run_id, case_dir=case_dir, started_at=time.time())

        with self._lock:
            self._runs[run_id] = record
            self._stopping[run_id] = threading.Event()

        self._persist(record)

        thread = threading.Thread(
            target=self._execute,
            args=(record, timeout, clean, lock),
            name=f"foamagent-run-{run_id}",
            daemon=True,
        )
        with self._lock:
            self._threads[run_id] = thread
        thread.start()

        logger.info("Started run %s in %s", run_id, case_dir)
        return record

    def _execute(self, record: RunRecord, timeout: float, clean: bool, lock: CaseLock) -> None:
        case_dir = record.case_dir
        out_file = os.path.join(case_dir, "Allrun.out")
        err_file = os.path.join(case_dir, "Allrun.err")

        try:
            if clean:
                # A rerun in a directory that still holds the previous attempt's logs and
                # time directories cannot be told apart from a fresh one.
                for stale in [*Path(case_dir).glob("log*"), Path(out_file), Path(err_file)]:
                    stale.unlink(missing_ok=True)
                remove_numeric_folders(case_dir)

            allrun = os.path.join(case_dir, "Allrun")
            backend = get_execution_backend()
            os.chmod(allrun, 0o777)

            def remember(plan, process):
                with self._lock:
                    self._processes[record.run_id] = (backend, plan, process)

            result = backend.run(["bash", allrun], case_dir, timeout=timeout, on_start=remember)
            Path(out_file).write_text(result.stdout, encoding="utf-8")
            Path(err_file).write_text(result.stderr, encoding="utf-8")

            errors = [self._as_text(e) for e in check_foam_errors(case_dir)]
            with self._lock:
                record.returncode = result.returncode
                record.errors = errors
                if self._stopping[record.run_id].is_set():
                    record.state = STOPPED
                elif result.timed_out:
                    record.state = TIMED_OUT
                    record.detail = f"No result within {timeout:.0f}s."
                elif errors:
                    record.state = FAILED
                    record.detail = f"{len(errors)} error(s) in the logs."
                else:
                    record.state = SUCCEEDED
        except Exception as exc:  # the run must never take the server down with it
            logger.exception("Run %s failed to execute", record.run_id)
            with self._lock:
                record.state = FAILED
                record.detail = f"{type(exc).__name__}: {exc}"
        finally:
            record.finished_at = time.time()
            self._persist(record)
            logger.info("Run %s %s after %.0fs", record.run_id, record.state, record.seconds)
            lock.release()

    @staticmethod
    def _as_text(error) -> str:
        if isinstance(error, dict):
            return f"{error.get('file', 'unknown')}: {error.get('error_content', '')}".strip()
        return str(error)

    # -- asking --------------------------------------------------------------------

    def get(self, run_id: str) -> Optional[RunRecord]:
        """The run with this identifier, if this process started it.

        A run started by an earlier server is not reachable by identifier alone: the
        records live under the case directory, and a bare identifier does not say which
        case that is. `latest(case_dir)` is the way back to one of those.
        """
        with self._lock:
            return self._runs.get(run_id)

    def latest(self, case_dir: str) -> Optional[RunRecord]:
        """The most recent run for a case, for a caller that lost the identifier."""
        case_dir = os.path.abspath(case_dir)
        with self._lock:
            candidates = [r for r in self._runs.values() if r.case_dir == case_dir]
        if candidates:
            return max(candidates, key=lambda r: r.started_at)

        directory = Path(case_dir) / RUNS_SUBDIR
        if not directory.is_dir():
            return None
        records = [self._read(path) for path in directory.glob("*.json")]
        records = [r for r in records if r is not None]
        return max(records, key=lambda r: r.started_at) if records else None

    def stop(self, run_id: str) -> Optional[RunRecord]:
        record = self.get(run_id)
        if record is None or record.done:
            return record

        with self._lock:
            self._stopping[run_id].set()
            handle = self._processes.get(run_id)

        # The same operation the backend performs when a run overruns: kill the process
        # group and, under docker, the container.
        if handle is not None:
            backend, plan, process = handle
            backend.terminate(plan, process)
        return record

    # -- persistence ---------------------------------------------------------------

    def _path(self, record: RunRecord) -> Path:
        return Path(record.case_dir) / RUNS_SUBDIR / f"{record.run_id}.json"

    def _persist(self, record: RunRecord) -> None:
        try:
            path = self._path(record)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
        except OSError as exc:
            logger.debug("Could not record run %s: %s", record.run_id, exc)

    @staticmethod
    def _read(path: Path) -> Optional[RunRecord]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        known = {f for f in RunRecord.__dataclass_fields__}
        record = RunRecord(**{k: v for k, v in data.items() if k in known})
        # A record left as running by a server that exited says nothing about the run.
        if record.state == RUNNING and record.finished_at is None:
            record.state = STOPPED
            record.detail = "The server that started this run is no longer running it."
        return record


_registry = RunRegistry()


def get_run_registry() -> RunRegistry:
    return _registry


def set_run_registry(registry: RunRegistry) -> None:
    """Replace the registry. For tests."""
    global _registry
    _registry = registry


def tail_log(case_dir: str, *, name: str = "Allrun.out", lines: int = 50) -> str:
    """Return the last ``lines`` lines of a log in the case directory.

    ``name`` may be Allrun.out, Allrun.err, or any log.* the run produced; "latest" picks
    the most recently written log, which is the one a running solver is filling.
    """
    directory = Path(os.path.abspath(case_dir))
    if name == "latest":
        logs = sorted(directory.glob("log.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            logs = [p for p in (directory / "Allrun.out", directory / "Allrun.err") if p.is_file()]
        if not logs:
            return ""
        path = logs[0]
    else:
        path = directory / name
        # Reading "../../etc/passwd" through a log name is not a log read.
        if os.path.commonpath([directory, path.resolve()]) != str(directory):
            raise ValueError(f"{name} is not inside the case directory")

    if not path.is_file():
        return ""

    content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(content[-max(1, lines):])


def list_logs(case_dir: str) -> List[str]:
    """Which logs the case directory holds, newest first."""
    directory = Path(os.path.abspath(case_dir))
    if not directory.is_dir():
        return []
    candidates = list(directory.glob("log.*"))
    candidates += [p for p in (directory / "Allrun.out", directory / "Allrun.err") if p.is_file()]
    return [p.name for p in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)]


__all__ = [
    "FAILED",
    "RUNNING",
    "STOPPED",
    "SUCCEEDED",
    "TIMED_OUT",
    "RunRecord",
    "RunRegistry",
    "get_run_registry",
    "list_logs",
    "set_run_registry",
    "tail_log",
]
