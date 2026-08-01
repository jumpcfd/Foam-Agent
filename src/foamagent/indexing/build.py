"""Building the reference library from a live OpenFOAM installation.

Three steps, each of which has to work for a containerised OpenFOAM as well as a local one:

1. Copy the tutorials somewhere this process can read. Under the docker runtime the
   tutorials are inside the image, so the copy is made by the container itself into a
   mounted directory. A copy is made even for a native installation, because the scan
   writes shared blockMeshDict files into the cases it reads.
2. Collect the help text of every application, in one pass inside the environment rather
   than one process launch per command.
3. Write the library an AI harness reads: the catalogue, the cleaned cases and the
   command help.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from foamagent.environment import OpenFOAMEnvironment, detect_environment
from foamagent.execution import ExecutionBackend, get_execution_backend
from foamagent.indexing import index_dir
from foamagent.indexing.library import LibraryResult, write_library
from foamagent.indexing.tutorials import find_cases
from foamagent.logger import get_logger

logger = get_logger(__name__)

COMMAND_HELP_SCRIPT = r"""
set -u
if [ -z "${FOAM_APPBIN:-}" ] || [ ! -d "${FOAM_APPBIN}" ]; then
  exit 3
fi
for app in "${FOAM_APPBIN}"/*; do
  [ -x "$app" ] || continue
  name=$(basename "$app")
  help_text=$("$app" -help 2>&1 || true)
  printf '<command_begin><command>%s</command><help_text>%s</help_text></command_end>\n\n' \
    "$name" "$help_text"
done
"""


@dataclass
class BuildResult:
    environment: OpenFOAMEnvironment
    index_path: Path
    case_count: int
    command_count: int
    seconds: float
    library: Optional[LibraryResult] = None

    def describe(self) -> str:
        library = f", library: {self.library.describe()}" if self.library else ""
        return (
            f"{self.case_count} cases, {self.command_count} commands{library}, "
            f"in {self.seconds:.0f}s -> {self.index_path}"
        )


def copy_tutorials(
    environment: OpenFOAMEnvironment,
    destination: Path,
    backend: Optional[ExecutionBackend] = None,
    *,
    timeout: float = 900.0,
) -> Path:
    """Place a readable copy of the installation's tutorials under ``destination``.

    Returns the directory holding the copy.
    """
    backend = backend or get_execution_backend()
    if not environment.tutorials:
        raise RuntimeError(
            "The OpenFOAM environment did not report FOAM_TUTORIALS, so there are no "
            "tutorials to index. Check that the OpenFOAM environment can be sourced."
        )

    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "tutorials"
    if target.exists():
        shutil.rmtree(target)

    source = Path(environment.tutorials)
    if source.is_dir():
        # Readable from here: a plain copy, and no container needed.
        logger.info("Copying tutorials from %s", source)
        shutil.copytree(source, target, symlinks=True, ignore_dangling_symlinks=True)
        return target

    # Not visible from this process, so the environment copies them out for us. destination
    # is the backend's working directory, which the docker backend mounts into the
    # container at the same absolute path.
    logger.info("Copying tutorials out of the OpenFOAM environment (%s)", environment.tutorials)
    result = backend.run(
        ["cp", "-a", str(source), str(target)], str(destination), timeout=timeout
    )
    if not result.ok:
        raise RuntimeError(
            f"Could not copy {source} out of the OpenFOAM environment: "
            f"{(result.stderr or result.stdout).strip()[:500]}"
        )
    if not target.is_dir():
        raise RuntimeError(f"Tutorials were not copied to {target}")

    return target


def collect_command_help(
    backend: Optional[ExecutionBackend] = None,
    *,
    working_dir: Optional[Path] = None,
    timeout: float = 900.0,
) -> str:
    """Return the help text of every application, one block per command."""
    backend = backend or get_execution_backend()
    work = str(working_dir or Path.cwd())

    result = backend.run(["bash", "-c", COMMAND_HELP_SCRIPT], work, timeout=timeout)
    if result.returncode == 3:
        raise RuntimeError("FOAM_APPBIN is not set or not a directory; cannot collect command help.")
    if result.timed_out:
        raise RuntimeError(f"Collecting command help timed out after {timeout}s.")

    # A non-zero exit from an individual `-help` is swallowed by the script itself; anything
    # left is a shell-level failure worth reporting, but partial output is still usable.
    if not result.ok and not result.stdout.strip():
        raise RuntimeError(
            f"Collecting command help failed: {(result.stderr or '').strip()[:500]}"
        )

    return result.stdout


def build_index(
    environment: Optional[OpenFOAMEnvironment] = None,
    *,
    backend: Optional[ExecutionBackend] = None,
    keep_tutorials: bool = False,
) -> BuildResult:
    """Build the reference library for an OpenFOAM installation."""
    started = time.monotonic()
    backend = backend or get_execution_backend()
    environment = environment or detect_environment(backend)

    if not environment.detected:
        raise RuntimeError(
            "Could not detect an OpenFOAM environment, so there is nothing to index. "
            "Source OpenFOAM, or set FOAMAGENT_OPENFOAM_RUNTIME=docker with an image that "
            "has it."
        )

    destination = index_dir(environment)
    work_dir = destination / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Building index for %s at %s", environment.describe(), destination)

    try:
        tutorials = copy_tutorials(environment, work_dir, backend)

        cases, scan_stats = find_cases(tutorials)
        logger.info(
            "Found %d cases in %d directories (%d files read)",
            len(cases),
            scan_stats["directories_scanned"],
            scan_stats["files_read_success"],
        )
        if not cases:
            raise RuntimeError(f"No tutorial cases found under {tutorials}.")

        command_help = collect_command_help(backend, working_dir=work_dir)
        command_count = command_help.count("<command_begin>")
        logger.info("Collected help for %d commands", command_count)

        # What a harness reads. Written from the same scan as the catalogue, so the two
        # cannot describe different installations.
        library = write_library(
            cases,
            destination,
            environment_description=environment.describe(),
            command_help=command_help,
        )
    finally:
        # The copied tutorials are ~100 MB. Leaving them behind after a failure, which is
        # when they are least expected, is the case that matters.
        if not keep_tutorials:
            shutil.rmtree(work_dir, ignore_errors=True)

    return BuildResult(
        environment=environment,
        index_path=destination,
        library=library,
        case_count=len(cases),
        command_count=command_count,
        seconds=time.monotonic() - started,
    )
