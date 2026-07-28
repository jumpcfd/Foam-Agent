"""Where OpenFOAM commands actually run.

Foam-Agent invokes OpenFOAM in two quite different ways: as executables on this machine
inside a sourced OpenFOAM environment, or inside a container image. The difference used to
be an `if runtime == "docker"` branch buried in the function that runs the Allrun script,
while the other OpenFOAM calls -- gmshToFoam, checkMesh -- went straight to subprocess and
so silently ignored the container setting.

This module holds that choice in one place. A backend knows how to turn a command into the
argv that runs it, how to run it, and how to stop it when it overruns; everything else calls
`get_execution_backend().run(...)` and does not care which one it got.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional, Sequence

from foamagent.logger import get_logger

logger = get_logger(__name__)

DEFAULT_IMAGE = "foam-bench:latest"
DEFAULT_IMAGE_BASHRC = "/opt/openfoam10/etc/bashrc"


class OpenFOAMEnvironmentError(RuntimeError):
    """Raised when no OpenFOAM environment can be reached at all."""


@dataclass(frozen=True)
class ExecutionPlan:
    """What a backend decided to run, before it is run."""

    argv: List[str]
    working_dir: str
    # Set only for container runs. Killing the docker client leaves the container running,
    # so the name is needed to stop it when a run overruns its time limit.
    container_name: Optional[str] = None


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class ExecutionBackend(ABC):
    """A place OpenFOAM commands can be run."""

    name: ClassVar[str]

    @abstractmethod
    def plan(self, command: Sequence[str], working_dir: str) -> ExecutionPlan:
        """Return the argv that runs ``command`` in an OpenFOAM environment."""

    def identity(self) -> str:
        """What OpenFOAM this backend reaches, as a string.

        Two backends with the same identity reach the same installation, so anything
        measured through one holds for the other. Callers that cache such measurements key
        on this rather than on the object.
        """
        return self.name

    def run(
        self,
        command: Sequence[str],
        working_dir: str,
        *,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        """Run ``command`` and collect its output.

        Never raises on a non-zero exit or a timeout: both are outcomes the callers report
        back to the model, so they are returned rather than thrown.
        """
        plan = self.plan(command, working_dir)
        logger.debug("Running %s via %s backend", plan.argv, self.name)

        process = subprocess.Popen(
            plan.argv,
            cwd=plan.working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return CommandResult(process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            self.terminate(plan, process)
            stdout, stderr = process.communicate()
            return CommandResult(
                returncode=process.returncode if process.returncode is not None else -signal.SIGKILL,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
            )

    def run_checked(
        self,
        command: Sequence[str],
        working_dir: str,
        *,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        """Run ``command``, raising CalledProcessError if it fails.

        For callers that already handle CalledProcessError, which is what running these
        commands through subprocess directly used to give them.
        """
        result = self.run(command, working_dir, timeout=timeout)
        if not result.ok:
            raise subprocess.CalledProcessError(
                result.returncode, list(command), output=result.stdout, stderr=result.stderr
            )
        return result

    def terminate(self, plan: ExecutionPlan, process: subprocess.Popen) -> None:
        """Stop an overrunning run. Backends that leave work behind override this."""
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


class NativeBackend(ExecutionBackend):
    """Run on this machine, inside the OpenFOAM environment named by WM_PROJECT_DIR."""

    name = "native"

    def __init__(self, project_dir: Optional[str] = None):
        self._project_dir = project_dir

    def identity(self) -> str:
        # Read here rather than in __init__ so that a backend built before the environment
        # was sourced still reports the installation it will actually use.
        return f"{self.name}:{self._project_dir or os.getenv('WM_PROJECT_DIR') or ''}"

    def bashrc(self) -> str:
        project_dir = self._project_dir or os.getenv("WM_PROJECT_DIR")
        if not project_dir:
            raise OpenFOAMEnvironmentError(
                "WM_PROJECT_DIR is not set. Please source OpenFOAM environment before running Foam-Agent "
                "(e.g., source env/common.sh and env/foamagent.sh), or set "
                "FOAMAGENT_OPENFOAM_RUNTIME=docker to run OpenFOAM in a container."
            )

        bashrc_path = os.path.join(project_dir, "etc", "bashrc")
        if not os.path.exists(bashrc_path):
            raise OpenFOAMEnvironmentError(f"OpenFOAM bashrc not found at: {bashrc_path}")
        return bashrc_path

    def plan(self, command: Sequence[str], working_dir: str) -> ExecutionPlan:
        inner = f"source {self.bashrc()} && {shlex.join(command)}"
        return ExecutionPlan(
            argv=["bash", "-c", inner],
            working_dir=os.path.abspath(working_dir),
        )


class DockerBackend(ExecutionBackend):
    """Run inside a container image that already carries OpenFOAM.

    The working directory is mounted at the same absolute path it has on the host, so paths
    printed into the logs mean the same thing on both sides. The container runs as the
    invoking user so that the files it writes are not left owned by root.
    """

    name = "docker"

    def __init__(self, image: Optional[str] = None, bashrc: Optional[str] = None):
        self.image = (image or os.getenv("FOAMAGENT_OPENFOAM_IMAGE") or DEFAULT_IMAGE).strip()
        self.bashrc = (
            bashrc or os.getenv("FOAMAGENT_OPENFOAM_BASHRC") or DEFAULT_IMAGE_BASHRC
        ).strip()

    def identity(self) -> str:
        return f"{self.name}:{self.image}:{self.bashrc}"

    def _container_name(self) -> str:
        return f"foamagent-run-{os.getpid()}-{int(time.time())}"

    def plan(self, command: Sequence[str], working_dir: str) -> ExecutionPlan:
        abs_work_dir = os.path.abspath(working_dir)
        container_name = self._container_name()
        inner = f"source {self.bashrc} && {shlex.join(command)}"
        argv = [
            "docker", "run", "--rm",
            "--name", container_name,
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-e", "HOME=/tmp",
            "-v", f"{abs_work_dir}:{abs_work_dir}",
            "-w", abs_work_dir,
            "--entrypoint", "bash",
            self.image, "-c", inner,
        ]
        return ExecutionPlan(argv=argv, working_dir=abs_work_dir, container_name=container_name)

    def terminate(self, plan: ExecutionPlan, process: subprocess.Popen) -> None:
        if plan.container_name:
            subprocess.run(
                ["docker", "kill", plan.container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        super().terminate(plan, process)


_BACKENDS: Dict[str, type] = {
    NativeBackend.name: NativeBackend,
    DockerBackend.name: DockerBackend,
}


def get_execution_backend(runtime: Optional[str] = None) -> ExecutionBackend:
    """Return the backend for ``runtime``, or for FOAMAGENT_OPENFOAM_RUNTIME when omitted.

    An unrecognised value falls back to native, matching how the runtime setting behaved
    before this module existed.
    """
    if runtime is None:
        runtime = os.getenv("FOAMAGENT_OPENFOAM_RUNTIME") or NativeBackend.name

    key = runtime.strip().lower()
    backend_class = _BACKENDS.get(key)
    if backend_class is None:
        logger.warning(
            "Unknown OpenFOAM runtime %r; falling back to %s.", runtime, NativeBackend.name
        )
        backend_class = NativeBackend

    return backend_class()


def backend_for_config(config) -> ExecutionBackend:
    """Return the backend a Config asks for."""
    runtime = getattr(config, "openfoam_runtime", None)
    if runtime == DockerBackend.name:
        return DockerBackend(
            image=getattr(config, "openfoam_image", None),
            bashrc=getattr(config, "openfoam_bashrc", None),
        )
    return get_execution_backend(runtime)
