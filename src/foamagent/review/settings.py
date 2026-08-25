"""Where the audit's settings come from.

The server holds no API key, so the model that audits a case is the user's own: a
non-interactive session of the harness they already pay for, started as a subprocess. What
that command is and how long it may take are settings rather than constants, because the
harness differs per user.

The file is YAML at ``~/.config/foamagent/config.yaml``, and a project file next to the
work overrides it (foamagent.settings resolves both). Everything in it has a working
default for Claude Code, so a user who never writes one still gets a working audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from foamagent import settings as settings_module
from foamagent.logger import get_logger
from foamagent.settings import (  # re-exported: this is where callers have always found them
    CONFIG_FILENAME,
    TEMPLATES_DIRNAME,
    config_file,
    config_home,
    templates_dir,
)

logger = get_logger(__name__)

SECTION = "review"
# The section's older name, still read so that a settings file written before the rename
# keeps working.
LEGACY_SECTION = "model_channel"

# The default is Claude Code's non-interactive mode. `-p` takes the prompt as its argument
# and prints the model's final text to stdout, which is exactly the shape this needs. The
# model is named on the command line rather than left to whatever the harness happens to
# default to -- a user who cannot tell which model checked their result has no way to judge
# the check -- and `--dangerously-skip-permissions` is what lets a headless (`-p`) session
# use any tool at all: without it Claude Code denies any tool call nobody pre-approved rather
# than hanging on a prompt nobody can answer, so the reviewer could not even read the case.
# Reviewer and judge are one command: they are not the same job (the reviewer reads and
# computes, the judge rules on the exchange) but they are the same kind of job, and a
# `review.command` a user writes out by hand once is simpler to reason about than a shared
# default plus two per-role overrides. Point `command` at a different harness entirely --
# with its own model and permission flags already baked in -- to switch what runs a review.
DEFAULT_COMMAND: List[str] = [
    "claude", "-p", "--model", "claude-sonnet-5", "--dangerously-skip-permissions",
]
# The separator ends option parsing before the prompt, so a prompt that starts with `-` is
# not read as more flags. Set it to "" for a command that would treat the separator as part
# of its input.
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

# The server name a review's sandbox MCP config is written under. See
# foamagent.review.sandbox and foamagent.review.channel.sandbox_config -- the reviewer is
# started with --strict-mcp-config pointed at a config holding only this server (plus
# paraview, when foamagent.harness.paraview_integration finds one configured), so nothing
# else the user has set up for their own sessions leaks into the review.
SANDBOX_SERVER = "foamagent"

# Which stages actually run a model. The default reviews everything, because a result
# nobody checked is what this fork exists to avoid. The other two are for work where the
# check is not the point: `spec` keeps the cheap check that catches a case answering the
# wrong question, and `off` is for a benchmark or a case being run for the twentieth time,
# where two reviews and a report per run cost more than they tell anyone.
DEFAULT_MODE = "full"
MODES = ("full", "spec", "off")

DEFAULT_SANDBOX_RUNTIME = "docker"
# Nothing is installed into it and nothing is built: the review writes plain Python, and
# the OpenFOAM fields a case this size writes are ASCII. An image with numpy in it is the
# obvious next step once a review is seen to want one.
DEFAULT_SANDBOX_IMAGE = "python:3.12-slim"
# Per script, not per review. A calculation over a finished case is seconds of work; five
# minutes is enough for a slow one and short enough that a runaway loop is noticed.
DEFAULT_SCRIPT_TIMEOUT_SECONDS = 300


# The settings this module reads, as dotted keys, with what each is when nobody sets it.
# `foamagent config show` walks this mapping in order and `foamagent config set` validates
# against its keys, so a setting added here needs adding nowhere else. None of them has an
# environment variable, because a command line with its own argument list does not fit in
# one.
REVIEW_KEYS: Dict[str, Any] = {
    "review.command": DEFAULT_COMMAND,
    "review.prompt_separator": DEFAULT_PROMPT_SEPARATOR,
    "review.mcp_config_flag": DEFAULT_MCP_CONFIG_FLAG,
    "review.strict_mcp_config_flag": DEFAULT_STRICT_MCP_CONFIG_FLAG,
    "review.prompt_after_command": False,
    "review.timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    "review.mode": DEFAULT_MODE,
    "review.sandbox.runtime": DEFAULT_SANDBOX_RUNTIME,
    "review.sandbox.image": DEFAULT_SANDBOX_IMAGE,
    "review.sandbox.timeout_seconds": DEFAULT_SCRIPT_TIMEOUT_SECONDS,
}


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
    prompt_separator: str = DEFAULT_PROMPT_SEPARATOR
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    mcp_config_flag: str = DEFAULT_MCP_CONFIG_FLAG
    strict_mcp_config_flag: str = DEFAULT_STRICT_MCP_CONFIG_FLAG
    # True for a harness whose prompt-taking flag needs the prompt as its own immediately
    # following argument (Hermes's `-z PROMPT`), unlike Claude Code's `-p` (no value of its
    # own; the prompt is a trailing positional after every other flag).
    prompt_after_command: bool = False
    mode: str = DEFAULT_MODE
    sandbox: SandboxSettings = field(default_factory=SandboxSettings)

    @property
    def offers_sandbox(self) -> bool:
        """Whether this command can be handed a server of its own."""
        return self.sandbox.enabled and bool(self.mcp_config_flag)

    def covers(self, task: str) -> bool:
        """Whether ``mode`` has this stage checked at all.

        ``task`` is "spec", "result" or "report". Anything not covered returns a document
        saying so rather than nothing at all: a stage that was skipped by configuration is
        still a stage that was not checked, and the user is told either way.
        """
        if self.mode == "off":
            return False
        if self.mode == "spec":
            return task == "spec"
        return True

    def why_not_covered(self, task: str) -> str:
        return (
            f"The {task} stage is switched off for this installation "
            f"(review.mode is {self.mode!r})."
        )

    def argv(self, prompt: str, *, mcp_config: Optional[Path] = None) -> List[str]:
        """The command line that runs one audit.

        The prompt is the last argument, after the separator that ends option parsing,
        because that is where a non-interactive harness expects its input. The model and
        permission flags are not assembled here: they are whatever ``command`` already
        contains, since ``review.command`` is the whole command line a user configures.

        ``mcp_config`` names a server configuration written for this one run. It is passed
        with the strict flag, so the review gets that server and none of whatever the user
        happens to have configured for their own sessions.
        """
        argv = list(self.command)
        if self.prompt_after_command:
            argv.append(prompt)

        if mcp_config is not None and self.mcp_config_flag:
            argv += [self.mcp_config_flag, str(mcp_config)]
            if self.strict_mcp_config_flag:
                argv.append(self.strict_mcp_config_flag)
        if self.prompt_separator:
            argv.append(self.prompt_separator)
        if not self.prompt_after_command:
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


def describe(resolved: Optional[Any] = None) -> List[Any]:
    """Every review setting, resolved, for `foamagent config show`."""
    resolved = resolved or settings_module.load()
    return [resolved.resolve(key, default=default) for key, default in REVIEW_KEYS.items()]


def _section(path: Optional[Path]) -> tuple[Dict[str, Any], Path]:
    """The review section in effect, and the file to name in a message about it."""
    if path is not None:
        parsed = settings_module.read_yaml(path)
        data = parsed.get(SECTION) or parsed.get(LEGACY_SECTION) or {}
        if not isinstance(data, dict):
            logger.warning("The %r section of %s is not a mapping; ignoring it.", SECTION, path)
            data = {}
        return data, path

    resolved = settings_module.load()
    data = resolved.section(SECTION) or resolved.section(LEGACY_SECTION)
    return data, (resolved.files[0] if resolved.files else config_file())


def load_settings(path: Optional[Path] = None) -> ChannelSettings:
    """Read the channel settings, falling back to the defaults for anything absent.

    A missing file is the normal case, not an error: the defaults drive Claude Code. A file
    that cannot be parsed is reported and then ignored, because failing every review over a
    stray tab in a settings file helps nobody.
    """
    data, path = _section(path)

    command = _as_list_of_str(data.get("command"), "review.command") or list(DEFAULT_COMMAND)
    prompt_separator = data.get("prompt_separator", DEFAULT_PROMPT_SEPARATOR)
    mcp_config_flag = data.get("mcp_config_flag", DEFAULT_MCP_CONFIG_FLAG)
    strict_flag = data.get("strict_mcp_config_flag", DEFAULT_STRICT_MCP_CONFIG_FLAG)
    prompt_after_command = bool(data.get("prompt_after_command", False))

    timeout = data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        logger.warning("review.timeout_seconds in %s is not a number; using %s.", path, DEFAULT_TIMEOUT_SECONDS)
        timeout = DEFAULT_TIMEOUT_SECONDS

    mode = data.get("mode", DEFAULT_MODE)
    # YAML 1.1 reads a bare `off` as the boolean false, so `review: {mode: off}` -- the
    # spelling anyone would write -- arrives here as False. Reading it as the word meant is
    # better than telling the user to quote it.
    if mode is False:
        mode = "off"
    mode = str(mode).strip().lower()
    if mode not in MODES:
        logger.warning(
            "review.mode in %s is %r; expected one of %s. Using %r.",
            path, mode, ", ".join(MODES), DEFAULT_MODE,
        )
        mode = DEFAULT_MODE

    return ChannelSettings(
        command=command,
        prompt_separator=str(prompt_separator) if prompt_separator else "",
        timeout_seconds=timeout,
        mode=mode,
        mcp_config_flag=str(mcp_config_flag) if mcp_config_flag else "",
        strict_mcp_config_flag=str(strict_flag) if strict_flag else "",
        prompt_after_command=prompt_after_command,
        sandbox=_sandbox_settings(data.get("sandbox"), path),
    )
