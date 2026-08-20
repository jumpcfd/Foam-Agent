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

# The reviewer is not isolated from the case by tool restriction: an allowlist merges with
# whatever the user's own settings already permit rather than replacing it (a review started
# with a read-only allowlist was observed shelling out through Bash regardless, found by the
# end-to-end run of 2026-08-01), and the compensating deny-list-plus-case-copy machinery this
# used to carry made ordinary tools stop working for real users more often than it caught
# anything. The reviewer is now an ordinary, trusted subprocess of the harness, told its role
# by the prompt alone -- the same trust the user already places in their own session. What
# stops it running loose is `--dangerously-skip-permissions` doing the opposite of its name
# suggests here: headless (`-p`) Claude Code denies any tool call nobody pre-approved rather
# than hanging on a prompt nobody can answer, so *without* this flag the reviewer cannot even
# read the case. Set it to "" for a command that grants full access without one.
DEFAULT_SKIP_PERMISSIONS_FLAG = "--dangerously-skip-permissions"
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

# Named bundles of the settings above (command, the model flag, the skip-permissions flag,
# the MCP config flags, the prompt separator), so a user on a different harness picks
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
        "skip_permissions_flag": DEFAULT_SKIP_PERMISSIONS_FLAG,
        "prompt_separator": DEFAULT_PROMPT_SEPARATOR,
        "mcp_config_flag": DEFAULT_MCP_CONFIG_FLAG,
        "strict_mcp_config_flag": DEFAULT_STRICT_MCP_CONFIG_FLAG,
    },
    # An earlier version of this profile ran the review through a dedicated, isolated
    # Hermes identity (`foamagent-review`, created by `foamagent install hermes-agent
    # --with-review`) so the worker's own foamagent MCP server -- run_start and the other
    # case-mutating tools -- stayed out of the reviewer's reach, since Hermes has no
    # per-invocation MCP config (global only, unlike Claude's --mcp-config) to hide it with
    # a flag the way claude-code's strict_mcp_config_flag does. Real use found that
    # boundary cost more than it caught: the isolated profile's own toolset restrictions
    # broke ordinary reads (see git history for the pre-removal debugging notes), and the
    # fixes for that ended up granting the profile the same trusted, unrestricted
    # access as any other Hermes session -- at which point a separate identity was not
    # buying any real isolation. The reviewer now runs as the user's own default Hermes
    # profile, install_hermes_agent() already wired up: `foamagent install hermes-agent`
    # alone is enough. It does see the worker's foamagent MCP server, same as it sees every
    # other tool -- if that boundary matters again, sandbox the whole `hermes` process in
    # Docker rather than reintroducing a second Hermes identity.
    "hermes-agent": {
        "command": ["hermes", "-z"],
        "prompt_after_command": True,
        # Empty: there is no universal default model the way claude-sonnet-5 is for Claude
        # Code -- a Hermes install's model is whatever OpenRouter-routed model its own
        # profile is set up with. Empty hands the choice back to Hermes, same as any command
        # with no --model of its own (see ChannelSettings.argv).
        "model": "",
        "model_flag": DEFAULT_MODEL_FLAG,
        "skip_permissions_flag": "",
        "prompt_separator": "",
        "mcp_config_flag": "",
        "strict_mcp_config_flag": "",
    },
}

# The server name a review's sandbox MCP config is written under. See
# foamagent.review.sandbox and foamagent.review.channel.sandbox_config -- the reviewer is
# started with --strict-mcp-config pointed at a config holding only this one server, so it
# is the only MCP tool the review ever sees, whatever else the user has configured.
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
    "review.skip_permissions_flag": DEFAULT_SKIP_PERMISSIONS_FLAG,
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
    model: str = DEFAULT_MODEL
    model_flag: str = DEFAULT_MODEL_FLAG
    skip_permissions_flag: str = DEFAULT_SKIP_PERMISSIONS_FLAG
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
        because that is where a non-interactive harness expects its input.

        ``mcp_config`` names a server configuration written for this one run. It is passed
        with the strict flag, so the review gets that server and none of whatever the user
        happens to have configured for their own sessions.

        The model is named on the command line rather than left implicit, so the line this
        is logged as says which model reviewed the case. Setting ``review.model`` to "" hands
        that choice back to the harness, which is what a command that takes no ``--model``
        needs.

        ``skip_permissions_flag`` is what lets a headless session use any tool at all: see
        its own comment for why an *unset* allowlist would leave the review unable to read
        the case, not merely unable to write it.
        """
        argv = list(self.command)
        if self.prompt_after_command:
            argv.append(prompt)

        if self.model and self.model_flag:
            argv += [self.model_flag, self.model]
        if self.skip_permissions_flag:
            argv.append(self.skip_permissions_flag)

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
    """Every review setting, resolved, for `foamagent config show`.

    A per-role model nobody set is shown as the shared one it falls back to, rather than as
    blank: what the user wants to know is which model the judge will run on, not whether
    that answer came from a key with the judge's name on it.

    The flag-shaped keys (`command` through `strict_mcp_config_flag`) fall back to
    `review.harness`'s own profile, the same as `load_settings()` actually resolves them --
    not to REVIEW_KEYS' bare claude-code defaults. Without this, switching
    `review.harness` to `hermes-agent` left `config show` printing `[claude, -p]`
    regardless: correct for what actually runs, wrong for what this command told the user
    was running.
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
    on the exchange, not how the subprocess is started or how long it may take.
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

    model = _role_model(data, role, data.get("model", profile.get("model", DEFAULT_MODEL)))
    model_flag = data.get("model_flag", profile["model_flag"])
    skip_permissions_flag = data.get("skip_permissions_flag", profile["skip_permissions_flag"])
    prompt_separator = data.get("prompt_separator", profile["prompt_separator"])
    mcp_config_flag = data.get("mcp_config_flag", profile["mcp_config_flag"])
    strict_flag = data.get("strict_mcp_config_flag", profile["strict_mcp_config_flag"])
    prompt_after_command = bool(data.get("prompt_after_command", profile.get("prompt_after_command", False)))

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
        skip_permissions_flag=str(skip_permissions_flag) if skip_permissions_flag else "",
        prompt_separator=str(prompt_separator) if prompt_separator else "",
        timeout_seconds=timeout,
        mode=mode,
        mcp_config_flag=str(mcp_config_flag) if mcp_config_flag else "",
        strict_mcp_config_flag=str(strict_flag) if strict_flag else "",
        prompt_after_command=prompt_after_command,
        sandbox=_sandbox_settings(data.get("sandbox"), path),
    )
