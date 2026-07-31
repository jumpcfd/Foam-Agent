"""Where the audit's settings come from.

The server holds no API key, so the model that audits a case is the user's own: a
non-interactive session of the harness they already pay for, started as a subprocess. What
that command is, which tools it may use and how long it may take are settings rather than
constants, because the harness differs per user.

The file is YAML at ``~/.config/foamagent/config.yaml``. Everything in it has a working
default for Claude Code, so a user who never writes one still gets a working audit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from foamagent.logger import get_logger

logger = get_logger(__name__)

CONFIG_FILENAME = "config.yaml"
TEMPLATES_DIRNAME = "templates"

# The default is Claude Code's non-interactive mode. `-p` takes the prompt as its argument
# and prints the model's final text to stdout, which is exactly the shape this needs.
DEFAULT_COMMAND: List[str] = ["claude", "-p"]
DEFAULT_ALLOW_TOOLS_FLAG = "--allowed-tools"
DEFAULT_ALLOW_TOOLS_SEPARATOR = ","
DEFAULT_ALLOWED_TOOLS: List[str] = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]
# `--allowed-tools` takes a list, so without this the prompt that follows it is read as
# more tool names and the review starts with no task at all. Set it to "" for a command
# that would treat the separator as part of its input.
DEFAULT_PROMPT_SEPARATOR = "--"
# A result review reads the case, the logs and the literature, and 900s was not enough for
# it on a finished cavity: it timed out twice in the phase-5 end-to-end run. Half an hour is
# long for a specification review and about right for a result one, and a review that is
# still running costs nothing that stopping it would recover.
DEFAULT_TIMEOUT_SECONDS = 1800

# The flags that hand the review a server of its own. Set either to "" for a command that
# does not take them; the sandbox is then simply not offered.
DEFAULT_MCP_CONFIG_FLAG = "--mcp-config"
DEFAULT_STRICT_MCP_CONFIG_FLAG = "--strict-mcp-config"

# The one tool a review may reach beyond reading and searching: a Python script, run in a
# container that mounts the case read-only. See foamagent.review.sandbox.
SANDBOX_SERVER = "foamagent"
SANDBOX_TOOL = "run_script"
SANDBOX_TOOL_NAME = f"mcp__{SANDBOX_SERVER}__{SANDBOX_TOOL}"

# Server tools are named by the server that serves them, so a name-based check cannot tell
# what one does. Rather than guess, only the tools this package itself provides are allowed
# through: anything else with an mcp prefix is dropped, whatever the settings file says.
ALLOWED_MCP_TOOLS = frozenset({SANDBOX_TOOL_NAME})

DEFAULT_SANDBOX_RUNTIME = "docker"
# Nothing is installed into it and nothing is built: the review writes plain Python, and
# the OpenFOAM fields a case this size writes are ASCII. An image with numpy in it is the
# obvious next step once a review is seen to want one.
DEFAULT_SANDBOX_IMAGE = "python:3.12-slim"
# Per script, not per review. A calculation over a finished case is seconds of work; five
# minutes is enough for a slow one and short enough that a runaway loop is noticed.
DEFAULT_SCRIPT_TIMEOUT_SECONDS = 300

# Tool names that would let the audit change what it is auditing. The allowlist is the
# user's to edit, but a reviewer that can rewrite the case is not a reviewer, so these are
# dropped from whatever the file says. Matched case-insensitively on the bare tool name,
# which is how every harness we know of spells them.
FORBIDDEN_TOOLS = frozenset(
    {
        "bash", "shell", "run", "execute", "exec", "terminal", "command",
        "write", "edit", "multiedit", "str_replace_editor", "notebookedit",
        "apply_patch", "create_file", "delete", "rm",
    }
)


def config_home() -> Path:
    """The directory holding Foam-Agent's user settings."""
    override = os.getenv("FOAMAGENT_CONFIG_HOME")
    if override and override.strip():
        return Path(override.strip()).expanduser()

    xdg = os.getenv("XDG_CONFIG_HOME")
    base = Path(xdg.strip()).expanduser() if xdg and xdg.strip() else Path.home() / ".config"
    return base / "foamagent"


