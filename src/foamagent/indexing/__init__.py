"""Building and locating the search index for a particular OpenFOAM installation.

Foam-Agent ships one index, built from Foundation v10 tutorials. That is the right
reference for a Foundation v10 user and the wrong one for anybody else: an ESI user gets
retrieval hits for cases their OpenFOAM does not have, described with dictionary names it
does not use. Since every installation carries its own tutorials, the index can be built
from those instead.

Built indexes live outside the repository, under ~/.cache/foamagent by default, one
directory per fork and version. Lookup prefers a built index and falls back to the shipped
one, so nothing changes for a user who never builds anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from foamagent import paths
from foamagent.environment import OpenFOAMEnvironment
from foamagent.indexing.library import CATALOG_FILE, library_paths
from foamagent.logger import get_logger

logger = get_logger(__name__)

RAW_SUBDIR = "raw"
FAISS_SUBDIR = "faiss"
CASE_STATS_FILE = "openfoam_case_stats.json"


@dataclass(frozen=True)
class IndexInfo:
    """A built index on disk."""

    name: str
    path: Path
    has_corpus: bool
    has_faiss: bool
    size_bytes: int
    has_library: bool = False

    def describe(self) -> str:
        parts = []
        if self.has_library:
            parts.append("library")
        if self.has_corpus:
            parts.append("corpus")
        if self.has_faiss:
            parts.append("faiss")
        contents = "+".join(parts) if parts else "empty"
        return f"{self.name}  [{contents}]  {self.size_bytes / 1e6:.1f} MB  {self.path}"


def index_root() -> Path:
    """Where built indexes are kept.

    Outside the repository on purpose: a built index is machine state, not source, and
    writing it into database/ would put a several-hundred-megabyte rebuild in the way of
    every `git status`.
    """
    override = os.getenv("FOAMAGENT_INDEX_DIR")
    if override:
        return Path(override).expanduser().resolve()

    cache_home = os.getenv("XDG_CACHE_HOME")
    base = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return (base / "foamagent" / "indexes").resolve()


def index_name(environment: OpenFOAMEnvironment) -> str:
    """A directory name identifying the installation an index was built from."""
    version = environment.version.replace("/", "_") or "unknown"
    return f"{environment.fork}-{version}"


def index_dir(environment: OpenFOAMEnvironment) -> Path:
    return index_root() / index_name(environment)


def corpus_dir(environment: OpenFOAMEnvironment) -> Path:
    return index_dir(environment) / RAW_SUBDIR


def faiss_dir(environment: OpenFOAMEnvironment) -> Path:
    return index_dir(environment) / FAISS_SUBDIR


def _directory_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def list_indexes() -> List[IndexInfo]:
    """Return every built index, newest name order."""
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
                has_corpus=(path / RAW_SUBDIR).is_dir(),
                has_faiss=(path / FAISS_SUBDIR).is_dir(),
                has_library=(path / CATALOG_FILE).is_file(),
                size_bytes=_directory_size(path),
            )
        )
    return found


def resolve_corpus_dir(environment: Optional[OpenFOAMEnvironment] = None) -> Path:
    """Return the raw corpus to read: the built one when present, else the shipped one."""
    if environment is not None:
        built = corpus_dir(environment)
        if built.is_dir():
            return built
    return paths.database_dir() / RAW_SUBDIR


def resolve_faiss_base_dir(environment: Optional[OpenFOAMEnvironment] = None) -> Path:
    """Return the FAISS directory to read: the built one when present, else the shipped one."""
    if environment is not None:
        built = faiss_dir(environment)
        if built.is_dir():
            return built
    return paths.database_dir() / FAISS_SUBDIR


def detected_environment() -> Optional[OpenFOAMEnvironment]:
    """The OpenFOAM installed here, or None when that cannot be established.

    Only used to choose between a built index and the shipped one, so a failure here is not
    a failure of whatever the caller was doing -- it means the shipped index is used.
    """
    try:
        from foamagent.environment import detect_environment

        environment = detect_environment()
    except Exception as exc:
        logger.debug("Could not detect the OpenFOAM environment: %s", exc)
        return None

    return environment if environment.detected else None


def resolve_raw_dir() -> Path:
    """Return the corpus directory for the OpenFOAM installed here."""
    return resolve_corpus_dir(detected_environment())


def resolve_library_dir(environment: Optional[OpenFOAMEnvironment] = None) -> Optional[Path]:
    """Return the reference library for this installation, or None when none is built.

    There is no shipped fallback: the library is the installation's own tutorials, and a
    library for somebody else's OpenFOAM would describe cases this one does not have.
    """
    if environment is None:
        environment = detected_environment()
    if environment is None:
        return None

    built = index_dir(environment)
    return built if (built / CATALOG_FILE).is_file() else None


def case_stats_path() -> Path:
    """Return the case catalog (domains, categories, solvers) to plan against.

    It comes from the same index as the references do, so that the planner is offered the
    kinds of case the retrieved tutorials actually describe.
    """
    return resolve_raw_dir() / CASE_STATS_FILE


__all__ = [
    "CASE_STATS_FILE",
    "CATALOG_FILE",
    "FAISS_SUBDIR",
    "RAW_SUBDIR",
    "IndexInfo",
    "case_stats_path",
    "corpus_dir",
    "detected_environment",
    "library_paths",
    "resolve_library_dir",
    "resolve_raw_dir",
    "faiss_dir",
    "index_dir",
    "index_name",
    "index_root",
    "list_indexes",
    "resolve_corpus_dir",
    "resolve_faiss_base_dir",
]
