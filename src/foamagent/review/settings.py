"""Where the audit's settings come from.

The server holds no API key, so the model that audits a case is the user's own: a
non-interactive session of the harness they already pay for, started as a subprocess. What
that command is, which tools it may use and how long it may take are settings rather than
constants, because the harness differs per user.

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

# The roles that run on a model. The reviewer reads and computes; the judge rules on the
# exchange between the reviewer and whoever built the case. They are named separately
# because they are not the same job, and a user who wants the ruling done by a stronger
# model should not have to pay for that model on every arithmetic check as well.
REVIEWER_ROLE = "reviewer"
JUDGE_ROLE = "judge"
ROLES = (REVIEWER_ROLE, JUDGE_ROLE)

# The default is Claude Code's non-interactive mode. `-p` takes the prompt as its argument
# and prints the model's final text to stdout, which is exactly the shape this needs.
DEFAULT_COMMAND: List[str] = ["claude", "-p"]
# The model the review runs on, named here rather than left to whatever the harness happens
# to default to. A user who cannot tell which model checked their result has no way to judge
# the check, and an unnamed model is guessed at rather than trusted. Sonnet is the default
# because a review is reading, arithmetic and comparison against published numbers.
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MODEL_FLAG = "--model"

DEFAULT_ALLOW_TOOLS_FLAG = "--allowed-tools"
DEFAULT_ALLOW_TOOLS_SEPARATOR = ","
DEFAULT_ALLOWED_TOOLS: List[str] = ["Read", "Grep", "Glob", "WebSearch", "WebFetch"]

# Leaving a tool out of the allowlist does not take it away: the harness merges that list
# with whatever the user's own settings already permit, so a review started with a read-only
# allowlist was observed shelling out through Bash regardless (found by the end-to-end run of
# 2026-08-01). Denying by name is what actually holds, so the tools that could change the
# case under review are denied outright, and this list is not a setting -- a deny list a file
# can shorten is a deny list that gets shortened.
DEFAULT_DISALLOW_TOOLS_FLAG = "--disallowed-tools"
DENIED_TOOLS: List[str] = ["Bash", "Write", "Edit", "NotebookEdit"]
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

# Named bundles of the settings above (command, the model flag, the tool allow/deny
# flags, the MCP config flags, the prompt separator), so a user on a different harness picks
# one name instead of rewriting every flag by hand. Built from the DEFAULT_* constants
# rather than duplicating their values, so the two cannot drift apart.
#
# A profile for another harness belongs here once `foamagent doctor --review` has actually
# been run against it, not before: a flag spelling nobody has tried is a guess with a name
# on it, and a guess that fails still costs the user the review it was supposed to save them
# from writing by hand. See AGENTS.md / README's Harness support section for what is
# verified for each profile shipped here.
DEFAULT_HARNESS = "claude-code"
HARNESS_PROFILES: Dict[str, Dict[str, Any]] = {
    "claude-code": {
        "command": list(DEFAULT_COMMAND),
        "model_flag": DEFAULT_MODEL_FLAG,
        "allow_tools_flag": DEFAULT_ALLOW_TOOLS_FLAG,
        "allow_tools_separator": DEFAULT_ALLOW_TOOLS_SEPARATOR,
        "disallow_tools_flag": DEFAULT_DISALLOW_TOOLS_FLAG,
        "prompt_separator": DEFAULT_PROMPT_SEPARATOR,
        "mcp_config_flag": DEFAULT_MCP_CONFIG_FLAG,
        "strict_mcp_config_flag": DEFAULT_STRICT_MCP_CONFIG_FLAG,
    },
    # Hermes has no per-invocation MCP config (global only, unlike Claude's --mcp-config),
    # so isolation from the worker's own foamagent MCP server -- which has case-mutating
    # tools like run_start -- has to come from *which* Hermes profile runs the review, not
    # from a flag: `command` here must be the wrapper script of an isolated Hermes profile
    # (`hermes profile create <name> --no-skills`, `hermes profile alias <name>`) that has
    # no MCP servers registered. See README's "Setting up Hermes Agent as the review
    # command" for the full one-time setup.
    #
    # Hermes's own tool control is toolset-level, not per-tool: `file` bundles read and
    # write with no split, so there is no way to grant "can read the case" without also
    # granting "can write it" -- confirmed by asking a review to write a probe file under
    # `-t web` (file excluded): no file appeared, but the model still claimed success, so a
    # harness that silently can't do something is not distinguishable from one that silently
    # declined it. `copy_case_dir` below is how this profile stays safe anyway: the review
    # never sees the real case, only a throwaway copy, so it does not matter whether it can
    # write.
    "hermes-agent": {
        "command": ["foamagent-review", "-z"],
        "prompt_after_command": True,
        # Empty: there is no universal default model the way claude-sonnet-5 is for Claude
        # Code -- a Hermes install's model is whatever OpenRouter-routed model its own
        # profile is set up with. Empty hands the choice back to Hermes, same as any command
        # with no --model of its own (see ChannelSettings.argv).
        "model": "",
        "model_flag": DEFAULT_MODEL_FLAG,
        # Hermes toolset names, not Claude tool names -- "Read,Grep,Glob,WebSearch,WebFetch"
        # means nothing to it. `file` is the closest thing to read access it has (see the
        # note above on why that also grants write); `web` covers search and fetch.
        # Deliberately no `terminal`/`code_execution`/`browser`: those are host-reaching
        # capabilities Claude's own reviewer never gets either (Bash is denied outright).
        #
        # Listed here for documentation, but NOT passed as a per-invocation `--toolsets`
        # flag (allow_tools_flag is "") -- confirmed on a real review run, and reproduced
        # directly against `hermes -z`, that a narrow --toolsets list makes the `file`
        # toolset non-functional: the model can no longer actually read a file that exists
        # (either a flat refusal, or worse, a confident wrong answer with no tool call at
        # all), while the exact same prompt with no --toolsets restriction reads correctly
        # every time. This reproduced across two different models (deepseek and gpt-5.6-luna)
        # and is Hermes's own bug, not something a different flag spelling works around --
        # dropping the flag also then requires `setup_hermes_review()`'s persistent
        # `hermes tools disable` step (not a per-invocation flag, so unaffected by this bug)
        # to be the *only* thing narrowing what this profile can do, which is one reason
        # `--with-review` is the supported way to set this profile up rather than by hand.
        "allowed_tools": ["file", "web"],
        "allow_tools_flag": "",
        "allow_tools_separator": ",",
        # No per-invocation deny flag exists (`hermes tools disable` mutates persistent
        # profile config, not one call) -- copy_case_dir is what actually holds instead.
        "disallow_tools_flag": "",
        "prompt_separator": "",
        "mcp_config_flag": "",
        "strict_mcp_config_flag": "",
        "copy_case_dir": True,
    },
}

# The one tool a review may reach beyond reading and searching: a Python script, run in a
# container that mounts the case read-only. See foamagent.review.sandbox.
SANDBOX_SERVER = "foamagent"
SANDBOX_TOOL = "run_script"
SANDBOX_TOOL_NAME = f"mcp__{SANDBOX_SERVER}__{SANDBOX_TOOL}"

# Server tools are named by the server that serves them, so a name-based check cannot tell
# what one does. Rather than guess, only the tools this package itself provides are allowed
# through: anything else with an mcp prefix is dropped, whatever the settings file says.
ALLOWED_MCP_TOOLS = frozenset({SANDBOX_TOOL_NAME})

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


# The settings this module reads, as dotted keys, with what each is when nobody sets it.
# `foamagent config show` walks this mapping in order and `foamagent config set` validates
# against its keys, so a setting added here needs adding nowhere else. None of them has an
# environment variable, because a command line with its own argument list does not fit in
# one.
#
# The two per-role models are the exception, and their default is None: unset, each is
# whatever `review.model` resolved to, which is not known until the settings are read.
REVIEW_KEYS: Dict[str, Any] = {
    "review.harness": DEFAULT_HARNESS,
    "review.command": DEFAULT_COMMAND,
    "review.model": DEFAULT_MODEL,
    "review.reviewer.model": None,
    "review.judge.model": None,
    "review.model_flag": DEFAULT_MODEL_FLAG,
    "review.allowed_tools": DEFAULT_ALLOWED_TOOLS,
    "review.allow_tools_flag": DEFAULT_ALLOW_TOOLS_FLAG,
    "review.allow_tools_separator": DEFAULT_ALLOW_TOOLS_SEPARATOR,
    "review.disallow_tools_flag": DEFAULT_DISALLOW_TOOLS_FLAG,
    "review.prompt_separator": DEFAULT_PROMPT_SEPARATOR,
    "review.mcp_config_flag": DEFAULT_MCP_CONFIG_FLAG,
    "review.strict_mcp_config_flag": DEFAULT_STRICT_MCP_CONFIG_FLAG,
    "review.prompt_after_command": False,
    "review.copy_case_dir": False,
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
    model: str = DEFAULT_MODEL
    model_flag: str = DEFAULT_MODEL_FLAG
    allowed_tools: List[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))
    allow_tools_flag: str = DEFAULT_ALLOW_TOOLS_FLAG
    allow_tools_separator: str = DEFAULT_ALLOW_TOOLS_SEPARATOR
    disallow_tools_flag: str = DEFAULT_DISALLOW_TOOLS_FLAG
    prompt_separator: str = DEFAULT_PROMPT_SEPARATOR
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    mcp_config_flag: str = DEFAULT_MCP_CONFIG_FLAG
    strict_mcp_config_flag: str = DEFAULT_STRICT_MCP_CONFIG_FLAG
    # True for a harness whose prompt-taking flag needs the prompt as its own immediately
    # following argument (Hermes's `-z PROMPT`), unlike Claude Code's `-p` (no value of its
    # own; the prompt is a trailing positional after every other flag).
    prompt_after_command: bool = False
    # True for a harness with no way to deny write access to just the tools that need it
    # (see the hermes-agent profile's own comment) -- the review is handed a throwaway copy
    # of the case instead of the case itself, so nothing it does can reach the real one.
    copy_case_dir: bool = False
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

        The prompt is the last argument, after the tool allowlist and the separator that
        ends option parsing, because that is where a non-interactive harness expects its
        input.

        ``mcp_config`` names a server configuration written for this one run. It is passed
        with the strict flag, so the review gets that server and none of whatever the user
        happens to have configured for their own sessions.

        The model is named on the command line rather than left implicit, so the line this
        is logged as says which model reviewed the case. Setting ``review.model`` to "" hands
        that choice back to the harness, which is what a command that takes no ``--model``
        needs.

        The allowlist says what the review is here to use; the deny list is what stops it
        using anything else, because an allowlist alone is merged with the permissions the
        user's own settings already grant.
        """
        argv = list(self.command)
        if self.prompt_after_command:
            argv.append(prompt)

        if self.model and self.model_flag:
            argv += [self.model_flag, self.model]

        tools = list(self.allowed_tools)
        if mcp_config is not None and SANDBOX_TOOL_NAME not in tools:
            tools.append(SANDBOX_TOOL_NAME)

        if tools and self.allow_tools_flag:
            argv += [self.allow_tools_flag, self.allow_tools_separator.join(tools)]
        if self.disallow_tools_flag:
            argv += [self.disallow_tools_flag, self.allow_tools_separator.join(DENIED_TOOLS)]
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