def config_file() -> Path:
    """The settings file to read. ``FOAMAGENT_CONFIG_FILE`` names another one outright."""
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


@dataclass(frozen=True)
class SandboxSettings:
    """Where a review's arithmetic runs.

    A reviewer that cannot compute checks a residual history by eye. This gives it a
    Python interpreter in a container that mounts the case read-only, so it can add up a
    mass balance or compare a profile against published numbers without being able to
    change what it is reviewing.
    """

    runtime: str = DEFAULT_SANDBOX_RUNTIME
    image: str = DEFAULT_SANDBOX_IMAGE
    timeout_seconds: int = DEFAULT_SCRIPT_TIMEOUT_SECONDS

    @property
    def enabled(self) -> bool:
        return self.runtime == "docker"


@dataclass(frozen=True)
class ChannelSettings:
    """How to start the model that audits a case."""

    command: List[str] = field(default_factory=lambda: list(DEFAULT_COMMAND))
    allowed_tools: List[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))
    allow_tools_flag: str = DEFAULT_ALLOW_TOOLS_FLAG
    allow_tools_separator: str = DEFAULT_ALLOW_TOOLS_SEPARATOR
    prompt_separator: str = DEFAULT_PROMPT_SEPARATOR
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    mcp_config_flag: str = DEFAULT_MCP_CONFIG_FLAG
    strict_mcp_config_flag: str = DEFAULT_STRICT_MCP_CONFIG_FLAG
    sandbox: SandboxSettings = field(default_factory=SandboxSettings)

    @property
    def offers_sandbox(self) -> bool:
        """Whether this command can be handed a server of its own."""
        return self.sandbox.enabled and bool(self.mcp_config_flag)

    def argv(self, prompt: str, *, mcp_config: Optional[Path] = None) -> List[str]:
        """The command line that runs one audit.

        The prompt is the last argument, after the tool allowlist and the separator that
        ends option parsing, because that is where a non-interactive harness expects its
        input.

        ``mcp_config`` names a server configuration written for this one run. It is passed
        with the strict flag, so the review gets that server and none of whatever the user
        happens to have configured for their own sessions.
        """
        argv = list(self.command)

        tools = list(self.allowed_tools)
        if mcp_config is not None and SANDBOX_TOOL_NAME not in tools:
            tools.append(SANDBOX_TOOL_NAME)

        if tools and self.allow_tools_flag:
            argv += [self.allow_tools_flag, self.allow_tools_separator.join(tools)]
        if mcp_config is not None and self.mcp_config_flag:
            argv += [self.mcp_config_flag, str(mcp_config)]
            if self.strict_mcp_config_flag:
                argv.append(self.strict_mcp_config_flag)
        if self.prompt_separator:
            argv.append(self.prompt_separator)
        argv.append(prompt)
        return argv


def _as_list_of_str(value: Any, key: str) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        # A single string is a common way to write a one-element list by accident. Splitting
        # it on whitespace does what was meant for `command: claude -p`.
        return value.split()
    if isinstance(value, (list, tuple)) and all(isinstance(v, (str, int, float)) for v in value):
        return [str(v) for v in value]
    logger.warning("Ignoring %s in %s: expected a list of strings.", key, config_file())
    return None


def _drop_forbidden(tools: List[str]) -> List[str]:
    kept, dropped = [], []
    for tool in tools:
        name = tool.split("(")[0].strip()
        if name.lower().startswith("mcp__"):
            allowed = name in ALLOWED_MCP_TOOLS
        else:
            allowed = name.split(":")[-1].lower() not in FORBIDDEN_TOOLS
        (kept if allowed else dropped).append(tool)
    if dropped:
        logger.warning(
            "Dropped %s from the audit's tool allowlist: an independent review may read the "
            "case, never change it.",
            ", ".join(dropped),
        )
    return kept


