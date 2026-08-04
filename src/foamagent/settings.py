"""Where a setting comes from.

Foam-Agent had two ways of being configured: environment variables for the OpenFOAM
runtime and the index, a YAML file for the review. Which one a given setting used was
something you looked up rather than knew, and the environment half is lost when the shell
that set it closes -- which is why the installer bakes a snapshot of it into `.mcp.json`,
and why that snapshot then goes stale.

This module is the one place a setting is resolved from. Four sources, highest first:

1. the environment variable, when the setting has one
2. the project settings file, found by searching upward from the working directory
3. the user settings file, ``~/.config/foamagent/config.yaml``
4. the default compiled into the code

The environment stays on top so that everything already written into a `.mcp.json`, a CI
job or a benchmark script keeps working. The project file is what makes a setting travel
with the directory it belongs to, so a case that needs a particular OpenFOAM image says so
next to the case instead of in whoever's shell happens to start the server.

Every resolved value carries where it came from, because a setting whose origin cannot be
seen is one that gets set twice in two places and read from the wrong one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from foamagent.logger import get_logger

logger = get_logger(__name__)

CONFIG_FILENAME = "config.yaml"
TEMPLATES_DIRNAME = "templates"

# Searched for in the working directory and its parents, in this order within a directory.
PROJECT_FILENAMES: Tuple[str, ...] = (
    "foamagent.yaml",
    "foamagent.yml",
    os.path.join(".foamagent", "config.yaml"),
)

DEFAULT = "default"


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def config_home() -> Path:
    """The directory holding Foam-Agent's user settings and templates."""
    override = os.getenv("FOAMAGENT_CONFIG_HOME")
    if override and override.strip():
        return Path(override.strip()).expanduser()

    xdg = os.getenv("XDG_CONFIG_HOME")
    base = Path(xdg.strip()).expanduser() if xdg and xdg.strip() else Path.home() / ".config"
    return base / "foamagent"


def config_file() -> Path:
    """The user settings file. ``FOAMAGENT_CONFIG_FILE`` names another one outright."""
    override = os.getenv("FOAMAGENT_CONFIG_FILE")
    if override and override.strip():
        return Path(override.strip()).expanduser()
    return config_home() / CONFIG_FILENAME


def templates_dir() -> Path:
    """Where a user's own prompt templates override the packaged ones."""
    override = os.getenv("FOAMAGENT_TEMPLATES_DIR")
    if override and override.strip():
        return Path(override.strip()).expanduser()
    return config_home() / TEMPLATES_DIRNAME


def project_config_file(start: Optional[Path] = None) -> Optional[Path]:
    """The project settings file in effect here, or None when there is none.

    Searched for from ``start`` (the working directory by default) upwards, so that a
    server started in a subdirectory of a project still finds it. The search stops at the
    first file found; a directory holding a `.git` ends the search after it is examined,
    because a settings file above a repository belongs to something else.

    ``FOAMAGENT_PROJECT_CONFIG`` names a file outright, and naming one that does not exist
    is how a test or a benchmark says "no project file".
    """
    override = os.getenv("FOAMAGENT_PROJECT_CONFIG")
    if override is not None:
        if not override.strip():
            return None
        path = Path(override.strip()).expanduser()
        return path if path.is_file() else None

    try:
        here = (start or Path.cwd()).resolve()
    except OSError:
        return None

    for directory in [here, *here.parents]:
        for name in PROJECT_FILENAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        if (directory / ".git").exists():
            return None
    return None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_yaml(path: Path) -> Dict[str, Any]:
    """Parse one settings file, reporting rather than raising when it cannot be read.

    A stray tab in a settings file stops that file from being used, not the server from
    running: the alternative is a machine that cannot review a case because of a typo.
    """
    if not path.is_file():
        return {}
    try:
        import yaml

        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # yaml.YAMLError, OSError, ImportError
        logger.warning("Could not read %s (%s); ignoring it.", path, exc)
        return {}

    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        logger.warning("%s does not contain a mapping; ignoring it.", path)
        return {}
    return parsed


def _merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay wins, except that two mappings under the same key are merged."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _lookup(data: Dict[str, Any], dotted: str) -> Tuple[bool, Any]:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


@dataclass(frozen=True)
class Setting:
    """One resolved value, and where it came from."""

    key: str
    value: Any
    source: str

    @property
    def is_default(self) -> bool:
        return self.source == DEFAULT


