"""The tools that need no model.

Everything here either measures the machine or manipulates files: what OpenFOAM is
installed, where its tutorials were indexed, start a run, ask how it is going, read a log,
check a case, name the failures in it. The judgement -- which solver, which boundary
condition, what to change after a failure -- belongs to whichever agent is calling, and
this module deliberately holds none of it.

That split is the point of the host_delegate arrangement: the harness already has a model,
and a server that also had one would be inference the user cannot see, configure, or pay
for knowingly.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from foamagent.logger import get_logger

logger = get_logger(__name__)

MAX_READ_BYTES = 400_000


# ============================================================================
# describe_environment
# ============================================================================


class EnvironmentResponse(BaseModel):
    """What OpenFOAM is here, and where its reference material lives."""

    detected: bool = Field(description="False when no OpenFOAM could be probed; the rest is then a Foundation v10 assumption")
    fork: str = Field(description="foundation or esi")
    version: str = Field(description="10, v2406, ...")
    runtime: str = Field(description="Where solvers run: native or docker")
    solver_count: int = Field(description="How many applications $FOAM_APPBIN holds")
    solvers: List[str] = Field(description="Their names")
    tutorials: str = Field(description="$FOAM_TUTORIALS in the environment")
    library: Dict[str, str] = Field(
        description="Paths of the reference library built from this installation. Empty "
                    "when `foamagent index build` has not been run"
    )
    notes: List[str] = Field(default_factory=list, description="Anything the caller should know before starting")


async def describe_environment(ctx=None) -> EnvironmentResponse:
    """Report the OpenFOAM installation and the reference material built from it.

    Call this first. It tells you which solvers exist (do not name one that does not), and
    where the tutorial catalogue is. Read that catalogue before authoring a case: it lists
    every tutorial this installation ships, and the directory holding each one.
    """
    from foamagent.config import Config
    from foamagent.environment import environment_from_config
    from foamagent.indexing import resolve_library_dir
    from foamagent.indexing.library import library_paths

    config = Config()
    environment = environment_from_config(config)

    notes: List[str] = []
    library: Dict[str, str] = {}

    index_dir = resolve_library_dir(environment if environment.detected else None)
    if index_dir is None:
        notes.append(
            "No reference library has been built for this installation. Run "
            "`foamagent index build` to create one from its own tutorials."
        )
    else:
        library = {key: str(value) for key, value in library_paths(index_dir).items()}
        notes.append(
            f"Read {library['catalog']} to choose a tutorial to work from, then open only "
            "that case directory."
        )

    if not environment.detected:
        notes.append(
            "OpenFOAM could not be probed, so fork and version below are the historical "
            "default rather than a measurement. Source OpenFOAM, or set "
            "FOAMAGENT_OPENFOAM_RUNTIME=docker with an image that has it."
        )

    return EnvironmentResponse(
        detected=environment.detected,
        fork=environment.fork,
        version=environment.version,
        runtime=config.openfoam_runtime,
        solver_count=len(environment.solvers),
        solvers=list(environment.solvers),
        tutorials=environment.tutorials,
        library=library,
        notes=notes,
    )


# ============================================================================
# run_start / run_status / run_tail_log / run_stop
# ============================================================================


class RunStartRequest(BaseModel):
    case_dir: str = Field(description="Directory holding the case and its Allrun script")
    timeout: int = Field(default=3600, description="Seconds after which the run is killed")
    clean: bool = Field(default=True, description="Remove previous logs and time directories first")


class RunStartResponse(BaseModel):
    run_id: str
    state: str
    case_dir: str
    message: str


async def run_start(request: RunStartRequest, ctx=None) -> RunStartResponse:
    """Start the case's Allrun script and return immediately.

    The run continues in the background: poll it with run_status and watch it with
    run_tail_log. Nothing here waits for the solver, so no client timeout is involved.
    """
    from foamagent.services.run_async import get_run_registry

    record = get_run_registry().start(
        request.case_dir, timeout=float(request.timeout), clean=request.clean
    )
    if ctx is not None:
        await ctx.info(f"Run {record.run_id} started in {record.case_dir}")

    return RunStartResponse(
        run_id=record.run_id,
        state=record.state,
        case_dir=record.case_dir,
        message="Started. Poll run_status with this run_id; run_tail_log shows the live log.",
    )


class RunStatusRequest(BaseModel):
    run_id: str = Field(default="", description="Identifier from run_start")
    case_dir: str = Field(default="", description="Alternative to run_id: the case's most recent run")


class RunStatusResponse(BaseModel):
    run_id: str
    state: str = Field(description="running, succeeded, failed, timed_out or stopped")
    case_dir: str
    seconds: float
    returncode: Optional[int] = None
    errors: List[str] = Field(default_factory=list)
    detail: str = ""
    logs: List[str] = Field(default_factory=list, description="Log files present, newest first")


async def run_status(request: RunStatusRequest, ctx=None) -> RunStatusResponse:
    """Report how a run is going. Returns at once whether or not the run has finished."""
    from foamagent.services.run_async import get_run_registry, list_logs

    registry = get_run_registry()
    record = registry.get(request.run_id) if request.run_id else None
    if record is None and request.case_dir:
        record = registry.latest(request.case_dir)

    if record is None:
        raise ValueError(
            "No such run. Pass the run_id returned by run_start, or a case_dir that has "
            "been run at least once."
        )

    return RunStatusResponse(
        run_id=record.run_id,
        state=record.state,
        case_dir=record.case_dir,
        seconds=round(record.seconds, 1),
        returncode=record.returncode,
        errors=record.errors,
        detail=record.detail,
        logs=list_logs(record.case_dir),
    )


class RunTailRequest(BaseModel):
    case_dir: str = Field(description="Case directory to read a log from")
    name: str = Field(default="latest", description="Log file name, or 'latest' for the most recently written")
    lines: int = Field(default=50, description="How many trailing lines to return")


class RunTailResponse(BaseModel):
    name: str
    text: str
    logs: List[str] = Field(description="Every log present, newest first")


async def run_tail_log(request: RunTailRequest, ctx=None) -> RunTailResponse:
    """Return the tail of a run's log, the way `tail -f` would show it."""
    from foamagent.services.run_async import list_logs, tail_log

    text = tail_log(request.case_dir, name=request.name, lines=request.lines)
    logs = list_logs(request.case_dir)
    return RunTailResponse(name=request.name, text=text, logs=logs)


