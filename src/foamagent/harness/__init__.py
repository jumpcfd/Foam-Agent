"""Wiring Foam-Agent into the AI harness the user already runs.

The point of host_delegate is that the reasoning happens in the harness, so the setup is
whatever that harness needs to (a) reach the MCP server and (b) know how to use OpenFOAM
well. Both are files, and writing them by hand is a step people get wrong once and then
abandon the tool over.

`foamagent init <harness>` writes them. What it writes differs per harness; what it
means does not.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from foamagent import knowledge, settings as settings_module
from foamagent.logger import get_logger
from foamagent.review.settings import DEFAULT_TIMEOUT_SECONDS as REVIEW_TIMEOUT_SECONDS

logger = get_logger(__name__)

SKILL_NAME = "openfoam-cfd"
SERVER_NAME = "foamagent"
PARAVIEW_SERVER_NAME = "paraview"


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


def paraview_integration() -> Optional[Tuple[Dict[str, object], Path]]:
    """The paraview_mcp server block and its skill's source, or None if unconfigured.

    paraview_mcp (github.com/jumpcfd/paraview_mcp) is a separate project this one does not
    vendor -- it needs ParaView itself, which is not this project's business to install.
    Once `paraview.dir` (or FOAMAGENT_PARAVIEW_MCP_DIR) names a checkout, every installer
    below wires it in next to the `foamagent` server, and `review.channel.sandbox_config`
    hands it to the Reviewer and Judge too: an independent check that can only read text and
    run arithmetic misses what a screenshot or a field probe would catch immediately.
    """
    from foamagent.config import paraview_dir_setting

    setting = paraview_dir_setting()
    if setting.value is None:
        return None
    if not setting.value.is_dir():
        raise ValueError(
            f"paraview.dir={setting.value} (from {setting.source}) does not exist or is not "
            "a directory."
        )
    server: Dict[str, object] = {
        "command": "uv",
        "args": ["run", "--directory", str(setting.value), "paraview-mcp"],
    }
    return server, setting.value / "skills" / PARAVIEW_SERVER_NAME


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


# ponytail: matches a bare `git commit`; `git -C x commit` or `sh -c` slip past. A brake on
# habit, not a defence against intent -- tighten with a PreToolUse hook if that ever matters.
GIT_COMMIT_DENY = "Bash(git commit:*)"

# Files Claude Code itself drops under .claude/ that are machine- or session-specific --
# settings.local.json holds local MCP-trust approvals, by Claude Code's own convention never
# committed; lock files (e.g. a scheduled-task session lock) are per-run state. Without this,
# the task ledger's Stop hook forces them into a commit the moment they appear, since it
# refuses to end a turn with untracked changes -- confirmed against a real project where that
# happened.
CLAUDE_CODE_GITIGNORE_LINES = (".claude/settings.local.json", ".claude/*.lock")


def _ensure_gitignored(root: Path, lines: Tuple[str, ...], result: InstallResult) -> None:
    """Add each of `lines` to root/.gitignore, skipping ones already present verbatim.

    Idempotent -- a second `init` never duplicates a line -- and additive: an existing
    .gitignore (its own content unrelated to Foam-Agent) is appended to, never replaced.
    """
    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    missing = [line for line in lines if line not in existing.splitlines()]
    if not missing:
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with gitignore.open("a", encoding="utf-8") as f:
        f.write(prefix + "\n".join(missing) + "\n")
    result.written.append(gitignore)
    result.notes.append(
        f"Added {', '.join(missing)} to {gitignore} -- machine-specific, never meant to be "
        "committed."
    )


def _hook_command(subcommand: str) -> str:
    """`foamagent tasks <subcommand>`, spelled so the hook shell finds it (cf. server_command)."""
    executable = shutil.which("foamagent")
    if executable:
        return f"{shlex.quote(executable)} tasks {subcommand}"
    return f"{shlex.quote(sys.executable)} -m foamagent.cli tasks {subcommand}"


def _is_task_hook(entry: Dict) -> bool:
    return any(
        "foamagent" in str(hook.get("command", "")) and " tasks " in str(hook.get("command", ""))
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    )


def claude_settings(existing: Dict) -> Dict:
    """Add the task-ledger hooks and the git-commit deny to a .claude/settings.json.

    Everything else in the file is kept. Our own entries from an earlier install are
    replaced (the executable path may have moved); other people's hooks stay.

    The three together are what makes the ledger get used rather than ignored: the
    SessionStart hook puts the ledger in front of the agent at startup and again after every
    context compaction; the Stop hook sends it back once when it tries to finish a turn with
    uncommitted work; the deny leaves task_done as the only way to commit. The user's own
    git commit at the terminal is unaffected.
    """
    wanted = {
        "SessionStart": {
            "matcher": "startup|resume|compact",
            "hooks": [{"type": "command", "command": _hook_command("status")}],
        },
        "Stop": {"hooks": [{"type": "command", "command": _hook_command("stop-check")}]},
    }
    hooks = existing.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = existing["hooks"] = {}
    for event, entry in wanted.items():
        entries = hooks.get(event)
        if not isinstance(entries, list):
            entries = hooks[event] = []
        entries[:] = [e for e in entries if not (isinstance(e, dict) and _is_task_hook(e))] + [entry]

    permissions = existing.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        permissions = existing["permissions"] = {}
    deny = permissions.get("deny")
    if not isinstance(deny, list):
        deny = permissions["deny"] = []
    if GIT_COMMIT_DENY not in deny:
        deny.append(GIT_COMMIT_DENY)
    return existing


def copy_skill(destination: Path, result: InstallResult, source: Optional[Path] = None) -> None:
    source = source or skill_source()
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if item.is_file():
            target = destination / item.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            result.written.append(target)


def skill_version(path: Path) -> Optional[str]:
    """The `version:` field from a SKILL.md's frontmatter, or None if the file has none."""
    import yaml

    _, frontmatter, _ = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(frontmatter).get("version")