@dataclass(frozen=True)
class Settings:
    """The settings files in effect, merged, with each file remembered separately."""

    documents: Tuple[Tuple[str, Path, Dict[str, Any]], ...] = ()

    @property
    def data(self) -> Dict[str, Any]:
        """Every file merged together, the highest-priority file winning."""
        merged: Dict[str, Any] = {}
        for _, _, document in reversed(self.documents):
            merged = _merge(merged, document)
        return merged

    @property
    def files(self) -> List[Path]:
        return [path for _, path, _ in self.documents]

    def section(self, name: str) -> Dict[str, Any]:
        """One top-level section of the merged settings, or an empty mapping."""
        found, value = _lookup(self.data, name)
        if not found:
            return {}
        if not isinstance(value, dict):
            logger.warning("The %r section of the settings is not a mapping; ignoring it.", name)
            return {}
        return value

    # -- resolution ---------------------------------------------------------

    def _from_files(self, dotted: str) -> Optional[Tuple[Any, str]]:
        for label, path, document in self.documents:
            found, value = _lookup(document, dotted)
            if found:
                return value, f"{label} ({path})"
        return None

    def resolve(self, dotted: str, *, env: Optional[str] = None, default: Any = None) -> Setting:
        """The value in effect for one setting, with its origin."""
        if env:
            raw = os.getenv(env)
            if raw is not None and raw.strip():
                return Setting(dotted, raw.strip(), f"env {env}")

        found = self._from_files(dotted)
        if found is not None:
            return Setting(dotted, found[0], found[1])
        return Setting(dotted, default, DEFAULT)

    def text(
        self,
        dotted: str,
        *,
        env: Optional[str] = None,
        default: str = "",
        choices: Optional[Sequence[str]] = None,
        lower: bool = False,
    ) -> Setting:
        """A string setting. A value outside ``choices`` is reported and then ignored."""
        setting = self.resolve(dotted, env=env, default=default)
        if setting.value is None:
            return Setting(dotted, default, DEFAULT)

        value = str(setting.value).strip()
        if lower:
            value = value.lower()

        if choices is not None and value and value not in choices:
            logger.warning(
                "%s=%r (from %s) is not one of %s; using %r.",
                dotted, value, setting.source, ", ".join(choices), default,
            )
            return Setting(dotted, default, DEFAULT)
        return Setting(dotted, value, setting.source)

    def integer(self, dotted: str, *, env: Optional[str] = None, default: int = 0) -> Setting:
        """An integer setting. A value that is not a number is reported and then ignored."""
        setting = self.resolve(dotted, env=env, default=default)
        try:
            return Setting(dotted, int(setting.value), setting.source)
        except (TypeError, ValueError):
            logger.warning(
                "%s=%r (from %s) is not a number; using %s.",
                dotted, setting.value, setting.source, default,
            )
            return Setting(dotted, default, DEFAULT)

    def path(self, dotted: str, *, env: Optional[str] = None, default: Optional[Path] = None) -> Setting:
        """A filesystem path, with ``~`` expanded."""
        setting = self.resolve(dotted, env=env, default=default)
        if setting.value in (None, ""):
            return Setting(dotted, default, DEFAULT)
        return Setting(dotted, Path(str(setting.value)).expanduser(), setting.source)


def load(start: Optional[Path] = None) -> Settings:
    """Read the settings files in effect, highest priority first.

    Not cached: the files are two small YAML documents, and a cache would mean a setting
    changed while a long-running server is up takes effect for some callers and not others.
    """
    documents: List[Tuple[str, Path, Dict[str, Any]]] = []

    project = project_config_file(start)
    if project is not None:
        documents.append(("project settings", project, read_yaml(project)))

    user = config_file()
    if user.is_file():
        documents.append(("user settings", user, read_yaml(user)))

    return Settings(documents=tuple(documents))


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def set_value(path: Path, dotted: str, value: Any) -> None:
    """Write one setting into ``path``, keeping everything else in the file.

    Rewriting the file loses its comments, which is the price of being able to change a
    setting without opening an editor. ``foamagent config edit`` is there for anyone who
    wants their comments kept.
    """
    data = read_yaml(path)
    parts = dotted.split(".")

    current = data
    for part in parts[:-1]:
        existing = current.get(part)
        if not isinstance(existing, dict):
            existing = {}
            current[part] = existing
        current = existing
    current[parts[-1]] = value

    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def unset_value(path: Path, dotted: str) -> bool:
    """Remove one setting from ``path``. Returns whether it was there."""
    data = read_yaml(path)
    parts = dotted.split(".")

    current = data
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            return False
        current = nxt
    if parts[-1] not in current:
        return False
    del current[parts[-1]]

    import yaml

    path.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return True


def known_keys() -> Iterable[str]:
    """Every dotted key the code reads, for completion and for ``config show``."""
    from foamagent.config import CONFIG_KEYS
    from foamagent.review.settings import REVIEW_KEYS

    return [*CONFIG_KEYS, *REVIEW_KEYS]


__all__ = [
    "CONFIG_FILENAME",
    "DEFAULT",
    "PROJECT_FILENAMES",
    "Setting",
    "Settings",
    "config_file",
    "config_home",
    "known_keys",
    "load",
    "project_config_file",
    "set_value",
    "templates_dir",
    "unset_value",
]
