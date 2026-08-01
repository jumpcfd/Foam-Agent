"""The one tool a review is given beyond reading and searching.

`run_script` runs Python against the case under review. The case is mounted read-only and
there is no network, so a script can measure the case and nothing else — including when the
script was written at the suggestion of something the review read in a log file.

Which case, and where the script is kept, are not parameters. They arrive in the
environment of this process, which the server sets when it starts the review, so a review
cannot point the tool at a different directory than the one it was asked about.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from foamagent.logger import get_logger
from foamagent.review import sandbox

logger = get_logger(__name__)

CASE_DIR_ENV = "FOAMAGENT_SANDBOX_CASE_DIR"
WORK_DIR_ENV = "FOAMAGENT_SANDBOX_WORK_DIR"


class ScriptRequest(BaseModel):
    script: str = Field(
        description=(
            "Python source. It runs with the case mounted read-only at /case and a writable "
            "/work as the working directory. Print what you want to see; there is no network "
            "and only the standard library."
        )
    )


class ScriptResponse(BaseModel):
    ok: bool = Field(description="True when the script ran and exited zero")
    exit_code: int = Field(default=0)
    stdout: str = Field(default="")
    stderr: str = Field(default="")
    script_file: str = Field(default="", description="Where the script was kept, inside the case")
    available: bool = Field(description="False when no script could be run at all; read `detail`")
    detail: str = Field(default="")


def _target() -> tuple[Optional[str], Optional[Path]]:
    case_dir = os.getenv(CASE_DIR_ENV) or None
    work = os.getenv(WORK_DIR_ENV) or None
    return case_dir, Path(work) if work else None


async def run_script(request: ScriptRequest, ctx=None) -> ScriptResponse:
    """Run a Python script over the case you are reviewing.

    Use it for the arithmetic: sum a mass balance across the boundary patches, read the
    residual history out of the solver log and say where it stopped falling, interpolate a
    velocity profile and compare it with published values you have looked up.

    The case is at `/case`, read-only. The working directory `/work` is writable and is
    kept with the case, so what you computed can be checked later. Only the Python standard
    library is available, and there is no network — look things up with your own web tools
    and put the numbers in the script.

    A number you calculated here is worth more in a finding than a number you remembered.
    If this returns `available: false`, say in your findings which checks you could not
    make.
    """
    case_dir, work = _target()
    if not case_dir or work is None:
        return ScriptResponse(
            ok=False,
            available=False,
            detail=(
                "This server was started without a case to work on, so no script can be run. "
                "Report the checks you could not make."
            ),
        )

    if ctx is not None:
        await ctx.info(f"Running a script against {case_dir}.")

    result = await asyncio.to_thread(
        sandbox.run_script, request.script, case_dir=case_dir, destination=work
    )

    if result.detail and not result.script_file:
        # Nothing ran and nothing was written: the sandbox itself is not available.
        logger.warning("%s", result.detail)
        if ctx is not None:
            await ctx.warning(result.detail)
        return ScriptResponse(ok=False, available=False, detail=result.detail)

    return ScriptResponse(
        ok=result.ok,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        script_file=result.script_file,
        available=True,
        detail=result.detail,
    )


TOOLS = (("run_script", run_script),)


def register(mcp) -> None:
    """Add the script tool to a FastMCP server."""
    for name, function in TOOLS:
        mcp.tool(name=name)(function)


__all__ = ["CASE_DIR_ENV", "TOOLS", "WORK_DIR_ENV", "register", "run_script"]