class RunStopRequest(BaseModel):
    run_id: str = Field(description="Identifier from run_start")


class RunStopResponse(BaseModel):
    run_id: str
    state: str
    message: str


async def run_stop(request: RunStopRequest, ctx=None) -> RunStopResponse:
    """Stop a running case. The process group is killed, and under docker the container."""
    from foamagent.services.run_async import get_run_registry

    record = get_run_registry().stop(request.run_id)
    if record is None:
        raise ValueError(f"No such run: {request.run_id}")

    return RunStopResponse(
        run_id=record.run_id,
        state=record.state,
        message="Stop requested." if not record.done else f"Already {record.state}.",
    )


# ============================================================================
# validate_case / classify_errors
# ============================================================================


class ValidateRequest(BaseModel):
    case_dir: str = Field(description="Case directory to check")


class ValidateResponse(BaseModel):
    ok: bool = Field(description="True when nothing of severity 'error' was found")
    application: str = Field(description="The solver named in controlDict")
    mesh_patches: List[str] = Field(description="Patch names the mesh defines")
    fields: List[str] = Field(description="Files present in 0/")
    findings: List[Dict[str, str]] = Field(description="severity, where, message")


async def validate_case(request: ValidateRequest, ctx=None) -> ValidateResponse:
    """Check a case for the mistakes that cost a whole run to discover.

    Missing dictionaries, a solver this installation does not have, and field files whose
    patch names disagree with the mesh. Run this before run_start; it needs no OpenFOAM and
    returns in milliseconds.
    """
    from foamagent.config import Config
    from foamagent.environment import environment_from_config
    from foamagent.services.validate import validation_report

    environment = environment_from_config(Config())
    report = validation_report(
        request.case_dir, installed_solvers=environment.solvers if environment.detected else None
    )
    return ValidateResponse(**report)


class ClassifyRequest(BaseModel):
    case_dir: str = Field(description="Case directory whose logs to read")
    logs: List[str] = Field(default_factory=list, description="Specific log names; default is every log.* plus Allrun.err")


class ClassifyResponse(BaseModel):
    count: int
    categories: List[str]
    findings: List[Dict[str, str]] = Field(description="log, category, message, hint")


async def classify_errors(request: ClassifyRequest, ctx=None) -> ClassifyResponse:
    """Name the failures in a case's logs: category, the line that said so, and what it means."""
    from foamagent.services.diagnose import diagnosis_report

    report = diagnosis_report(request.case_dir, logs=request.logs or None)
    return ClassifyResponse(**report)


# ============================================================================
# Case files, for clients that cannot open one themselves
# ============================================================================


class ListCaseRequest(BaseModel):
    case_dir: str = Field(description="Directory to list")


class ListCaseResponse(BaseModel):
    case_dir: str
    files: List[Dict[str, Any]] = Field(description="path (relative), bytes")


async def list_case(request: ListCaseRequest, ctx=None) -> ListCaseResponse:
    """List a case's files with their sizes."""
    root = Path(os.path.abspath(request.case_dir))
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".foamagent" not in path.parts:
            files.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size})
    return ListCaseResponse(case_dir=str(root), files=files)


