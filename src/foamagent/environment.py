"""What OpenFOAM is actually installed.

Foam-Agent used to assume Foundation v10 everywhere: the ESI translator carried a
hand-written list of solvers ESI does not ship, and generation had no way to know which
solvers the target installation really has. Both are questions the installation can answer
about itself, so ask it instead of hard-coding the answer.

The probe runs through the execution backend, which means it reports on the OpenFOAM the
solver will actually run in -- including the one inside a container. When it cannot be run
at all, detection degrades to the Foundation v10 assumption that was previously unconditional.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, replace
from typing import Dict, Optional, Sequence, Tuple

from foamagent.execution import ExecutionBackend, get_execution_backend
from foamagent.logger import get_logger

logger = get_logger(__name__)

FOUNDATION = "foundation"
ESI = "esi"

# What Foam-Agent assumed before it could ask. Detection falls back to this so that a
# machine where the probe cannot run behaves as it did previously rather than failing.
FALLBACK_FORK = FOUNDATION
FALLBACK_VERSION = "10"

_PREFIX = "FOAMAGENT_PROBE_"
_SOLVERS_BEGIN = f"{_PREFIX}SOLVERS_BEGIN"
_SOLVERS_END = f"{_PREFIX}SOLVERS_END"

# Printed by a shell that has already sourced the OpenFOAM bashrc. Listing $FOAM_APPBIN is
# what turns "which solvers exist" from a guess into a fact.
PROBE_SCRIPT = f"""
echo "{_PREFIX}VERSION=${{WM_PROJECT_VERSION:-}}"
echo "{_PREFIX}API=${{WM_PROJECT_API:-}}"
echo "{_PREFIX}PROJECT_DIR=${{WM_PROJECT_DIR:-}}"
echo "{_PREFIX}TUTORIALS=${{FOAM_TUTORIALS:-}}"
echo "{_PREFIX}APPBIN=${{FOAM_APPBIN:-}}"
echo "{_SOLVERS_BEGIN}"
if [ -n "${{FOAM_APPBIN:-}}" ] && [ -d "${{FOAM_APPBIN}}" ]; then
  ls -1 "${{FOAM_APPBIN}}"
