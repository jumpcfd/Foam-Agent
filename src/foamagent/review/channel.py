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

import contextlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from foamagent.logger import get_logger
from foamagent.review.settings import (
    SANDBOX_SERVER,
    ChannelSettings,
    config_file,
    load_settings,
)

logger = get_logger(__name__)

SANDBOX_PROFILE_ARGS = ["--profile", "sandbox"]


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


def sandbox_config(case_dir: str, work_dir: str | Path) -> dict:
    """The server configuration handed to one review.

    One server, one tool, one case. The case and the work directory are set here, in the
    environment of the process the review talks to, rather than passed as tool arguments:
    a review can then ask for a calculation, but not for a calculation somewhere else.
    """
    from foamagent.mcp.sandbox import CASE_DIR_ENV, WORK_DIR_ENV
    from foamagent.harness import server_command

    server = dict(server_command())
    server["args"] = list(server["args"]) + SANDBOX_PROFILE_ARGS
    server["env"] = {
        CASE_DIR_ENV: str(case_dir),
        WORK_DIR_ENV: str(work_dir),
    }
    return {"mcpServers": {SANDBOX_SERVER: server}}


@contextlib.contextmanager
def _sandbox_config_file(
    case_dir: Optional[str], work_dir: Optional[str | Path], settings: ChannelSettings
) -> Iterator[Optional[Path]]:
    """Write the review's server configuration, and take it away again afterwards."""
    if work_dir is None or case_dir is None or not settings.offers_sandbox:
        yield None
        return

    with tempfile.TemporaryDirectory(prefix="foamagent-review-") as directory:
        path = Path(directory) / "mcp.json"
        path.write_text(json.dumps(sandbox_config(case_dir, work_dir), indent=2), encoding="utf-8")
        yield path


@contextlib.contextmanager
def _case_copy(cwd: Optional[str], settings: ChannelSettings) -> Iterator[Optional[str]]:
    """The directory the review actually runs in: a throwaway copy for a harness that has no
    way to deny it write access, the real one otherwise.

    A harness whose ``copy_case_dir`` is set (see the hermes-agent profile) has no per-tool
    or per-invocation way to grant read without also granting write, so instead of trusting
    it not to write, it is never handed anything writing could damage. The copy is a plain
    ``shutil.copytree`` -- deliberately not filtered, since the review may need to read
    anything a case-local checker or a request could have asked about -- and is removed
    unconditionally afterwards regardless of what the review did to it.
    """
    if cwd is None or not settings.copy_case_dir:
        yield cwd
        return

    with tempfile.TemporaryDirectory(prefix="foamagent-review-case-") as directory:
        copy_path = Path(directory) / "case"
        shutil.copytree(cwd, copy_path)
        yield str(copy_path)


def run_audit(
    prompt: str,
    *,
    cwd: Optional[str] = None,
    work_dir: Optional[str | Path] = None,
    settings: Optional[ChannelSettings] = None,
    role: Optional[str] = None,
) -> ChannelResult:
    """Run one audit and return its text.

    The subprocess inherits no case state beyond the path in the prompt, and is given no
    write tools, so the worst a failed run costs is the time it took.

    ``cwd`` is the case directory. Starting the review there rather than in the server's
    own working directory keeps its attention on the case: a review started in the
    repository will read the repository, which is not what it was asked about. For a harness
    that cannot be trusted not to write there (``settings.copy_case_dir``), the review
    actually starts in a throwaway copy instead -- see ``_case_copy``.

    ``work_dir`` turns on the sandbox: the review is handed a server of its own that can
    run Python against the case, with the case mounted read-only, and keeps what it ran in
    that directory. Without it the review can still read and search, as before.

    ``role`` is "reviewer" or "judge", and picks up ``review.<role>.model`` when the
    settings name one. It is ignored when ``settings`` is passed in, since those have
    already been resolved for whatever role the caller meant.
    """
    settings = settings or load_settings(role=role)
    resolve_command(settings)

    with _case_copy(cwd, settings) as review_cwd, \
            _sandbox_config_file(review_cwd, work_dir, settings) as mcp_config:
        return _run(prompt, cwd=review_cwd, settings=settings, mcp_config=mcp_config)


def _run(
    prompt: str,
    *,
    cwd: Optional[str],
    settings: ChannelSettings,
    mcp_config: Optional[Path],
) -> ChannelResult:
    argv = settings.argv(prompt, mcp_config=mcp_config)

    logger.info("Starting an independent review: %s", " ".join(argv[:-1]))

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=settings.timeout_seconds,
            # capture_output only redirects stdout and stderr; stdin stays inherited. Over
            # stdio transport that inherited descriptor is the JSON-RPC pipe from the
            # harness, and a review started on it reads the pipe: it blocks waiting for an
            # EOF that a live connection never sends, and it swallows the requests meant
            # for this server, which then go unanswered until the client gives up on them.
            stdin=subprocess.DEVNULL,
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