class ReadCaseRequest(BaseModel):
    case_dir: str = Field(description="Case directory")
    path: str = Field(description="File to read, relative to the case directory")


class ReadCaseResponse(BaseModel):
    path: str
    text: str
    truncated: bool


def _inside(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise ValueError(f"{relative} is outside the case directory")
    return target


async def read_case(request: ReadCaseRequest, ctx=None) -> ReadCaseResponse:
    """Read one file from a case. For clients with no filesystem access of their own."""
    root = Path(os.path.abspath(request.case_dir))
    target = _inside(root, request.path)
    if not target.is_file():
        raise ValueError(f"No such file: {request.path}")

    text = target.read_text(encoding="utf-8", errors="ignore")
    truncated = len(text) > MAX_READ_BYTES
    return ReadCaseResponse(path=request.path, text=text[:MAX_READ_BYTES], truncated=truncated)


class WriteCaseRequest(BaseModel):
    case_dir: str = Field(description="Case directory")
    path: str = Field(description="File to write, relative to the case directory")
    text: str = Field(description="Its complete contents")


class WriteCaseResponse(BaseModel):
    path: str
    bytes: int


async def write_case(request: WriteCaseRequest, ctx=None) -> WriteCaseResponse:
    """Write one file into a case, creating directories as needed."""
    root = Path(os.path.abspath(request.case_dir))
    target = _inside(root, request.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(request.text, encoding="utf-8")

    if target.name in ("Allrun", "Allclean") or target.suffix == ".sh":
        target.chmod(0o755)

    return WriteCaseResponse(path=request.path, bytes=len(request.text.encode("utf-8")))


# ============================================================================
# visualize
# ============================================================================


class VisualizeRequest(BaseModel):
    case_dir: str = Field(description="Case directory holding a finished run")
    quantity: str = Field(default="velocity", description="Field to colour by, e.g. velocity or pressure")


class VisualizeResponse(BaseModel):
    success: bool
    image: str = Field(description="Path of the PNG, empty when nothing was produced")
    field: str = Field(description="The field actually rendered")
    errors: List[str] = Field(default_factory=list)


async def visualize(request: VisualizeRequest, ctx=None) -> VisualizeResponse:
    """Render a screenshot of the results with PyVista.

    Uses a fixed template, so this needs no model. If you want a different view, write
    your own PyVista script and run it; the template is for the common case of "show me
    the field".
    """
    from foamagent.services.visualization import DEFAULT_OUTPUT_PNG, visualize_case

    result = await asyncio.to_thread(
        visualize_case,
        request.case_dir,
        request.quantity,
        output_png=DEFAULT_OUTPUT_PNG,
    )

    if ctx is not None and not result.success:
        await ctx.warning("Visualization produced no image: " + "; ".join(result.error_logs[-1:]))

    return VisualizeResponse(
        success=result.success,
        image=result.output_image or "",
        field=result.field_name,
        errors=result.error_logs,
    )


# ============================================================================
# search_tutorials
# ============================================================================


class SearchRequest(BaseModel):
    query: str = Field(description="What the case is: solver, physics, geometry")
    topk: int = Field(default=5, description="How many cases to return")


class SearchResponse(BaseModel):
    catalog: str = Field(description="Path of the full catalogue, if one is built")
    matches: List[Dict[str, str]] = Field(description="case, solver, domain, path")


async def search_tutorials(request: SearchRequest, ctx=None) -> SearchResponse:
    """Find tutorial cases by word match over the catalogue.

    A convenience for clients that cannot read the catalogue file themselves. If yours can,
    read it instead: it is a table of every case, and choosing from it is a better use of
    your judgement than a word count is.
    """
    from foamagent.indexing import resolve_library_dir
    from foamagent.indexing.library import CATALOG_FILE, catalog_search

    index_dir = resolve_library_dir()
    if index_dir is None:
        raise ValueError(
            "No reference library is built. Run `foamagent index build` first."
        )

    matches = catalog_search(index_dir / CATALOG_FILE, request.query, topk=request.topk)
    return SearchResponse(catalog=str(index_dir / CATALOG_FILE), matches=matches)


# ============================================================================
# Registration
# ============================================================================

TOOLS = (
    ("describe_environment", describe_environment),
    ("run_start", run_start),
    ("run_status", run_status),
    ("run_tail_log", run_tail_log),
    ("run_stop", run_stop),
    ("validate_case", validate_case),
    ("classify_errors", classify_errors),
    ("visualize", visualize),
    ("list_case", list_case),
    ("read_case", read_case),
    ("write_case", write_case),
    ("search_tutorials", search_tutorials),
)


def register(mcp) -> None:
    """Add every deterministic tool to a FastMCP server."""
    for name, function in TOOLS:
        mcp.tool(name=name)(function)


__all__ = [name for name, _ in TOOLS] + ["TOOLS", "register"]
