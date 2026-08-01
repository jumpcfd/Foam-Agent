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
from typing import Callable, Dict, List, Optional

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


def _copy_skill(destination: Path, result: InstallResult) -> None:
    source = skill_source()
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if item.is_file():
            target = destination / item.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            result.written.append(target)


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

    _copy_skill(root / ".claude" / "skills" / SKILL_NAME, result)

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
    _copy_skill(root / ".foamagent" / "skill", result)

    result.notes.append(
        "Append foamagent-codex.toml to ~/.codex/config.toml (Codex has no per-project "
        "MCP config)."
    )
    result.notes.append(
        f"Codex has no skill mechanism: point AGENTS.md at .foamagent/skill/SKILL.md."
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
    _copy_skill(root / ".foamagent" / "skill", result)

    result.notes.append(
        "Merge foamagent-mcp.json into your client's MCP settings file "
        "(.cursor/mcp.json, cline_mcp_settings.json, ...)."
    )
    result.notes.append(
        "Give .foamagent/skill/SKILL.md to the agent as project instructions."
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


__all__ = ["HARNESSES", "InstallResult", "SERVER_NAME", "SKILL_NAME", "install",
           "server_command", "skill_source"]
