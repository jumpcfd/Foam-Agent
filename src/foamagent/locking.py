"""Cross-process exclusive access to a case directory.

Nothing in this codebase previously prevented two independent Foam-Agent sessions -- two
separate `foamagent-mcp` server processes (one per connecting agent CLI session), or two
invocations of the validation/benchmark CLI harnesses -- from operating on the exact same
case directory at once. The destructive step in each of those paths (`run_start`'s
`clean=True` sweep in `services/run_async.py`, and the CLI harnesses' "clear the workspace,
then build here" idiom in `validation/run.py` and `bench/foambench_run.py`) assumed
exclusive use of its target directory; nothing enforced that assumption. Two sessions racing
on the same path is not hypothetical: it destroyed two in-progress runs during real use, each
losing over an hour of solve+review time with nothing to show for it.

The lock lives outside the directory it protects, in a centralized, path-keyed file under
`~/.cache/foamagent/locks/` -- not inside the case directory itself, since the whole point is
to guard against the directory being deleted, and a lock file that is itself a child of a
directory a concurrent `rmtree` might remove is exactly the kind of self-defeating design
this exists to avoid. `flock()` is held against this process's open file descriptor
regardless of what happens to the case directory being protected, and the kernel releases it
automatically if the holding process dies for any reason, including SIGKILL -- so a crashed
or killed session never leaves a stale lock behind. No cleanup code is needed for that case,
and none is provided for the lock *file* either: it is never deleted, only ever re-locked.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import hashlib
import json
import os
import socket
import time
from pathlib import Path
from typing import Iterator, Optional, Union

LOCK_DIR = Path.home() / ".cache" / "foamagent" / "locks"


class CaseDirectoryBusy(RuntimeError):
    """Another Foam-Agent session already holds the lock for this case directory."""


def _lock_path(case_dir: Union[str, Path]) -> Path:
    # Keyed by the resolved absolute path so `a/../a` and a relative path from a different
    # cwd both hash to the same lock as the canonical form -- otherwise the very collision
    # this exists to prevent could slip through on nothing more than a path-spelling
    # difference between two callers.
    key = hashlib.sha256(str(Path(case_dir).resolve()).encode()).hexdigest()[:32]
    return LOCK_DIR / f"{key}.lock"


def _describe_holder(lock_path: Path) -> str:
    try:
        info = json.loads(lock_path.read_text(encoding="utf-8"))
        return f"pid {info.get('pid')} on {info.get('host')} (claimed {info.get('claimed_at')})"
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return "another process (lock metadata unreadable)"


class CaseLock:
    """Explicit acquire/release form, for a claim that must outlive one `with` block --
    `run_start` returns immediately and the run continues on a background thread, so the
    lock has to be acquired synchronously in the calling thread (a caller needs to learn
    `CaseDirectoryBusy` right away, not after the fact) and released later, from whichever
    thread's `finally` actually finishes the run. `case_lock()` below is the context-manager
    form for every caller that doesn't have this split.
    """

    def __init__(self, case_dir: Union[str, Path]) -> None:
        self.case_dir = Path(case_dir)
        self._lock_path = _lock_path(self.case_dir)
        self._fd: Optional[int] = None

    def acquire(self, *, blocking: bool = False) -> None:
        if self._fd is not None:
            return  # already held by this instance
        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flags)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise CaseDirectoryBusy(
                    f"{self.case_dir} is already in use by {_describe_holder(self._lock_path)}."
                ) from exc
            raise
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "case_dir": str(self.case_dir.resolve()) if self.case_dir.exists() else str(self.case_dir),
            "claimed_at": time.time(),
        }).encode("utf-8"))
        os.fsync(fd)
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)  # releases the flock
            self._fd = None


@contextlib.contextmanager
def case_lock(case_dir: Union[str, Path], *, blocking: bool = False) -> Iterator[None]:
    """Claim exclusive access to `case_dir` for the life of this context.

    Raises `CaseDirectoryBusy` immediately if another live process already holds it
    (`blocking=False`, the default) -- a caller about to destroy and rebuild a directory
    must never silently wait behind, and then clobber, whatever the other session is doing
    with it. Pass `blocking=True` only for a caller that genuinely wants to wait its turn.
    """
    lock = CaseLock(case_dir)
    lock.acquire(blocking=blocking)
    try:
        yield
    finally:
        lock.release()
