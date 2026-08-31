"""Where a review does its arithmetic.

A reviewer with no way to compute checks a residual history by eye and compares against
the literature from memory. This runs a Python script for it — in a container that mounts
the case read-only, has no network, and is thrown away afterwards.

The read-only mount is the point. The rule that a reviewer may read a case but not change
it was until now a list of tool names that get dropped from its allowlist; a name is a
guess about what a tool does. Here the kernel refuses the write, and this process builds
the command line itself, so the guarantee is one the server can check rather than request.

What the script may reach:

    /case   the case being reviewed, read-only
    /work   a directory inside the case, writable, where the script itself is kept
    /tmp    a small tmpfs, gone when the container exits

and nothing else: no network, no capabilities, no writable root filesystem.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from foamagent.locking import case_lock
from foamagent.logger import get_logger
from foamagent.review.documents import scan_numbers
from foamagent.review.settings import SandboxSettings, load_settings

logger = get_logger(__name__)

# The directory a case keeps its review calculations in, one subdirectory per document.
WORK_DIRNAME = "review-work"
REPORT_WORK = "report"
SCRIPT_PATTERN = "script-{n}.py"

# Not settings. A review's arithmetic is small — sums over a log, a profile compared
# against a table — and a limit that can be raised by a settings file is a limit that gets
# raised instead of the script being fixed.
MEMORY_LIMIT = "2g"
CPU_LIMIT = "2"
PIDS_LIMIT = "256"
TMPFS_SIZE = "256m"

# Enough for a table of numbers and a traceback, and short of what would fill a review's
# context with the output of a loop that should not have been written.
OUTPUT_LIMIT = 1_000_000

# Only ever paid once per machine, on a link that may be slow.
IMAGE_PULL_SECONDS = 600


@dataclass(frozen=True)
class ScriptResult:
    """What one script run produced."""

    ok: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    detail: str = ""
    script_file: str = ""


def work_dir(case_dir: str | Path, destination: str | int) -> Path:
    """The directory a given review document keeps its calculations in.

    Inside the case, because the arithmetic behind a finding is part of the record: the
    report is written later by someone who was not there, and a number nobody can recompute
    is a number nobody can check.
    """
    return Path(case_dir) / WORK_DIRNAME / str(destination)


def _next_script_number(directory: Path) -> int:
    numbers = scan_numbers(directory, SCRIPT_PATTERN)
    return max(numbers) + 1 if numbers else 1


def save_script(source: str, directory: Path) -> Path:
    """Write a script into the work directory under the next free number.

    Listing the directory for the next number and writing under it happen inside one
    `case_lock`, keyed on `directory` itself (a review's own work directory, not the whole
    case -- no reason to contend with an unrelated review's lock on the same case_dir) --
    held here rather than left to the caller, so two `run_script` calls landing in the same
    work directory close together cannot both read the same listing and each write
    script-<n>.py under the same n, one silently overwriting the other's script.
    """
    directory.mkdir(parents=True, exist_ok=True)
    with case_lock(directory, blocking=True):
        path = directory / SCRIPT_PATTERN.format(n=_next_script_number(directory))
        path.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8")
    return path


def _user_argument() -> List[str]:
    """Run as the invoking user, so files land in the case owned by whoever owns the case."""
    if not hasattr(os, "getuid"):  # pragma: no cover - the server runs on Unix
        return []
    return ["--user", f"{os.getuid()}:{os.getgid()}"]


def _container_name() -> str:
    """A name unique enough to `docker kill` this run and no other.

    `--rm` only removes a container once it exits on its own; a `docker run` with no
    `--name` given a `subprocess.run(..., timeout=...)` that expires leaves the Python side
    killed but the container itself un-targeted and still running (`execution.py`'s
    `DockerBackend` solved the identical problem for solver runs the same way -- see its own
    `_container_name()`). The pid, timestamp and random suffix mirror that function so a
    stray container from either code path is greppable the same way.
    """
    return f"foamagent-review-sandbox-{os.getpid()}-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def docker_argv(
    script: Path,
    *,
    case_dir: str | Path,
    settings: Optional[SandboxSettings] = None,
    name: Optional[str] = None,
) -> List[str]:
    """The command line that runs ``script`` against ``case_dir``.

    ``script`` must already be inside the work directory: that directory is the only
    writable mount, and mounting it is what makes the script visible to the container.
    ``name`` lets ``run_script`` know what to `docker kill` if the run times out; left to
    generate its own when called on its own (from a test, for instance).
    """
    settings = settings or load_settings().sandbox
    work = script.parent
    name = name or _container_name()

    return [
        "docker", "run", "--rm",
        "--name", name,
        # No network at all. The review reaches the literature through its own web tools,
        # in the session; nothing that runs here needs to reach anything, and anything that
        # tries is either a mistake or an instruction that came out of the case files.
        "--network", "none",
        "--memory", MEMORY_LIMIT,
        # Without this, the memory limit is a limit on memory plus swap, which is no limit.
        "--memory-swap", MEMORY_LIMIT,
        "--cpus", CPU_LIMIT,
        "--pids-limit", PIDS_LIMIT,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        "--tmpfs", f"/tmp:rw,size={TMPFS_SIZE}",
        *_user_argument(),
        "--workdir", "/work",
        "-v", f"{Path(case_dir).resolve()}:/case:ro",
        "-v", f"{work.resolve()}:/work",
        "-e", "HOME=/tmp",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        # Unbuffered, so a script that dies partway still shows what it had printed.
        "-e", "PYTHONUNBUFFERED=1",
        settings.image,
        "python", f"/work/{script.name}",
    ]


def unavailable(reason: str) -> ScriptResult:
    """The result returned when no script could be run.

    Reported rather than raised, and the review carries on: a check that could not be made
    belongs in the findings, where the reader learns it was not made.
    """
    return ScriptResult(ok=False, exit_code=-1, detail=reason)


def available(settings: Optional[SandboxSettings] = None) -> Optional[str]:
    """Why scripts cannot be run here, or None when they can."""
    settings = settings or load_settings().sandbox
    if not settings.enabled:
        return (
            "Running scripts is switched off for this installation "
            "(review.sandbox.runtime is 'none')."
        )
    if shutil.which("docker") is None:
        return (
            "Scripts run in a container and docker is not on this machine's PATH, so no "
            "calculation can be run here."
        )
    return None


def ensure_image(image: str) -> Optional[str]:
    """Fetch the image if this machine does not have it. Returns why it could not be.

    Done as its own step so that the first review on a machine does not have a page of
    download progress prepended to whatever its script printed.
    """
    # stdin is DEVNULL on every spawn here for the reason given in channel.py: nothing this
    # server starts may hold the descriptor the harness talks to it on.
    present = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if present.returncode == 0:
        return None

    logger.info("Fetching %s; this happens once.", image)
    try:
        pulled = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            text=True,
            timeout=IMAGE_PULL_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return f"Fetching the image {image} took longer than {IMAGE_PULL_SECONDS}s."
    except OSError as exc:
        return f"Could not fetch the image {image}: {exc}"

    if pulled.returncode != 0:
        return f"Could not fetch the image {image}: {(pulled.stderr or '').strip()[:500]}"
    return None


def _clip(text: str) -> str:
    text = text or ""
    if len(text) <= OUTPUT_LIMIT:
        return text
    return text[:OUTPUT_LIMIT] + f"\n[output truncated at {OUTPUT_LIMIT} characters]"


def run_script(
    source: str,
    *,
    case_dir: str | Path,
    destination: Path,
    settings: Optional[SandboxSettings] = None,
) -> ScriptResult:
    """Run one Python script against a case and return what it printed.

    ``destination`` is the work directory: the script is written there first, so what the
    review computed stays in the case alongside what it concluded.
    """
    settings = settings or load_settings().sandbox

    reason = available(settings)
    if reason:
        return unavailable(reason)

    if not Path(case_dir).is_dir():
        return unavailable(f"There is no case at {case_dir}.")

    missing_image = ensure_image(settings.image)
    if missing_image:
        return unavailable(missing_image)

    script = save_script(source, Path(destination))
    name = _container_name()
    argv = docker_argv(script, case_dir=case_dir, settings=settings, name=name)

    logger.info("Running %s against %s", script.name, case_dir)

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=settings.timeout_seconds,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        # subprocess.run only kills the `docker run` client process; the container itself,
        # named above for exactly this, otherwise keeps running with nothing left to stop
        # it -- `--rm` removes a container once it exits on its own, not one still running.
        subprocess.run(
            ["docker", "kill", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        return ScriptResult(
            ok=False,
            exit_code=-1,
            detail=f"The script did not finish within {settings.timeout_seconds}s.",
            script_file=str(script),
        )
    except OSError as exc:
        return ScriptResult(
            ok=False, exit_code=-1, detail=f"Could not start the container: {exc}",
            script_file=str(script),
        )

    return ScriptResult(
        ok=completed.returncode == 0,
        exit_code=completed.returncode,
        stdout=_clip(completed.stdout),
        stderr=_clip(completed.stderr),
        script_file=str(script),
    )


__all__ = [
    "REPORT_WORK",
    "ScriptResult",
    "WORK_DIRNAME",
    "available",
    "docker_argv",
    "run_script",
    "save_script",
    "unavailable",
    "work_dir",
]
