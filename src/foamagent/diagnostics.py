"""What `foamagent doctor` checks, separately from how it prints.

Everything here is discovered at the moment it is asked for, and nothing is changed. The
point is to move the failures that used to surface inside the harness -- an OpenFOAM that
cannot be reached, a catalogue nobody built, a review command that is not installed -- to a
command the user can run before starting work.

Each check says whether it holds, what was measured, and what to do about it. A check that
fails without a fix to offer is a check that leaves the user where it found them.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from foamagent.logger import get_logger

logger = get_logger(__name__)

MCP_CONFIG_FILENAME = ".mcp.json"
HERMES_CONFIG_FILENAME = "foamagent-hermes.yaml"


@dataclass(frozen=True)
class Check:
    """One thing that was looked at."""

    name: str
    ok: bool
    detail: str
    fix: str = ""
    # Whether a failure here means nothing works. A missing review command degrades the
    # work (the case is built and run, and the report says it was never checked); an
    # OpenFOAM that cannot be reached stops it.
    required: bool = True

    @property
    def blocking(self) -> bool:
        return self.required and not self.ok


def check_openfoam(config=None) -> Check:
    """Is there an OpenFOAM this machine can run?"""
    from foamagent.config import Config
    from foamagent.environment import environment_from_config

    config = config or Config()
    try:
        environment = environment_from_config(config)
    except Exception as exc:  # a probe that cannot start is a failed check, not a crash
        return Check(
            name="OpenFOAM",
            ok=False,
            detail=f"The probe could not be run: {exc}",
            fix="Source the OpenFOAM bashrc, or set openfoam.runtime to docker.",
        )

    if not environment.detected:
        return Check(
            name="OpenFOAM",
            ok=False,
            detail=f"No installation was detected ({config.openfoam_runtime} runtime).",
            fix=(
                "Native: source the bashrc so $WM_PROJECT_DIR is set. "
                "Container: foamagent config set openfoam.runtime docker"
            ),
        )

    return Check(
        name="OpenFOAM",
        ok=True,
        detail=f"{environment.describe()} ({config.openfoam_runtime} runtime)",
    )


def check_library(config=None) -> Check:
    """Has the tutorial catalogue been built for that installation?"""
    from foamagent.config import Config
    from foamagent.environment import environment_from_config
    from foamagent.indexing import resolve_library_dir

    config = config or Config()
    try:
        environment = environment_from_config(config)
    except Exception as exc:
        return Check(
            name="Reference library",
            ok=False,
            detail=f"Cannot tell, because the OpenFOAM probe failed: {exc}",
            fix="Fix the OpenFOAM check first.",
        )

    if not environment.detected:
        return Check(
            name="Reference library",
            ok=False,
            detail="Cannot tell, because no OpenFOAM was detected.",
            fix="Fix the OpenFOAM check first.",
        )

    built = resolve_library_dir(environment)
    if built is None:
        return Check(
            name="Reference library",
            ok=False,
            detail=f"Nothing built for {environment.describe()}.",
            fix="foamagent index build",
        )

    return Check(name="Reference library", ok=True, detail=str(built))


def check_review_command() -> Check:
    """Is the harness that runs an independent review installed here?"""
    from foamagent.review.settings import load_settings
    from foamagent.review.settings import JUDGE_ROLE, REVIEWER_ROLE

    settings = load_settings()
    if not settings.command:
        return Check(
            name="Review command",
            ok=False,
            detail="No command is configured.",
            fix="foamagent config set review.command '[claude, -p]'",
            required=False,
        )

    executable = settings.command[0]
    if shutil.which(executable) is None:
        return Check(
            name="Review command",
            ok=False,
            detail=f"{executable!r} is not on PATH, so nothing would check a case here.",
            fix=(
                "Install that harness's CLI, or point review.command at one this machine "
                "has. Cases still run; the report says they were never checked."
            ),
            required=False,
        )

    reviewer = load_settings(role=REVIEWER_ROLE).model or "(the harness decides)"
    judge = load_settings(role=JUDGE_ROLE).model or "(the harness decides)"
    where = shutil.which(executable)
    return Check(
        name="Review command",
        ok=True,
        detail=f"{where}; reviewer on {reviewer}, judge on {judge}",
    )


def check_sandbox() -> Check:
    """Can a review run its own arithmetic?"""
    from foamagent.review.settings import load_settings
    from foamagent.review.sandbox import available

    settings = load_settings().sandbox
    reason = available(settings)
    if reason is not None:
        return Check(
            name="Review sandbox",
            ok=False,
            detail=reason,
            fix=(
                "Install Docker to let a review compute. Without it the review still runs "
                "and says which checks it could not make."
            ),
            required=False,
        )

    return Check(
        name="Review sandbox",
        ok=True,
        detail=f"docker, image {settings.image}, {settings.timeout_seconds}s per script",
    )


def check_harness_configuration(directory: Optional[Path] = None, config=None) -> Check:
    """Does the .mcp.json here agree with the settings in effect?

    `foamagent install` writes the environment it was run in into that file. A setting
    changed afterwards -- in a file, or in a different shell -- leaves the two disagreeing,
    and the server the harness starts uses the stale one.
    """
    from foamagent.config import Config, CONFIG_KEYS
    from foamagent.harness import SERVER_NAME

    directory = directory or Path.cwd()
    path = directory / MCP_CONFIG_FILENAME
    if not path.is_file():
        # Hermes Agent has no per-project MCP config -- `foamagent install hermes-agent`
        # writes foamagent-hermes.yaml instead, for the user to merge into their global
        # ~/.hermes/config.yaml by hand. Its presence is the only local evidence that a
        # Hermes setup was chosen on purpose; without this, doctor called this "no
        # .mcp.json" and pointed at `foamagent install claude-code` even for someone who
        # correctly never wrote one, which reads as a warning that never clears.
        hermes_yaml = directory / HERMES_CONFIG_FILENAME
        if hermes_yaml.is_file():
            return Check(
                name="Harness configuration",
                ok=True,
                detail=(
                    f"No {MCP_CONFIG_FILENAME} (expected for Hermes Agent); "
                    f"{hermes_yaml} was written by `foamagent install hermes-agent`. "
                    "Whether it is actually merged into ~/.hermes/config.yaml cannot be "
                    "checked from here."
                ),
                required=False,
            )
        return Check(
            name="Harness configuration",
            ok=False,
            detail=f"No {MCP_CONFIG_FILENAME} in {directory}.",
            fix="foamagent install claude-code   # or: foamagent install hermes-agent",
            required=False,
        )

    try:
        written = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Check(
            name="Harness configuration",
            ok=False,
            detail=f"{path} could not be read: {exc}",
            fix="foamagent install claude-code",
            required=False,
        )

    server = (written.get("mcpServers") or {}).get(SERVER_NAME)
    if not isinstance(server, dict):
        return Check(
            name="Harness configuration",
            ok=False,
            detail=f"{path} does not configure the {SERVER_NAME} server.",
            fix="foamagent install claude-code",
            required=False,
        )

    config = config or Config()
    baked = server.get("env") or {}
    current = {
        "FOAMAGENT_OPENFOAM_RUNTIME": config.openfoam_runtime,
        "FOAMAGENT_OPENFOAM_IMAGE": config.openfoam_image,
        "FOAMAGENT_OPENFOAM_BASHRC": config.openfoam_bashrc,
    }
    stale = [
        f"{key}={baked[key]!r} in the file, {current[key]!r} in effect"
        for key in current
        if key in baked and baked[key] != current[key]
    ]
    if stale:
        return Check(
            name="Harness configuration",
            ok=False,
            detail="; ".join(stale),
            fix=(
                "The file wins for the server the harness starts. Rerun `foamagent install`, "
                "or delete the env block from it and keep the settings in one place."
            ),
            required=False,
        )

    return Check(name="Harness configuration", ok=True, detail=str(path))


DOCTOR_REVIEW_TIMEOUT_SECONDS = 60
DOCTOR_TOKEN = "FOAMAGENT_DOCTOR_OK"


def _check_review_instructions(settings) -> Check:
    """Does the review command actually do what it is told, once started for real?"""
    import tempfile

    from foamagent.review.channel import run_audit

    with tempfile.TemporaryDirectory(prefix="foamagent-doctor-") as scratch:
        result = run_audit(
            f"Reply with exactly this one line and nothing else: {DOCTOR_TOKEN}",
            cwd=scratch,
            settings=settings,
        )

    if not result.ok:
        return Check(
            name="Review: follows instructions",
            ok=False,
            detail=result.detail or "produced no output",
            fix="Run review.command by hand with a trivial prompt and see what it does.",
        )
    reply = result.text.strip()
    if reply != DOCTOR_TOKEN:
        return Check(
            name="Review: follows instructions",
            ok=False,
            detail=f"Asked for {DOCTOR_TOKEN!r}, got {reply[:200]!r}",
            fix="review.prompt_separator or review.model_flag may be wrong for this harness.",
        )
    return Check(name="Review: follows instructions", ok=True, detail=f"Replied {DOCTOR_TOKEN!r} as asked")


def _check_review_sandbox(settings) -> Check:
    """Can a review actually run a script through the sandbox, not just claim to offer one?"""
    if not settings.offers_sandbox:
        return Check(
            name="Review: sandbox usable",
            ok=True,
            detail="not offered (no MCP config flag, or review.sandbox.runtime is not docker)",
        )

    import tempfile

    from foamagent.review.channel import run_audit

    with tempfile.TemporaryDirectory(prefix="foamagent-doctor-case-") as case_dir, \
            tempfile.TemporaryDirectory(prefix="foamagent-doctor-work-") as work_dir:
        result = run_audit(
            "Use run_script to compute 1 + 1 in Python. Reply with only the number it printed.",
            cwd=case_dir,
            work_dir=work_dir,
            settings=settings,
        )

    if not result.ok or "2" not in result.text:
        return Check(
            name="Review: sandbox usable",
            ok=False,
            detail=(result.detail or result.text or "no output")[:200],
            fix="Check Docker is reachable and review.sandbox.* is correct.",
        )
    return Check(name="Review: sandbox usable", ok=True, detail="run_script computed 1 + 1")


def run_review_checks() -> List[Check]:
    """Start the configured review harness for real and see what it does.

    `check_review_command` only confirms something is on PATH; a harness that starts but
    ignores `--model` passes that check and fails silently on the first real review. This
    starts it twice against scratch directories nothing depends on, bounded by a short
    timeout of its own so a harness that hangs does not turn a diagnostic into a half-hour
    wait.
    """
    import dataclasses

    from foamagent.review.settings import load_settings
    from foamagent.review.channel import ChannelUnavailable, resolve_command

    settings = load_settings()
    try:
        resolve_command(settings)
    except ChannelUnavailable as exc:
        detail = str(exc)
        return [
            Check(name=name, ok=False, detail=detail, fix="Fix the Review command check above first.")
            for name in (
                "Review: follows instructions",
                "Review: sandbox usable",
            )
        ]

    settings = dataclasses.replace(settings, timeout_seconds=DOCTOR_REVIEW_TIMEOUT_SECONDS)
    return [
        _check_review_instructions(settings),
        _check_review_sandbox(settings),
    ]


def run_checks(directory: Optional[Path] = None) -> List[Check]:
    """Every check, in the order a first-time user meets them."""
    from foamagent.config import Config

    config = Config()
    return [
        check_openfoam(config),
        check_library(config),
        check_review_command(),
        check_sandbox(),
        check_harness_configuration(directory, config),
    ]


__all__ = [
    "Check",
    "check_harness_configuration",
    "check_library",
    "check_openfoam",
    "check_review_command",
    "check_sandbox",
    "run_checks",
    "run_review_checks",
]