def describe(resolved: Optional[Any] = None) -> List[Any]:
    """Every review setting, resolved, for `foamagent config show`.

    A per-role model nobody set is shown as the shared one it falls back to, rather than as
    blank: what the user wants to know is which model the judge will run on, not whether
    that answer came from a key with the judge's name on it.

    The flag-shaped keys (`command` through `strict_mcp_config_flag`) fall back to
    `review.harness`'s own profile, the same as `load_settings()` actually resolves them --
    not to REVIEW_KEYS' bare claude-code defaults. Without this, switching
    `review.harness` to `hermes-agent` left `config show` printing `[claude, -p]` and
    `--disallowed-tools` regardless: correct for what actually runs, wrong for what this
    command told the user was running.
    """
    from foamagent.settings import Setting

    resolved = resolved or settings_module.load()

    data = resolved.section(SECTION) or resolved.section(LEGACY_SECTION) or {}
    harness = str(data.get("harness", DEFAULT_HARNESS)).strip() or DEFAULT_HARNESS
    profile = HARNESS_PROFILES.get(harness, HARNESS_PROFILES[DEFAULT_HARNESS])

    shared = resolved.resolve("review.model", default=profile.get("model", DEFAULT_MODEL))
    rows: List[Any] = []
    for key, default in REVIEW_KEYS.items():
        bare = key[len("review."):] if key.startswith("review.") else key
        default = profile.get(bare, default)
        setting = resolved.resolve(key, default=default)
        # Only the per-role models default to None, and an unset one is the shared model.
        if setting.value is None:
            setting = Setting(key, shared.value, "review.model")
        rows.append(setting)

    # The deny list is reported alongside the settings although it is not one, because a
    # user reading this list will otherwise conclude that the allowlist is all there is.
    rows.append(Setting("review.denied_tools", list(DENIED_TOOLS), "not configurable"))
    return rows


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


