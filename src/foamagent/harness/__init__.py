"""Wiring Foam-Agent into the AI harness the user already runs.

The point of host_delegate is that the reasoning happens in the harness, so the setup is
whatever that harness needs to (a) reach the MCP server and (b) know how to use OpenFOAM
well. Both are files, and writing them by hand is a step people get wrong once and then
abandon the tool over.

`foamagent install <harness>` writes them. What it writes differs per harness; what it
means does not.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from foamagent import settings as settings_module
from foamagent.config import skills_dir_setting
from foamagent.logger import get_logger

logger = get_logger(__name__)

SKILL_NAME = "openfoam-cfd"
SERVER_NAME = "foamagent"


@dataclass
class InstallResult:
    harness: str
    written: List[Path] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def describe(self) -> str:
        lines = [f"Configured {self.harness}:"]
        lines += [f"  {path}" for path in self.written]
        lines += [f"  note: {note}" for note in self.notes]
        return "\n".join(lines)


def skill_source() -> Path:
    """Where the packaged skill lives."""
    return Path(__file__).resolve().parent / "skill"


def server_command() -> Dict[str, object]:
    """How to start the MCP server, as MCP clients spell it.

    Prefers the installed console script; falls back to the interpreter running this code,
    which is what makes an editable checkout or a virtualenv work without PATH surgery.
    """
    executable = shutil.which("foamagent-mcp")
    if executable:
        return {"command": executable, "args": ["--transport", "stdio"]}
    return {
        "command": sys.executable,
        "args": ["-m", "foamagent.mcp.cli", "--transport", "stdio"],
    }


def _server_env() -> Dict[str, str]:
    """The environment settings a server needs that are not defaults.

    Only the OpenFOAM runtime: everything else has a working default, and copying the whole
    environment into a config file would put whatever key is set today into a file the user
    then commits.
    """
    keys = (
        "FOAMAGENT_OPENFOAM_RUNTIME",
        "FOAMAGENT_OPENFOAM_IMAGE",
        "FOAMAGENT_OPENFOAM_BASHRC",
        "FOAMAGENT_OPENFOAM_FORK",
        "WM_PROJECT_DIR",
    )
    return {key: os.environ[key] for key in keys if os.environ.get(key)}


def _write(path: Path, text: str, result: InstallResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    result.written.append(path)


def _merge_json(path: Path, update: Dict) -> Dict:
    """Read a config file, merge one key into it, keep everything else."""
    existing: Dict = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("%s is not valid JSON; writing a fresh one alongside it", path)
            existing = {}

    for key, value in update.items():
        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            existing[key].update(value)
        else:
            existing[key] = value
    return existing


def _copy_skill(destination: Path, result: InstallResult, source: Optional[Path] = None) -> None:
    source = source or skill_source()
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if item.is_file():
            target = destination / item.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            result.written.append(target)


def discover_supplemental_skills(
    resolved: Optional["settings_module.Settings"] = None,
) -> List[Tuple[str, Path]]:
    """User-supplied skills under `skills.dir`, sorted by name.

    A skill is a directory directly under `skills.dir` that contains a `SKILL.md`; anything
    else there is ignored. Empty when `skills.dir` is unset. Raises when it is set to
    something that is not a directory -- a deploy script wants a misconfigured path to fail
    loudly, not to silently install with no extra skills.
    """
    setting = skills_dir_setting(resolved)
    if setting.value is None:
        return []

    root = setting.value
    if not root.is_dir():
        raise ValueError(
            f"skills.dir={setting.value} (from {setting.source}) does not exist or is not "
            "a directory."
        )

    return sorted(
        (entry.name, entry)
        for entry in root.iterdir()
        if entry.is_dir() and (entry / "SKILL.md").is_file()
    )


def _copy_supplemental_skills(
    result: InstallResult,
    bundled_destination: Path,
    destination_for: Callable[[str], Path],
) -> List[Tuple[str, Path]]:
    """Copy every skill under `skills.dir`, after the bundled skill is already in place.

    A skill named the same as the bundled one (`openfoam-cfd`) lands at
    ``bundled_destination`` instead of ``destination_for``, replacing it -- an intentional
    channel for shipping an improved base skill.
    """
    resolved = settings_module.load()
    setting = skills_dir_setting(resolved)
    if setting.value is None:
        return []

    skills = discover_supplemental_skills(resolved)
    if not skills:
        result.notes.append(
            f"No skills found under {setting.value} (skills.dir, from {setting.source})."
        )
        return []

    for name, source in skills:
        destination = bundled_destination if name == SKILL_NAME else destination_for(name)
        _copy_skill(destination, result, source=source)
        replaced = " -- replaces the bundled skill" if name == SKILL_NAME else ""
        result.notes.append(f"Supplemental skill {name!r} copied from {source}{replaced}.")
    return skills


# ---------------------------------------------------------------------------
# Per-harness installers
# ---------------------------------------------------------------------------


def install_claude_code(root: Path) -> InstallResult:
    """Claude Code: an MCP entry in .mcp.json and a skill it loads on demand."""
    result = InstallResult(harness="Claude Code")

    server = dict(server_command())
    env = _server_env()
    if env:
        server["env"] = env

    config_path = root / ".mcp.json"
    merged = _merge_json(config_path, {"mcpServers": {SERVER_NAME: server}})
    _write(config_path, json.dumps(merged, indent=2) + "\n", result)

    bundled = root / ".claude" / "skills" / SKILL_NAME
    _copy_skill(bundled, result)
    _copy_supplemental_skills(result, bundled, lambda name: root / ".claude" / "skills" / name)

    result.notes.append(
        "Start Claude Code in this directory; it picks up .mcp.json on launch."
    )
    result.notes.append(
        "Ask for a simulation in plain words -- the skill loads when the request is CFD."
    )
    return result


def install_codex_cli(root: Path) -> InstallResult:
    """Codex CLI: a TOML server block, and instructions in AGENTS.md."""
    result = InstallResult(harness="Codex CLI")

    server = server_command()
    args = ", ".join(f'"{a}"' for a in server["args"])
    lines = [
        f"[mcp_servers.{SERVER_NAME}]",
        f'command = "{server["command"]}"',
        f"args = [{args}]",
    ]
    env = _server_env()
    if env:
        pairs = ", ".join(f'{k} = "{v}"' for k, v in env.items())
        lines.append(f"env = {{ {pairs} }}")

    _write(root / "foamagent-codex.toml", "\n".join(lines) + "\n", result)
    bundled = root / ".foamagent" / "skill"
    _copy_skill(bundled, result)
    copied = _copy_supplemental_skills(
        result, bundled, lambda name: root / ".foamagent" / "skills" / name
    )

    result.notes.append(
        "Append foamagent-codex.toml to ~/.codex/config.toml (Codex has no per-project "
        "MCP config)."
    )
    result.notes.append(
        f"Codex has no skill mechanism: point AGENTS.md at .foamagent/skill/SKILL.md."
    )
    if copied:
        result.notes.append(
            "Reference each supplemental skill's SKILL.md from AGENTS.md or your project "
            "instructions too."
        )
    return result


def install_generic_mcp(root: Path) -> InstallResult:
    """Cursor, Windsurf, Kilo Code, Cline and anything else reading mcpServers JSON."""
    result = InstallResult(harness="MCP client (generic)")

    server = dict(server_command())
    env = _server_env()
    if env:
        server["env"] = env

    _write(
        root / "foamagent-mcp.json",
        json.dumps({"mcpServers": {SERVER_NAME: server}}, indent=2) + "\n",
        result,
    )
    bundled = root / ".foamagent" / "skill"
    _copy_skill(bundled, result)
    copied = _copy_supplemental_skills(
        result, bundled, lambda name: root / ".foamagent" / "skills" / name
    )

    result.notes.append(
        "Merge foamagent-mcp.json into your client's MCP settings file "
        "(.cursor/mcp.json, cline_mcp_settings.json, ...)."
    )
    result.notes.append(
        "Give .foamagent/skill/SKILL.md to the agent as project instructions."
    )
    if copied:
        result.notes.append(
            "Give each supplemental skill's SKILL.md to the agent as project instructions too."
        )
    return result


HARNESSES: Dict[str, Callable[[Path], InstallResult]] = {
    "claude-code": install_claude_code,
    "codex-cli": install_codex_cli,
    "cursor": install_generic_mcp,
    "kilo-code": install_generic_mcp,
    "cline": install_generic_mcp,
    "generic": install_generic_mcp,
}


def install(harness: str, root: Optional[Path] = None) -> InstallResult:
    """Write the configuration for ``harness`` under ``root`` (default: here)."""
    installer = HARNESSES.get(harness)
    if installer is None:
        raise ValueError(
            f"Unknown harness {harness!r}. Known: {', '.join(sorted(HARNESSES))}."
        )
    return installer(Path(root or Path.cwd()).resolve())


__all__ = ["HARNESSES", "InstallResult", "SERVER_NAME", "SKILL_NAME", "discover_supplemental_skills",
           "install", "server_command", "skill_source"]
