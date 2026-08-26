"""OpenFOAM know-how, kept apart from the harness how-to in `harness/skill/SKILL.md`.

`user_dir` -- `~/.config/foamagent/knowledge/` by default -- is where this advice actually
lives, the same way `review/templates.py`'s prompt templates live under
`~/.config/foamagent/templates/`. `bundled_dir` (this package's own `.md` files) is only the
default content `seed` copies in the first time `user_dir` is empty; once it holds anything,
edit it there. `seed` is called eagerly -- every CLI invocation and MCP server start, not just
`foamagent init` -- so a fresh install has an editable copy without any extra step; it is
idempotent (only ever adds a missing file) so calling it repeatedly costs nothing. `active_dir`
is what `describe_environment` points an agent at, and falls back to `bundled_dir` only for a
server started before `seed` has ever run (e.g. a hand-written `.mcp.json`, or a test that
calls it directly).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

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
    `foamagent init` (a hand-written .mcp.json, say) still has knowledge to read.
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


def seed(result: Optional["InstallResult"] = None) -> None:
    """Copy each bundled knowledge file into the user's directory, skipping ones already there.

    Existing files -- the user's own edits -- are never touched; only a bundled file with no
    counterpart yet is added, the same rule `review/templates.py` uses for prompt templates.
    Cheap and side-effect-free once `user_dir` is populated, which is what makes it safe to
    call on every CLI invocation and MCP server start rather than only from `foamagent init`.
    `result` is only for `install`'s own reporting; omit it when calling this eagerly.
    """
    destination = user_dir()
    destination.mkdir(parents=True, exist_ok=True)
    for source in sorted(bundled_dir().glob("*.md")):
        target = destination / source.name
        if target.exists():
            continue
        shutil.copy2(source, target)
        if result is not None:
            result.written.append(target)


__all__ = ["active_dir", "bundled_dir", "index", "seed", "user_dir"]
