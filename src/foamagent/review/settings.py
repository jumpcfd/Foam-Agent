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
DEFAULT_TIMEOUT_SECONDS = 900

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
class ChannelSettings:
    """How to start the model that audits a case."""

    command: List[str] = field(default_factory=lambda: list(DEFAULT_COMMAND))
    allowed_tools: List[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))
    allow_tools_flag: str = DEFAULT_ALLOW_TOOLS_FLAG
    allow_tools_separator: str = DEFAULT_ALLOW_TOOLS_SEPARATOR
    prompt_separator: str = DEFAULT_PROMPT_SEPARATOR
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def argv(self, prompt: str) -> List[str]:
        """The command line that runs one audit.

        The prompt is the last argument, after the tool allowlist and the separator that
        ends option parsing, because that is where a non-interactive harness expects its
        input.
        """
        argv = list(self.command)
        if self.allowed_tools and self.allow_tools_flag:
            argv += [self.allow_tools_flag, self.allow_tools_separator.join(self.allowed_tools)]
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
        bare = tool.split("(")[0].split(":")[-1].strip().lower()
        (dropped if bare in FORBIDDEN_TOOLS else kept).append(tool)
    if dropped:
        logger.warning(
            "Dropped %s from the audit's tool allowlist: an independent review may read the "
            "case, never change it.",
            ", ".join(dropped),
        )
    return kept


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
    )