fi
echo "{_SOLVERS_END}"
""".strip()


@dataclass(frozen=True)
class OpenFOAMEnvironment:
    """The OpenFOAM installation Foam-Agent will run against."""

    fork: str = FALLBACK_FORK
    version: str = FALLBACK_VERSION
    # Everything in $FOAM_APPBIN: solvers and utilities alike, since OpenFOAM does not
    # separate them and callers ask about both.
    solvers: Tuple[str, ...] = ()
    tutorials: str = ""
    project_dir: str = ""
    # False when the probe could not be run and the fields above are the fallback.
    detected: bool = True

    @classmethod
    def fallback(cls, reason: str = "") -> "OpenFOAMEnvironment":
        if reason:
            logger.warning(
                "Could not detect the OpenFOAM environment (%s); assuming %s v%s.",
                reason,
                FALLBACK_FORK,
                FALLBACK_VERSION,
            )
        return cls(detected=False)

    @property
    def is_esi(self) -> bool:
        return self.fork == ESI

    def has_solver(self, name: str) -> bool:
        """Whether ``name`` exists in this installation.

        Answers None-safely for an undetected environment: with no measured list there is
        no evidence against any solver, so the answer is True and the caller proceeds as it
        did before detection existed.
        """
        if not self.solvers:
            return True
        return name in self.solvers

    def describe(self) -> str:
        suffix = "" if self.detected else " (assumed; detection failed)"
        return f"{self.fork} {self.version}, {len(self.solvers)} applications{suffix}"


def classify_fork(version: str, api: str = "") -> str:
    """Decide which OpenFOAM this is from the version strings it reports.

    ESI numbers its releases by year and month and exports WM_PROJECT_API alongside
    (v2406, API 2406); the Foundation numbers them sequentially and exports no API variable
    (10, 11, 12).
    """
    version = (version or "").strip()
    api = (api or "").strip()

    if api:
        return ESI
    if re.fullmatch(r"v\d+", version):
        return ESI
    if re.fullmatch(r"\d+", version):
        return FOUNDATION
    return FALLBACK_FORK


def parse_probe_output(text: str) -> Dict[str, object]:
    """Turn the probe's stdout into fields.

    Tolerates anything the bashrc printed before or after: only the prefixed lines and the
    block between the solver markers are read.
    """
    values: Dict[str, str] = {}
    solvers: list = []
    in_solvers = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == _SOLVERS_BEGIN:
            in_solvers = True
            continue
        if line == _SOLVERS_END:
            in_solvers = False
            continue
        if in_solvers:
            if line:
                solvers.append(line)
            continue
        if line.startswith(_PREFIX) and "=" in line:
            key, _, value = line[len(_PREFIX) :].partition("=")
            values[key] = value.strip()

    return {
        "version": values.get("VERSION", ""),
        "api": values.get("API", ""),
        "project_dir": values.get("PROJECT_DIR", ""),
        "tutorials": values.get("TUTORIALS", ""),
        "appbin": values.get("APPBIN", ""),
        "solvers": tuple(sorted(set(solvers))),
    }


def environment_from_probe(text: str) -> OpenFOAMEnvironment:
    """Build an environment from probe output, or the fallback if it says nothing."""
    parsed = parse_probe_output(text)
    version = str(parsed["version"])
    if not version:
        return OpenFOAMEnvironment.fallback("the probe reported no WM_PROJECT_VERSION")

    return OpenFOAMEnvironment(
        fork=classify_fork(version, str(parsed["api"])),
        version=version,
        solvers=parsed["solvers"],  # type: ignore[arg-type]
        tutorials=str(parsed["tutorials"]),
        project_dir=str(parsed["project_dir"]),
    )


_CACHE: Dict[str, OpenFOAMEnvironment] = {}


def _cache_key(backend: ExecutionBackend) -> str:
    # The backend says which installation it reaches; two objects pointing at the same one
    # share the result. Reading attributes off the object instead would key on identity for
    # the native backend, whose bashrc is a method, and probe once per caller.
    return backend.identity()


def detect_environment(
    backend: Optional[ExecutionBackend] = None,
    *,
    timeout: float = 120.0,
    use_cache: bool = True,
) -> OpenFOAMEnvironment:
    """Ask the OpenFOAM installation what it is.

    The result is cached per backend: the probe starts a container under the docker runtime,
    which is too slow to repeat for every generation step.
    """
    backend = backend or get_execution_backend()
    key = _cache_key(backend)

    if use_cache and key in _CACHE:
        return _CACHE[key]

    environment = _probe(backend, timeout=timeout)
    logger.info("Detected OpenFOAM environment: %s", environment.describe())

    if use_cache:
        _CACHE[key] = environment
    return environment


def _probe(backend: ExecutionBackend, *, timeout: float) -> OpenFOAMEnvironment:
    # A throwaway directory keeps the docker backend from mounting whatever happens to be
    # the current working directory just to read a few variables.
    try:
        with tempfile.TemporaryDirectory(prefix="foamagent-probe-") as work_dir:
            result = backend.run(["bash", "-c", PROBE_SCRIPT], work_dir, timeout=timeout)
    except Exception as exc:  # backend could not even start: no OpenFOAM, no docker, ...
        return OpenFOAMEnvironment.fallback(str(exc))

    if result.timed_out:
        return OpenFOAMEnvironment.fallback(f"the probe timed out after {timeout}s")
    if not result.ok:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        return OpenFOAMEnvironment.fallback(
            f"the probe exited with {result.returncode}: {detail[-1] if detail else 'no output'}"
        )

    return environment_from_probe(result.stdout)


def clear_environment_cache() -> None:
    """Forget detected environments. For tests and for switching runtime mid-process."""
    _CACHE.clear()


def set_environment(backend: ExecutionBackend, environment: OpenFOAMEnvironment) -> None:
    """Record an environment for a backend without probing. For tests."""
    _CACHE[_cache_key(backend)] = environment


def unavailable_solvers(
    environment: OpenFOAMEnvironment, candidates: Sequence[str]
) -> Tuple[str, ...]:
    """Return the candidates this installation does not provide."""
    return tuple(name for name in candidates if not environment.has_solver(name))


def environment_from_config(config) -> OpenFOAMEnvironment:
    """Detect the environment a Config points at.

    Normally the measurement decides. When the config pins a fork (FOAMAGENT_OPENFOAM_FORK),
    that setting wins instead: it is the user telling Foam-Agent which conventions to
    generate for, which is a separate question from which binaries are installed.
    """
    from foamagent.execution import backend_for_config

    environment = detect_environment(backend_for_config(config))

    pinned = getattr(config, "openfoam_fork", None)
    if pinned and environment.detected and pinned != environment.fork:
        logger.warning(
            "FOAMAGENT_OPENFOAM_FORK=%s but the installed OpenFOAM looks like %s %s. "
            "Generating for %s as configured.",
            pinned,
            environment.fork,
            environment.version,
            pinned,
        )
    if pinned:
        environment = replace(environment, fork=pinned)

    return environment


__all__ = [
    "ESI",
    "FOUNDATION",
    "OpenFOAMEnvironment",
    "PROBE_SCRIPT",
    "classify_fork",
    "clear_environment_cache",
    "detect_environment",
    "environment_from_config",
    "environment_from_probe",
    "parse_probe_output",
    "set_environment",
    "unavailable_solvers",
]
