"""The tools that need no model.

Everything here measures the machine or the case: what OpenFOAM is installed, where its
tutorials were indexed, whether a case is well-formed before it runs, a picture of a
finished one. The judgement -- which solver, which boundary condition, what to change
after a failure, and running the case itself -- belongs to whichever agent is calling, on
its own native tools (file read/write, a shell): a harness capable enough to be worth
running already has those, and duplicating them here as MCP tools was dead weight nobody
reached for in practice, not a safety net. See git history for the run_start/run_status/
run_tail_log/run_stop/classify_errors/list_case/read_case/write_case tools this module
used to carry.

That split is the point of the host_delegate arrangement: the harness already has a model,
and a server that also had one would be inference the user cannot see, configure, or pay
for knowingly.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List

from pydantic import BaseModel, Field

from foamagent.logger import get_logger

logger = get_logger(__name__)


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
    knowledge_dir: str = Field(description="Where the OpenFOAM know-how files live")
    knowledge: Dict[str, str] = Field(
        description="Every .md file in knowledge_dir, mapped to its first line"
    )
    notes: List[str] = Field(default_factory=list, description="Anything the caller should know before starting")


async def describe_environment(ctx=None) -> EnvironmentResponse:
    """Report the OpenFOAM installation and the reference material built from it.

    Call this first. It tells you which solvers exist (do not name one that does not), and
    where the tutorial catalogue is. Read that catalogue before authoring a case: it lists
    every tutorial this installation ships, and the directory holding each one.
    """
    from foamagent import knowledge
    from foamagent.config import Config
    from foamagent.environment import environment_from_config
    from foamagent.indexing import resolve_library_dir
    from foamagent.indexing.library import library_paths

    config = Config()
    # The only tool here slow enough to matter: on its first call for a given backend this
    # probes OpenFOAM by starting a container, which can take a few seconds and would
    # otherwise hold the event loop other tool calls are waiting on. Cached after that (see
    # environment.detect_environment), so every later call returns as fast as the rest.
    environment = await asyncio.to_thread(environment_from_config, config)

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

    knowledge_dir = knowledge.active_dir()
    notes.append(
        "knowledge lists what each file in knowledge_dir is for -- how to classify a case "
        "and build it in order, the mistakes that recur, what a failing log line means. "
        "Read the ones that apply before writing anything. It is the user's to edit and "
        "extend: drop a .md file into knowledge_dir and it shows up here too."
    )
    if knowledge_dir == knowledge.bundled_dir():
        notes.append(
            f"knowledge_dir is the bundled copy; `foamagent install` seeds an editable one "
            f"at {knowledge.user_dir()}."
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
        knowledge_dir=str(knowledge_dir),
        knowledge=knowledge.index(knowledge_dir),
        notes=notes,
    )


# ============================================================================
# validate_case
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
    patch names disagree with the mesh. Run this before running the case; it needs no
    OpenFOAM and returns in milliseconds.
    """
    from foamagent.config import Config
    from foamagent.environment import environment_from_config
    from foamagent.services.validate import validation_report

    environment = environment_from_config(Config())
    report = validation_report(
        request.case_dir, installed_solvers=environment.solvers if environment.detected else None
    )
    return ValidateResponse(**report)


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
    ("validate_case", validate_case),
    ("visualize", visualize),
    ("search_tutorials", search_tutorials),
)


def register(mcp) -> None:
    """Add every deterministic tool to a FastMCP server."""
    for name, function in TOOLS:
        mcp.tool(name=name)(function)


__all__ = [name for name, _ in TOOLS] + ["TOOLS", "register"]
