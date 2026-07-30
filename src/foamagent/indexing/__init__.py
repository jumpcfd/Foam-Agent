"""Building and locating the reference library for a particular OpenFOAM installation.

Every installation carries its own tutorials, so the library is built from those: a
catalogue of every case, the cases themselves minus their mesh payloads, and the help text
of every application.

Built libraries live outside the repository, under ~/.cache/foamagent by default, one
directory per fork and version. There is no shipped fallback -- a library for somebody
else's OpenFOAM would describe cases this one does not have.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from foamagent.environment import OpenFOAMEnvironment
from foamagent.indexing.library import CATALOG_FILE, library_paths
from foamagent.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class IndexInfo:
    """A built library on disk."""

    name: str
    path: Path
    size_bytes: int
    has_library: bool = False

    def describe(self) -> str:
        contents = "library" if self.has_library else "empty"
        return f"{self.name}  [{contents}]  {self.size_bytes / 1e6:.1f} MB  {self.path}"


def index_root() -> Path:
    """Where built libraries are kept.

    Outside the repository on purpose: a built library is machine state, not source, and
    writing it into the checkout would put a rebuild in the way of every `git status`.
    """
    override = os.getenv("FOAMAGENT_INDEX_DIR")
    if override:
        return Path(override).expanduser().resolve()

    cache_home = os.getenv("XDG_CACHE_HOME")
    base = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return (base / "foamagent" / "indexes").resolve()


def index_name(environment: OpenFOAMEnvironment) -> str:
    """A directory name identifying the installation a library was built from."""
    version = environment.version.replace("/", "_") or "unknown"
    return f"{environment.fork}-{version}"


def index_dir(environment: OpenFOAMEnvironment) -> Path:
    return index_root() / index_name(environment)


def _directory_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def list_indexes() -> List[IndexInfo]:
    """Return every built library, in name order."""
    root = index_root()
    if not root.is_dir():
        return []

    found = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        found.append(
            IndexInfo(
                name=path.name,
                path=path,
                has_library=(path / CATALOG_FILE).is_file(),
                size_bytes=_directory_size(path),
            )
        )
    return found


def detected_environment() -> Optional[OpenFOAMEnvironment]:
    """The OpenFOAM installed here, or None when that cannot be established.

    Only used to locate the library built for it, so a failure here is not a failure of
    whatever the caller was doing -- it means no library is found.
    """
    try:
        from foamagent.environment import detect_environment

        environment = detect_environment()
    except Exception as exc:
        logger.debug("Could not detect the OpenFOAM environment: %s", exc)
        return None

    return environment if environment.detected else None


def resolve_library_dir(environment: Optional[OpenFOAMEnvironment] = None) -> Optional[Path]:
    """Return the reference library for this installation, or None when none is built."""
    if environment is None:
        environment = detected_environment()
    if environment is None:
        return None

    built = index_dir(environment)
    return built if (built / CATALOG_FILE).is_file() else None


__all__ = [
    "CATALOG_FILE",
    "IndexInfo",
    "detected_environment",
    "library_paths",
    "resolve_library_dir",
    "index_dir",
    "index_name",
    "index_root",
    "list_indexes",
]
