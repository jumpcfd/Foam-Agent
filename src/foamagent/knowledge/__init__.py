"""OpenFOAM know-how, kept apart from the harness how-to in `harness/skill/SKILL.md`.

Shipped as editable Markdown for the same reason as the review's prompt templates
(`review/templates.py`): a same-named file under the user's own directory wins over the
bundled one, so improving the advice is an edit, not a code change. `active_dir` is what
`describe_environment` points an agent at; `seed` is what `foamagent install` uses to put
an editable copy where the user can find it.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Dict

from foamagent.settings import config_home

if TYPE_CHECKING:
    from foamagent.harness import InstallResult

USER_DIRNAME = "knowledge"


def bundled_dir() -> Path:
    """Where the shipped knowledge files live."""
    return Path(__file__).resolve().parent


def user_dir() -> Path:
    """Where a user's own or seeded knowledge files override the bundled ones."""
    return config_home() / USER_DIRNAME


def active_dir() -> Path:
    """The directory an agent should read: the user's, once it holds anything.

    Falls back to the bundled directory so a server started without ever running
    `foamagent install` (a hand-written .mcp.json, say) still has knowledge to read.
    """
    directory = user_dir()
    if any(directory.glob("*.md")):
        return directory
    return bundled_dir()


def index(directory: Path) -> Dict[str, str]:
    """Map each `.md` file in `directory` to its first line, which doubles as its heading."""
    result: Dict[str, str] = {}
    for path in sorted(directory.glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        heading = lines[0].lstrip("#").strip() if lines else ""
        result[path.name] = heading or path.name
    return result


def seed(result: "InstallResult") -> None:
    """Copy each bundled knowledge file into the user's directory, skipping ones already there.

    Existing files -- the user's own edits -- are never touched; only a bundled file with no
    counterpart yet is added, the same rule `review/templates.py` uses for prompt templates.
    """
    destination = user_dir()
    destination.mkdir(parents=True, exist_ok=True)
    for source in sorted(bundled_dir().glob("*.md")):
        target = destination / source.name
        if target.exists():
            continue
        shutil.copy2(source, target)
        result.written.append(target)


__all__ = ["active_dir", "bundled_dir", "index", "seed", "user_dir"]