def _role_model(data: Dict[str, Any], role: Optional[str], fallback: Any) -> Any:
    """The model for one role, falling back to the one every role shares.

    ``review.model`` remains the setting most people touch. The per-role keys exist for
    the case where the ruling and the arithmetic should not run on the same model.
    """
    if role is None:
        return fallback

    section = data.get(role)
    if section is None:
        return fallback
    if not isinstance(section, dict):
        logger.warning(
            "review.%s in the settings is not a mapping; using review.model for it.", role
        )
        return fallback
    return section.get("model", fallback)


def load_settings(path: Optional[Path] = None, *, role: Optional[str] = None) -> ChannelSettings:
    """Read the channel settings, falling back to the defaults for anything absent.

    A missing file is the normal case, not an error: the defaults drive Claude Code. A file
    that cannot be parsed is reported and then ignored, because failing every review over a
    stray tab in a settings file helps nobody.

    ``role`` is "reviewer" or "judge", and selects ``review.<role>.model`` when the settings
    name one. Everything else is shared: what differs between the two is which model rules
    on the exchange, not which tools it may use or how long it may take.
    """
    if role is not None and role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}, not {role!r}")

    data, path = _section(path)

    harness = str(data.get("harness", DEFAULT_HARNESS)).strip() or DEFAULT_HARNESS
    profile = HARNESS_PROFILES.get(harness)
    if profile is None:
        logger.warning(
            "review.harness in %s is %r; no such profile. Using %r. Known profiles: %s.",
            path, harness, DEFAULT_HARNESS, ", ".join(sorted(HARNESS_PROFILES)),
        )
        profile = HARNESS_PROFILES[DEFAULT_HARNESS]

    command = _as_list_of_str(data.get("command"), "review.command") or list(profile["command"])
    tools = _as_list_of_str(data.get("allowed_tools"), "review.allowed_tools")
    tools = list(profile.get("allowed_tools", DEFAULT_ALLOWED_TOOLS)) if tools is None else tools

    model = _role_model(data, role, data.get("model", profile.get("model", DEFAULT_MODEL)))
    model_flag = data.get("model_flag", profile["model_flag"])

    flag = data.get("allow_tools_flag", profile["allow_tools_flag"])
    separator = data.get("allow_tools_separator", profile["allow_tools_separator"])
    disallow_flag = data.get("disallow_tools_flag", profile["disallow_tools_flag"])
    prompt_separator = data.get("prompt_separator", profile["prompt_separator"])
    mcp_config_flag = data.get("mcp_config_flag", profile["mcp_config_flag"])
    strict_flag = data.get("strict_mcp_config_flag", profile["strict_mcp_config_flag"])
    prompt_after_command = bool(data.get("prompt_after_command", profile.get("prompt_after_command", False)))
    copy_case_dir = bool(data.get("copy_case_dir", profile.get("copy_case_dir", False)))
    # copy_case_dir is the other way this can stay safe with no per-invocation deny flag:
    # the review never sees the live case, only a throwaway copy, so there is nothing for
    # Bash/Write/Edit to damage even if nothing denies them by name. hermes-agent is set up
    # this way on purpose (see its profile above) -- warning about it on every load_settings()
    # call (doctor alone triggers this five separate times) read as a live, repeating danger
    # for a profile that was never actually exposed.
    if not disallow_flag and not copy_case_dir:
        logger.warning(
            "review.disallow_tools_flag in %s is empty, so %s cannot be denied to the review. "
            "Whatever the user's own settings permit, the review may do to the case.",
            path, ", ".join(DENIED_TOOLS),
        )

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
        model=str(model).strip() if model else "",
        model_flag=str(model_flag).strip() if model_flag else "",
        allowed_tools=_drop_forbidden(tools),
        allow_tools_flag=str(flag) if flag else "",
        allow_tools_separator=str(separator),
        disallow_tools_flag=str(disallow_flag) if disallow_flag else "",
        prompt_separator=str(prompt_separator) if prompt_separator else "",
        timeout_seconds=timeout,
        mode=mode,
        mcp_config_flag=str(mcp_config_flag) if mcp_config_flag else "",
        strict_mcp_config_flag=str(strict_flag) if strict_flag else "",
        prompt_after_command=prompt_after_command,
        copy_case_dir=copy_case_dir,
        sandbox=_sandbox_settings(data.get("sandbox"), path),
    )
