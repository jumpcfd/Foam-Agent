"""Running the audit: a model of the user's own, in a process of its own.

This server has no API key and does not want one. The model that reviews a case is a
non-interactive session of the harness the user already runs, started here as a
subprocess with a read-only tool set. Its stdout is the document.

MCP sampling would have been the tidier route and is not available: Claude Code does not
implement it (anthropics/claude-code#1785, still open as of 2026-07), and a sampling call
produces one block of text with no tools -- which would leave the reviewer unable to open
the case it is reviewing or check a number against the literature.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from foamagent.logger import get_logger
from foamagent.review.settings import ChannelSettings, config_file, load_settings

logger = get_logger(__name__)


class ChannelUnavailable(RuntimeError):
    """The configured command cannot be run here."""


@dataclass(frozen=True)
class ChannelResult:
    """What one audit run produced."""

    ok: bool
    text: str
    detail: str = ""

    @property
    def failed(self) -> bool:
        return not self.ok


def resolve_command(settings: Optional[ChannelSettings] = None) -> List[str]:
    """Return the command that starts an audit, or raise if it cannot be started.

    Checked before anything is written, so that an unconfigured machine produces one clear
    document rather than a half-finished review.
    """
    settings = settings or load_settings()
    if not settings.command:
        raise ChannelUnavailable(
            f"No review command is configured. Set review.command in {config_file()}."
        )

    executable = settings.command[0]
    if shutil.which(executable) is None:
        raise ChannelUnavailable(
            f"The review command {executable!r} is not on PATH. Install it, or set "
            f"review.command in {config_file()} to a harness this machine has."
        )
    return list(settings.command)


def unavailable_document(reason: str, task: str) -> str:
    """The document returned when no review could be run.

    A review that did not happen is reported as a document like any other, because the
    alternative -- an error the caller can swallow -- is how an unchecked case comes to
    look like a checked one.
    """
    return (
        f"# {task}: not carried out\n\n"
        f"{reason}\n\n"
        "No independent check of this case has been made. Tell the user this before "
        "presenting any result, and treat the case as unreviewed.\n"
    )


def run_audit(
    prompt: str,
    *,
    cwd: Optional[str] = None,
    settings: Optional[ChannelSettings] = None,
) -> ChannelResult:
    """Run one audit and return its text.

    The subprocess inherits no case state beyond the path in the prompt, and is given no
    write tools, so the worst a failed run costs is the time it took.

    ``cwd`` is the case directory. Starting the review there rather than in the server's
    own working directory keeps its attention on the case: a review started in the
    repository will read the repository, which is not what it was asked about.
    """
    settings = settings or load_settings()
    resolve_command(settings)
    argv = settings.argv(prompt)

    logger.info("Starting an independent review: %s", " ".join(argv[:-1]))

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=settings.timeout_seconds,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return ChannelResult(
            ok=False,
            text="",
            detail=f"The review did not finish within {settings.timeout_seconds}s.",
        )
    except OSError as exc:
        return ChannelResult(ok=False, text="", detail=f"Could not start the review: {exc}")

    text = (completed.stdout or "").strip()
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()[:1000] or f"exit code {completed.returncode}"
        return ChannelResult(ok=False, text=text, detail=detail)
    if not text:
        return ChannelResult(ok=False, text="", detail="The review produced no output.")

    return ChannelResult(ok=True, text=text)