def _sandbox_settings(data: Any, path: Path) -> SandboxSettings:
    if data is None:
        return SandboxSettings()
    if not isinstance(data, dict):
        logger.warning("review.sandbox in %s is not a mapping; using the defaults.", path)
        return SandboxSettings()

    runtime = str(data.get("runtime", DEFAULT_SANDBOX_RUNTIME)).strip().lower()
    if runtime not in ("docker", "none"):
        logger.warning(
            "review.sandbox.runtime in %s is %r; expected 'docker' or 'none'. Using %r.",
            path, runtime, DEFAULT_SANDBOX_RUNTIME,
        )
        runtime = DEFAULT_SANDBOX_RUNTIME

    image = str(data.get("image", DEFAULT_SANDBOX_IMAGE)).strip() or DEFAULT_SANDBOX_IMAGE

    timeout = data.get("timeout_seconds", DEFAULT_SCRIPT_TIMEOUT_SECONDS)
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        logger.warning(
            "review.sandbox.timeout_seconds in %s is not a number; using %s.",
            path, DEFAULT_SCRIPT_TIMEOUT_SECONDS,
        )
        timeout = DEFAULT_SCRIPT_TIMEOUT_SECONDS

    return SandboxSettings(runtime=runtime, image=image, timeout_seconds=timeout)


def load_settings(path: Optional[Path] = None) -> ChannelSettings:
    """Read the channel settings, falling back to the defaults for anything absent.

    A missing file is the normal case, not an error: the defaults drive Claude Code. A file
    that cannot be parsed is reported and then ignored, because failing every review over a
    stray tab in a settings file helps nobody.
    """
    path = path or config_file()
    data: Dict[str, Any] = {}

    if path.is_file():
        try:
            import yaml

            parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                data = parsed.get("review") or parsed.get("model_channel") or {}
                if not isinstance(data, dict):
                    logger.warning("The 'review' section of %s is not a mapping; ignoring it.", path)
                    data = {}
            elif parsed is not None:
                logger.warning("%s does not contain a mapping; ignoring it.", path)
        except Exception as exc:  # yaml.YAMLError, OSError, ImportError
            logger.warning("Could not read %s (%s); using the built-in defaults.", path, exc)

    command = _as_list_of_str(data.get("command"), "review.command") or list(DEFAULT_COMMAND)
    tools = _as_list_of_str(data.get("allowed_tools"), "review.allowed_tools")
    tools = list(DEFAULT_ALLOWED_TOOLS) if tools is None else tools

    flag = data.get("allow_tools_flag", DEFAULT_ALLOW_TOOLS_FLAG)
    separator = data.get("allow_tools_separator", DEFAULT_ALLOW_TOOLS_SEPARATOR)
    prompt_separator = data.get("prompt_separator", DEFAULT_PROMPT_SEPARATOR)
    mcp_config_flag = data.get("mcp_config_flag", DEFAULT_MCP_CONFIG_FLAG)
    strict_flag = data.get("strict_mcp_config_flag", DEFAULT_STRICT_MCP_CONFIG_FLAG)

    timeout = data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        logger.warning("review.timeout_seconds in %s is not a number; using %s.", path, DEFAULT_TIMEOUT_SECONDS)
        timeout = DEFAULT_TIMEOUT_SECONDS

    return ChannelSettings(
        command=command,
        allowed_tools=_drop_forbidden(tools),
        allow_tools_flag=str(flag) if flag else "",
        allow_tools_separator=str(separator),
        prompt_separator=str(prompt_separator) if prompt_separator else "",
        timeout_seconds=timeout,
        mcp_config_flag=str(mcp_config_flag) if mcp_config_flag else "",
        strict_mcp_config_flag=str(strict_flag) if strict_flag else "",
        sandbox=_sandbox_settings(data.get("sandbox"), path),
    )
