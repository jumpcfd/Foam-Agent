"""Tests for the MCP tools' use of the shared case state.

The tools are plain async functions behind the FastMCP decorator, so they can be called
directly with a stand-in context. Everything that would need a model, an index or a running
OpenFOAM is replaced.
"""

import asyncio

import pytest

from foamagent.case_state import CaseState, load_case_state, save_case_state
from foamagent.mcp import fastmcp_server as server


class FakeContext:
    """Records what a tool reported instead of sending it to a client."""

    def __init__(self):
        self.messages = {"info": [], "warning": [], "error": [], "debug": []}

    async def info(self, message):
        self.messages["info"].append(message)

    async def warning(self, message):
        self.messages["warning"].append(message)

    async def error(self, message):
        self.messages["error"].append(message)

    async def debug(self, message):
        self.messages["debug"].append(message)

    async def report_progress(self, current, total, message=None):
        pass


@pytest.fixture
def case_dir(tmp_path):
    (tmp_path / "system").mkdir()
    return tmp_path


@pytest.fixture
def stubbed_review(monkeypatch):
    """Replace review's collaborators and record the retrieval arguments."""
    calls = {}

    def fake_retrieve_references(**kwargs):
        calls["retrieve_references"] = kwargs
        return ("tutorial reference", None, None, None, None)

    class FakeFoamFiles:
        list_foamfile = []

    def fake_read_case_foamfiles(case_dir, dir_structure=None):
        return FakeFoamFiles()

    def fake_review_error_logs(**kwargs):
        calls["review_error_logs"] = kwargs
        return ("analysis text", [])

    monkeypatch.setattr(server, "retrieve_references", fake_retrieve_references)
    monkeypatch.setattr(server, "review_error_logs", fake_review_error_logs)
    monkeypatch.setattr("foamagent.utils.read_case_foamfiles", fake_read_case_foamfiles)

    class FakeConfig:
        searchdocs = 2

    monkeypatch.setattr(server, "get_config", lambda: FakeConfig())
    return calls


def _review(case_dir, ctx, *, errors=None, user_requirement="run the case"):
    request = server.ReviewRequest(
        case_dir=str(case_dir),
        errors=errors if errors is not None else ["some error"],
        user_requirement=user_requirement,
    )
    return asyncio.run(server.review(request, ctx))


def test_review_retrieves_references_for_the_recorded_solver(case_dir, stubbed_review):
    save_case_state(
        case_dir,
        CaseState(
            case_name="cavity",
            case_solver="icoFoam",
            case_domain="incompressible",
            case_category="lidDrivenCavity",
        ),
    )

    response = _review(case_dir, FakeContext())

    assert response.analysis == "analysis text"
    args = stubbed_review["retrieve_references"]
    assert args["case_solver"] == "icoFoam"
    assert args["case_domain"] == "incompressible"
    assert args["case_category"] == "lidDrivenCavity"
    assert args["case_name"] == "cavity"


def test_review_does_not_use_the_old_hardcoded_defaults(case_dir, stubbed_review):
    """The defect this replaced: every case was reviewed as a simpleFoam fluid tutorial."""
    save_case_state(case_dir, CaseState(case_solver="interFoam", case_domain="multiphase"))

    _review(case_dir, FakeContext())

    args = stubbed_review["retrieve_references"]
    assert args["case_solver"] != "simpleFoam"
    assert args["case_domain"] != "fluid"


def test_review_warns_and_falls_back_when_no_state_was_written(case_dir, stubbed_review):
    ctx = FakeContext()

    _review(case_dir, ctx)

    assert any("No Foam-Agent state found" in m for m in ctx.messages["warning"])
    args = stubbed_review["retrieve_references"]
    assert args["case_solver"] == "simpleFoam"
    assert args["case_name"] == case_dir.name


def test_review_falls_back_to_the_recorded_requirement(case_dir, stubbed_review):
    save_case_state(
        case_dir,
        CaseState(case_solver="icoFoam", user_requirement="recorded requirement"),
    )

    _review(case_dir, FakeContext(), user_requirement="")

    assert stubbed_review["review_error_logs"]["user_requirement"] == "recorded requirement"


def test_review_counts_the_fix_attempt(case_dir, stubbed_review):
    save_case_state(case_dir, CaseState(case_solver="icoFoam", loop_count=1))

    _review(case_dir, FakeContext())

    state = load_case_state(case_dir)
    assert state is not None
    assert state.loop_count == 2
    assert state.case_solver == "icoFoam"


def test_review_rejects_a_missing_case_directory(tmp_path, stubbed_review):
    request = server.ReviewRequest(
        case_dir=str(tmp_path / "absent"), errors=["e"], user_requirement="r"
    )
    with pytest.raises(ValueError, match="does not exist"):
        asyncio.run(server.review(request, FakeContext()))


def test_visualization_reports_the_artifact_the_service_produced(case_dir, monkeypatch):
    from foamagent.services.visualization import VisualizationResult

    def fake_visualize_case(path, quantity, *, max_loop, output_png):
        assert output_png == "visualization.png"
        return VisualizationResult(
            success=True,
            field_name="U",
            output_image=str(case_dir / output_png),
            script="print('x')",
            used="deterministic_template",
        )

    monkeypatch.setattr(server, "visualize_case", fake_visualize_case)

    request = server.VisualizationRequest(case_dir=str(case_dir), quantity="velocity")
    response = asyncio.run(server.visualization(request, FakeContext()))

    assert response.artifacts == [str(case_dir / "visualization.png")]
    assert response.script == "print('x')"


def test_visualization_reports_no_artifact_on_failure(case_dir, monkeypatch):
    from foamagent.services.visualization import VisualizationResult

    def fake_visualize_case(path, quantity, *, max_loop, output_png):
        return VisualizationResult(success=False, field_name="U", error_logs=["nope"])

    monkeypatch.setattr(server, "visualize_case", fake_visualize_case)

    ctx = FakeContext()
    request = server.VisualizationRequest(case_dir=str(case_dir), quantity="velocity")
    response = asyncio.run(server.visualization(request, ctx))

    assert response.artifacts == []
    assert any("no artifact" in m for m in ctx.messages["warning"])
