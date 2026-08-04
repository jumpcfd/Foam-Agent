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
    from foamagent.review import load_settings
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
    from foamagent.review import load_settings
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
        return Check(
            name="Harness configuration",
            ok=False,
            detail=f"No {MCP_CONFIG_FILENAME} in {directory}.",
            fix="foamagent install claude-code",
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
]
