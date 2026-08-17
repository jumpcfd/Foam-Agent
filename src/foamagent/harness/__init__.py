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
import subprocess
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


def _hermes_home() -> Path:
    """Hermes's own per-user state directory: $HERMES_HOME, or its default ~/.hermes."""
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


# The category folder a skill is filed under in Hermes's global skills/ directory. Hermes
# scans skills/<category>/<name>/SKILL.md, not a flat skills/<name>/ -- confirmed against a
# live install, whose ~/.hermes/skills/ held nothing but category folders.
HERMES_SKILL_CATEGORY = "cfd"


def install_hermes_agent(root: Path) -> InstallResult:
    """Hermes Agent: a YAML server block, and skills installed where Hermes actually finds them.

    Like Codex, Hermes has no per-project MCP config -- the server block has to be merged
    into ~/.hermes/config.yaml's top-level mcp_servers: key by hand. Unlike Codex, its global
    skills/ directory is one level deeper: a category folder sits between skills/ and the
    skill itself. Confirmed by a live Hermes session running a real case end to end through
    a skill installed exactly this way (mirrored by hand before this installer existed).
    """
    result = InstallResult(harness="Hermes Agent")

    server = server_command()
    lines = [
        "mcp_servers:",
        f"  {SERVER_NAME}:",
        f'    command: "{server["command"]}"',
        "    args:",
    ]
    lines += [f'      - "{arg}"' for arg in server["args"]]
    env = _server_env()
    if env:
        lines.append("    env:")
        lines += [f'      {key}: "{value}"' for key, value in env.items()]
    lines.append("    enabled: true")

    _write(root / "foamagent-hermes.yaml", "\n".join(lines) + "\n", result)

    skills_root = _hermes_home() / "skills" / HERMES_SKILL_CATEGORY
    bundled = skills_root / SKILL_NAME
    _copy_skill(bundled, result)
    copied = _copy_supplemental_skills(result, bundled, lambda name: skills_root / name)

    result.notes.append(
        "Merge foamagent-hermes.yaml's mcp_servers entry into ~/.hermes/config.yaml "
        "(Hermes has no per-project MCP config), or run "
        f"'hermes mcp add {SERVER_NAME} --command ... --args ...' with the same values."
    )
    result.notes.append(
        f"Skill installed into {bundled} -- Hermes loads it from a category folder under "
        "skills/, not a flat skills/<name>/."
    )
    if copied:
        result.notes.append("Supplemental skills installed the same way, no wiring needed.")
    return result


HARNESSES: Dict[str, Callable[[Path], InstallResult]] = {
    "claude-code": install_claude_code,
    "hermes-agent": install_hermes_agent,
}


# ---------------------------------------------------------------------------
# Hermes as the review command
# ---------------------------------------------------------------------------

HERMES_REVIEW_PROFILE = "foamagent-review"

# Everything a review does not need, disabled on the profile itself as defense in depth on
# top of the hermes-agent review profile's own per-invocation `--toolsets file,web` -- see
# review/settings.py for why that alone was not trusted without this. Kept as one list here
# instead of only in README so the two cannot drift apart.
HERMES_REVIEW_DISABLED_TOOLSETS: List[str] = [
    "terminal", "code_execution", "browser", "video", "video_gen", "x_search",
    "stt", "homeassistant", "spotify", "yuanbao", "computer_use", "image_gen",
    "bfl", "tts", "vision",
]


class HermesNotFound(RuntimeError):
    """`hermes` is not on PATH."""


def _hermes(*args: str, profile: Optional[str] = None) -> "subprocess.CompletedProcess[str]":
    hermes = shutil.which("hermes")
    if hermes is None:
        raise HermesNotFound(
            "hermes is not on PATH -- install Hermes Agent first (https://hermesagent.ai)."
        )
    argv = [hermes, *(["-p", profile] if profile is not None else []), *args]
    return subprocess.run(argv, capture_output=True, text=True)


def setup_hermes_review(profile: str = HERMES_REVIEW_PROFILE) -> InstallResult:
    """One-time setup for an isolated Hermes profile safe to use as `review.command`.

    This is the exact command sequence README's "Setting up Hermes Agent as the review
    command" documents by hand, run here instead -- Hermes's own state is not a file
    Foam-Agent can just write (`hermes profile create` and its siblings are the only
    supported way to reach it), so this shells out to `hermes` rather than following the
    write-a-file pattern every other installer in this module uses. That is a deliberate
    exception, not a precedent for touching a harness's *shared* config the way this module
    otherwise refuses to (see `install_codex_cli`/`install_hermes_agent` above): every step
    below only ever creates or edits ``profile``'s own isolated directory, never the user's
    main Hermes profile.

    Every step but the profile creation itself was confirmed empirically to be idempotent
    (re-running `tools disable`, `config set`, or `profile alias` on an already-configured
    profile just reprints success), so this is safe to call again on an already set-up
    profile -- ``foamagent install hermes-agent --with-review`` twice does not double up
    anything or fail the second time.
    """
    result = InstallResult(harness="Hermes Agent (review)")

    if _hermes("profile", "show", profile).returncode == 0:
        result.notes.append(f"Reusing the existing Hermes profile {profile!r}.")
    else:
        created = _hermes("profile", "create", profile, "--no-skills")
        if created.returncode != 0:
            raise RuntimeError(
                f"hermes profile create {profile} failed: {created.stderr.strip() or created.stdout.strip()}"
            )
        result.notes.append(f"Created an isolated Hermes profile: {profile!r}.")

    _hermes("profile", "alias", profile)
    alias_path = shutil.which(profile)
    if alias_path:
        result.written.append(Path(alias_path))

    # terminal.backend was set to "docker" here in an earlier version of this function, on
    # the theory that it would sandbox the terminal toolset the same way Claude Code's own
    # review sandbox does. It does not: the terminal toolset is disabled below regardless
    # (nothing to sandbox), and "docker" turned out to also reroute the *file* toolset's
    # reads through a container-mounted /workspace -- which, in a real run, silently
    # returned an empty directory for a case that had real files on the host (confirmed on
    # WSL2; a stale/unreliable bind mount, not a Foam-Agent bug). "host" is Hermes's own
    # default; setting it explicitly here just guards against a profile created from a
    # global config where it had already been changed.
    _hermes("config", "set", "terminal.backend", "host", profile=profile)

    _hermes("tools", "disable", *HERMES_REVIEW_DISABLED_TOOLSETS, profile=profile)
    result.notes.append(f"Disabled every toolset {profile!r} does not need for a review.")

    default_model = _hermes("config", "get", "model.default").stdout.strip()
    default_provider = _hermes("config", "get", "model.provider").stdout.strip()
    if default_model:
        _hermes("config", "set", "model.default", default_model, profile=profile)
    if default_provider:
        _hermes("config", "set", "model.provider", default_provider, profile=profile)
    if default_model:
        result.notes.append(f"Model: {default_model} (copied from your default Hermes profile).")
    else:
        result.notes.append(
            f"Your default Hermes profile has no model configured to copy -- run "
            f"'hermes -p {profile} setup' before using this for review."
        )

    settings_module.set_value(settings_module.config_file(), "review.harness", "hermes-agent")
    result.notes.append("review.harness set to hermes-agent (in Foam-Agent's own settings).")

    return result


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
