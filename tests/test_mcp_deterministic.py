"""The deterministic tools, exercised through a real MCP client.

FastMCP's in-memory transport means the schemas, the serialisation and the tool names are
all under test, not just the Python functions behind them. No OpenFOAM, no container and no
model: the execution backend is a stub and the environment probe is fed fixed output.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastmcp import Client

from foamagent.environment import OpenFOAMEnvironment
from foamagent.mcp import deterministic, fastmcp_server as server


@pytest.fixture
def case_dir(tmp_path):
    (tmp_path / "system").mkdir()
    (tmp_path / "0").mkdir()
    (tmp_path / "system" / "controlDict").write_text(
        "application icoFoam;\nendTime 1;\ndeltaT 0.1;\nwriteInterval 1;\n", encoding="utf-8"
    )
    (tmp_path / "system" / "fvSchemes").write_text("ddtSchemes { }\n", encoding="utf-8")
    (tmp_path / "system" / "fvSolution").write_text("solvers { }\n", encoding="utf-8")
    (tmp_path / "Allrun").write_text("#!/bin/sh\nblockMesh\n", encoding="utf-8")
    return tmp_path


def call(tool: str, arguments: dict) -> dict:
    """Call a tool and return its response as plain data, the way a client sees it."""
    async def main():
        async with Client(server.mcp) as client:
            result = await client.call_tool(tool, arguments)
            # structured_content is the JSON the client receives; result.data is the same
            # thing behind a generated attribute wrapper.
            return result.structured_content
    return asyncio.run(main())


# ---------------------------------------------------------------------------
# What is exposed
# ---------------------------------------------------------------------------


def _tool_names():
    async def main():
        async with Client(server.mcp) as client:
            return sorted(t.name for t in await client.list_tools())

    return asyncio.run(main())


def test_no_tool_runs_or_writes_the_case_for_the_caller():
    names = _tool_names()

    assert "describe_environment" in names
    assert "validate_case" in names
    # Running the case, reading its logs and editing its files belong to the caller's own
    # tools now -- see mcp/deterministic.py's module docstring for why these were removed.
    for gone in (
        "run_start", "run_status", "run_tail_log", "run_stop", "classify_errors",
        "list_case", "read_case", "write_case",
    ):
        assert gone not in names
    # Choosing a solver and writing a dictionary belong to the caller's model, not here.
    for reasoning in ("plan", "input_writer", "review", "apply_fixes"):
        assert reasoning not in names


def test_the_review_tools_are_offered():
    names = _tool_names()

    assert "request_review" in names
    assert "request_report" in names


def test_the_instructions_tell_the_agent_where_to_start():
    assert "describe_environment" in server.INSTRUCTIONS
    assert "catalogue" in server.INSTRUCTIONS


# ---------------------------------------------------------------------------
# describe_environment
# ---------------------------------------------------------------------------


def test_describe_environment_reports_the_installation(monkeypatch, tmp_path):
    environment = OpenFOAMEnvironment(
        fork="esi", version="v2406", solvers=("icoFoam", "interFoam"), tutorials="/opt/tutorials"
    )
    monkeypatch.setattr(
        "foamagent.environment.environment_from_config", lambda config: environment
    )
    monkeypatch.setenv("FOAMAGENT_INDEX_DIR", str(tmp_path))

    response = call("describe_environment", {})

    assert response["fork"] == "esi"
    assert response["version"] == "v2406"
    assert response["solver_count"] == 2
    assert "icoFoam" in response["solvers"]


def test_describe_environment_points_at_the_library_when_there_is_one(monkeypatch, tmp_path):
    environment = OpenFOAMEnvironment(fork="foundation", version="10", solvers=("icoFoam",))
    monkeypatch.setattr(
        "foamagent.environment.environment_from_config", lambda config: environment
    )
    monkeypatch.setenv("FOAMAGENT_INDEX_DIR", str(tmp_path))
    built = tmp_path / "foundation-10"
    built.mkdir()
    (built / "catalog.md").write_text("# catalogue", encoding="utf-8")

    response = call("describe_environment", {})

    assert response["library"]["catalog"] == str(built / "catalog.md")
    assert any("catalog" in note for note in response["notes"])


def test_describe_environment_does_not_block_the_event_loop(monkeypatch, tmp_path):
    """A1/A2: the probe runs off-thread, so another coroutine keeps making progress.

    Without asyncio.to_thread, the synchronous sleep below runs on the event loop itself and
    the marker task cannot run until describe_environment returns -- exactly the "a few
    seconds of docker startup blocks every other tool call" bug this fixes.
    """

    def slow_probe(config):
        time.sleep(0.2)
        return OpenFOAMEnvironment(fork="foundation", version="10", solvers=("icoFoam",))

    monkeypatch.setattr("foamagent.environment.environment_from_config", slow_probe)
    monkeypatch.setenv("FOAMAGENT_INDEX_DIR", str(tmp_path))

    marker_finished_at = []

    async def marker():
        await asyncio.sleep(0.01)
        marker_finished_at.append(time.monotonic())

    async def main():
        started = time.monotonic()
        await asyncio.gather(deterministic.describe_environment(), marker())
        return started

    started = asyncio.run(main())

    assert marker_finished_at[0] - started < 0.15


def test_describe_environment_says_when_no_library_was_built(monkeypatch, tmp_path):
    environment = OpenFOAMEnvironment(fork="foundation", version="10", solvers=("icoFoam",))
    monkeypatch.setattr(
        "foamagent.environment.environment_from_config", lambda config: environment
    )
    monkeypatch.setenv("FOAMAGENT_INDEX_DIR", str(tmp_path))

    response = call("describe_environment", {})

    assert response["library"] == {}
    assert any("foamagent index build" in note for note in response["notes"])


# ---------------------------------------------------------------------------
# validate_case
# ---------------------------------------------------------------------------


def test_validate_reports_findings(case_dir, monkeypatch):
    monkeypatch.setattr(
        "foamagent.environment.environment_from_config",
        lambda config: OpenFOAMEnvironment(fork="foundation", version="10", solvers=("simpleFoam",)),
    )

    response = call("validate_case", {"request": {"case_dir": str(case_dir)}})

    assert response["application"] == "icoFoam"
    assert not response["ok"]
    assert any("icoFoam is not installed" in f["message"] for f in response["findings"])


def test_visualize_uses_the_template_and_never_a_model(case_dir, monkeypatch):
    seen = {}

    def fake(case, requirement, **kwargs):
        seen.update(kwargs)
        from foamagent.services.visualization import VisualizationResult

        return VisualizationResult(
            success=True, field_name="U", output_image=f"{case}/visualization.png"
        )

    monkeypatch.setattr("foamagent.services.visualization.visualize_case", fake)

    response = call("visualize", {"request": {"case_dir": str(case_dir), "quantity": "velocity"}})

    assert response["success"]
    assert response["image"].endswith("visualization.png")
    assert seen["output_png"] == "visualization.png"


# ---------------------------------------------------------------------------
# search_tutorials
# ---------------------------------------------------------------------------


def test_search_needs_a_library(monkeypatch, tmp_path):
    monkeypatch.setenv("FOAMAGENT_INDEX_DIR", str(tmp_path))
    monkeypatch.setattr("foamagent.indexing.detected_environment", lambda: None)

    with pytest.raises(Exception) as excinfo:
        call("search_tutorials", {"request": {"query": "cavity"}})

    assert "foamagent index build" in str(excinfo.value)


def test_search_ranks_catalog_rows(monkeypatch, tmp_path):
    environment = OpenFOAMEnvironment(fork="foundation", version="10", solvers=("icoFoam",))
    monkeypatch.setenv("FOAMAGENT_INDEX_DIR", str(tmp_path))
    monkeypatch.setattr("foamagent.indexing.detected_environment", lambda: environment)
    built = tmp_path / "foundation-10"
    built.mkdir()
    (built / "catalog.md").write_text(
        "| case | solver | domain | category | path | files | left out |\n"
        "|---|---|---|---|---|---:|---|\n"
        "| cavity | icoFoam | incompressible | cavity | `cases/incompressible/icoFoam/cavity` | 7 | - |\n"
        "| damBreak | interFoam | multiphase | RAS | `cases/multiphase/interFoam/damBreak` | 12 | - |\n",
        encoding="utf-8",
    )

    response = call("search_tutorials", {"request": {"query": "lid driven cavity icoFoam"}})

    assert response["matches"][0]["case"] == "cavity"
    assert response["matches"][0]["path"] == "cases/incompressible/icoFoam/cavity"