def skill_destination(harness: str, root: Path) -> Path:
    """Where `harness`'s installer places the OpenFOAM skill -- what `sync` refreshes."""
    if harness == "claude-code":
        return root / ".claude" / "skills" / SKILL_NAME
    if harness == "hermes-agent":
        return _hermes_home() / "skills" / HERMES_SKILL_CATEGORY / SKILL_NAME
    raise ValueError(f"Unknown harness {harness!r}. Known: {', '.join(sorted(HARNESSES))}.")


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

    servers = {SERVER_NAME: server}
    paraview = paraview_integration()
    if paraview is not None:
        servers[PARAVIEW_SERVER_NAME] = paraview[0]

    config_path = root / ".mcp.json"
    merged = _merge_json(config_path, {"mcpServers": servers})
    _write(config_path, json.dumps(merged, indent=2) + "\n", result)

    settings_path = root / ".claude" / "settings.json"
    settings = claude_settings(_merge_json(settings_path, {}))
    _write(settings_path, json.dumps(settings, indent=2) + "\n", result)

    _ensure_gitignored(root, CLAUDE_CODE_GITIGNORE_LINES, result)

    bundled = root / ".claude" / "skills" / SKILL_NAME
    copy_skill(bundled, result)

    if paraview is not None:
        copy_skill(root / ".claude" / "skills" / PARAVIEW_SERVER_NAME, result, source=paraview[1])
        result.notes.append(
            "paraview MCP server and skill installed from paraview.dir -- Worker, Reviewer "
            "and Judge all get it."
        )
    else:
        result.notes.append(
            "paraview.dir is not set, so no paraview MCP server was configured. Point it "
            "(or FOAMAGENT_PARAVIEW_MCP_DIR) at a github.com/jumpcfd/paraview_mcp checkout "
            "to give Worker, Reviewer and Judge ParaView access."
        )

    knowledge.seed(result)
    result.notes.append(
        f"Knowledge files are at {knowledge.user_dir()}; edit them or add your own .md "
        "there -- describe_environment lists whatever is in it."
    )

    result.notes.append(
        "Start Claude Code in this directory; it picks up .mcp.json on launch."
    )
    result.notes.append(
        "Commit .mcp.json and .claude/settings.json: the task hooks then follow the project "
        "into every worktree."
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


def _yaml_server_block(name: str, server: Dict[str, object], env: Optional[Dict[str, str]] = None) -> List[str]:
    """One `mcp_servers:` entry, Hermes's YAML shape.

    Hermes's own default per-tool-call MCP timeout is 300s (tools/mcp_tool.py's own
    _DEFAULT_TOOL_TIMEOUT) -- shorter than review.timeout_seconds' own 1800s default
    (review/settings.py's DEFAULT_TIMEOUT_SECONDS). A real review that took longer than
    300s but well under 1800s was cut off client-side with "MCP TimeoutError" before the
    server-side subprocess (still well within its own budget) ever got to finish; the
    worker saw this indistinguishably from a hard failure. Matching this to Foam-Agent's
    own review timeout keeps the two budgets from fighting each other, for every server
    installed this way, not just the sandbox's own.
    """
    lines = [f"  {name}:", f'    command: "{server["command"]}"', "    args:"]
    lines += [f'      - "{arg}"' for arg in server["args"]]
    if env:
        lines.append("    env:")
        lines += [f'      {key}: "{value}"' for key, value in env.items()]
    lines.append(f"    timeout: {REVIEW_TIMEOUT_SECONDS}")
    lines.append("    enabled: true")
    return lines


def install_hermes_agent(root: Path) -> InstallResult:
    """Hermes Agent: a YAML server block, and skills installed where Hermes actually finds them.

    Like Codex, Hermes has no per-project MCP config -- the server block has to be merged
    into ~/.hermes/config.yaml's top-level mcp_servers: key by hand. Unlike Codex, its global
    skills/ directory is one level deeper: a category folder sits between skills/ and the
    skill itself. Confirmed by a live Hermes session running a real case end to end through
    a skill installed exactly this way (mirrored by hand before this installer existed).
    """
    result = InstallResult(harness="Hermes Agent")

    lines = ["mcp_servers:"] + _yaml_server_block(SERVER_NAME, server_command(), _server_env())
    paraview = paraview_integration()
    if paraview is not None:
        lines += _yaml_server_block(PARAVIEW_SERVER_NAME, paraview[0])

    _write(root / "foamagent-hermes.yaml", "\n".join(lines) + "\n", result)

    skills_root = _hermes_home() / "skills" / HERMES_SKILL_CATEGORY
    bundled = skills_root / SKILL_NAME
    copy_skill(bundled, result)

    result.notes.append(
        "Merge foamagent-hermes.yaml's mcp_servers entry into ~/.hermes/config.yaml "
        "(Hermes has no per-project MCP config) -- this is the only non-interactive way. "
        f"'hermes mcp add {SERVER_NAME} --command ... --args ...' does the same thing but "
        "always stops for an 'Enable all N tools? [Y/n/select]' prompt, with no flag to "
        "skip it, so it cannot be scripted or run unattended."
    )
    result.notes.append(
        f"Skill installed into {bundled} -- Hermes loads it from a category folder under "
        "skills/, not a flat skills/<name>/."
    )

    if paraview is not None:
        copy_skill(skills_root / PARAVIEW_SERVER_NAME, result, source=paraview[1])
        result.notes.append(
            "paraview MCP server and skill also merged in from paraview.dir."
        )

    knowledge.seed(result)
    result.notes.append(
        f"Knowledge files are at {knowledge.user_dir()}; edit them or add your own .md "
        "there -- describe_environment lists whatever is in it."
    )

    # review.command defaults to a Claude Code line (review/settings.py's DEFAULT_COMMAND)
    # regardless of which harness is installed here, so a hermes-agent-only install would
    # otherwise leave `request_review` shelling out to a `claude` binary that may not even
    # be on this machine. `hermes -z` takes the prompt as its own next argument rather than
    # a trailing positional (prompt_after_command), needs no option-parsing separator or
    # skip-permissions flag of its own (both cleared here), and has no per-invocation MCP
    # config to hide the worker's own server behind (mcp_config_flag cleared too) -- an
    # earlier version isolated the reviewer from that server with a second Hermes profile
    # instead, but that isolation broke more real tool calls than it caught (see git
    # history for the pre-removal debugging notes) and was dropped.
    config = settings_module.config_file()
    settings_module.set_value(config, "review.command", ["hermes", "-z"])
    settings_module.set_value(config, "review.prompt_after_command", True)
    settings_module.set_value(config, "review.prompt_separator", "")
    settings_module.set_value(config, "review.mcp_config_flag", "")
    settings_module.set_value(config, "review.strict_mcp_config_flag", "")
    result.notes.append("review.command set to run reviews through hermes -z too.")

    return result


HARNESSES: Dict[str, Callable[[Path], InstallResult]] = {
    "claude-code": install_claude_code,
    "hermes-agent": install_hermes_agent,
}


def install(harness: str, root: Optional[Path] = None) -> InstallResult:
    """Write the configuration for ``harness`` under ``root`` (default: here)."""
    installer = HARNESSES.get(harness)
    if installer is None:
        raise ValueError(
            f"Unknown harness {harness!r}. Known: {', '.join(sorted(HARNESSES))}."
        )
    return installer(Path(root or Path.cwd()).resolve())


__all__ = ["HARNESSES", "InstallResult", "SERVER_NAME", "SKILL_NAME", "PARAVIEW_SERVER_NAME",
           "copy_skill", "install", "paraview_integration", "server_command",
           "skill_destination", "skill_source", "skill_version"]
