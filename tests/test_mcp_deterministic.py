"""The deterministic tools, exercised through a real MCP client.

FastMCP's in-memory transport means the schemas, the serialisation and the tool names are
all under test, not just the Python functions behind them. No OpenFOAM, no container and no
model: the execution backend is a stub and the environment probe is fed fixed output.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastmcp import Client

from foamagent.environment import OpenFOAMEnvironment
from foamagent.execution import CommandResult, ExecutionPlan, NativeBackend
from foamagent.mcp import deterministic, fastmcp_server as server
from foamagent.services import run_async


class _Backend(NativeBackend):
    name = "stub"

    def __init__(self, on_run=None):
        super().__init__()
        self.on_run = on_run

    def plan(self, command, working_dir):
        return ExecutionPlan(argv=list(command), working_dir=working_dir)

    def run(self, command, working_dir, *, timeout=None, on_start=None):
        if on_start is not None:
            on_start(self.plan(command, working_dir), None)
        if self.on_run is not None:
            self.on_run(Path(working_dir))
        return CommandResult(0, "", "")


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


@pytest.fixture
def registry(monkeypatch):
    registry = run_async.RunRegistry()
    run_async.set_run_registry(registry)
    yield registry
    run_async.set_run_registry(run_async.RunRegistry())


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


def test_no_tool_writes_the_case_for_the_caller():
    names = _tool_names()

    assert "describe_environment" in names
    assert "run_start" in names
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
# The run tools
# ---------------------------------------------------------------------------


def test_a_run_is_started_and_then_asked_about(case_dir, registry, monkeypatch):
    monkeypatch.setattr(
        run_async, "get_execution_backend",
        lambda: _Backend(on_run=lambda d: (d / "log.blockMesh").write_text("End\n")),
    )

    started = call("run_start", {"request": {"case_dir": str(case_dir)}})
    assert started["state"] == "running"

    for _ in range(200):
        status = call("run_status", {"request": {"run_id": started["run_id"]}})
        if status["state"] != "running":
            break
        time.sleep(0.01)

    assert status["state"] == "succeeded"
    assert status["errors"] == []
    assert "log.blockMesh" in status["logs"]


def test_status_can_be_asked_by_case_directory(case_dir, registry, monkeypatch):
    monkeypatch.setattr(run_async, "get_execution_backend", lambda: _Backend())

    call("run_start", {"request": {"case_dir": str(case_dir)}})
    status = call("run_status", {"request": {"case_dir": str(case_dir)}})

    assert status["case_dir"] == str(case_dir)


def test_the_status_call_can_wait_for_the_run(case_dir, registry, monkeypatch):
    """A caller with nobody to remind it needs one call that comes back when the run ends.

    Polling in a loop is what a session abandons: on a benchmark run two cases in sixteen
    were left mid-solve by a session that had decided it was finished. `wait_seconds` makes
    waiting the single obvious call rather than a loop the caller has to keep choosing.
    """
    monkeypatch.setattr(deterministic, "POLL_SECONDS", 0.01)

    def slow(directory: Path):
        time.sleep(0.2)
        (directory / "log.icoFoam").write_text("End\n", encoding="utf-8")

    monkeypatch.setattr(run_async, "get_execution_backend", lambda: _Backend(on_run=slow))

    started = call("run_start", {"request": {"case_dir": str(case_dir)}})
    assert started["state"] == "running"
    # The message the caller reads is about finishing the run, not about having started it.
    assert "wait_seconds" in started["message"]

    status = call("run_status", {"request": {"run_id": started["run_id"], "wait_seconds": 10}})

    assert status["state"] == "succeeded"


def test_a_wait_that_runs_out_answers_anyway(case_dir, registry, monkeypatch):
    """Waiting must never turn into an error: the caller has to be told it is still going."""
    monkeypatch.setattr(deterministic, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(
        run_async, "get_execution_backend", lambda: _Backend(on_run=lambda d: time.sleep(5)),
    )

    started = call("run_start", {"request": {"case_dir": str(case_dir)}})
    began = time.monotonic()
    status = call("run_status", {"request": {"run_id": started["run_id"], "wait_seconds": 0.2}})
    waited = time.monotonic() - began

    assert status["state"] == "running"
    assert 0.2 <= waited < 4
    assert "Still running" in status["detail"] and "wait_seconds" in status["detail"]


def test_the_wait_is_capped_short_of_a_client_timeout(case_dir, registry):
    """An hour-long wait would be cut by the client's own timeout, not honoured."""
    assert deterministic.MAX_WAIT <= 600


def test_asking_about_a_run_that_never_happened(tmp_path, registry):
    with pytest.raises(Exception) as excinfo:
        call("run_status", {"request": {"run_id": "nosuchrun"}})

    assert "No such run" in str(excinfo.value)


def test_the_log_tail_comes_back(case_dir, registry):
    (case_dir / "log.icoFoam").write_text("\n".join(str(i) for i in range(20)), encoding="utf-8")

    response = call("run_tail_log", {"request": {"case_dir": str(case_dir), "lines": 2}})

    assert response["text"] == "18\n19"
    assert "log.icoFoam" in response["logs"]


def test_stopping_a_run_that_does_not_exist(registry):
    with pytest.raises(Exception):
        call("run_stop", {"request": {"run_id": "nosuchrun"}})


# ---------------------------------------------------------------------------
# validate_case / classify_errors
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
            success=True, field_name="U", output_image=f"{case}/visualization.png",
            script="", used="deterministic_template",
        )

    monkeypatch.setattr("foamagent.services.visualization.visualize_case", fake)

    response = call("visualize", {"request": {"case_dir": str(case_dir), "quantity": "velocity"}})

    assert response["success"]
    assert response["image"].endswith("visualization.png")
    assert seen["output_png"] == "visualization.png"


def test_classify_errors_names_the_failure(case_dir):
    (case_dir / "log.icoFoam").write_text(
        'keyword nu is undefined in dictionary "constant/physicalProperties"\n', encoding="utf-8"
    )

    response = call("classify_errors", {"request": {"case_dir": str(case_dir)}})

    assert response["count"] == 1
    assert response["categories"] == ["missing_keyword"]


# ---------------------------------------------------------------------------
# Case files
# ---------------------------------------------------------------------------


def test_files_are_listed_read_and_written(case_dir):
    listing = call("list_case", {"request": {"case_dir": str(case_dir)}})
    assert any(f["path"] == "system/controlDict" for f in listing["files"])

    read = call("read_case", {"request": {"case_dir": str(case_dir), "path": "system/controlDict"}})
    assert "application icoFoam;" in read["text"]

    call("write_case", {"request": {"case_dir": str(case_dir), "path": "0/U", "text": "dimensions [0 1 -1 0 0 0 0];\n"}})
    assert (case_dir / "0" / "U").is_file()


def test_a_written_allrun_is_executable(case_dir):
    call("write_case", {"request": {"case_dir": str(case_dir), "path": "Allrun", "text": "#!/bin/sh\n"}})

    assert (case_dir / "Allrun").stat().st_mode & 0o111


def test_reading_outside_the_case_is_refused(case_dir):
    with pytest.raises(Exception) as excinfo:
        call("read_case", {"request": {"case_dir": str(case_dir), "path": "../../etc/passwd"}})

    assert "outside the case directory" in str(excinfo.value)


def test_writing_outside_the_case_is_refused(case_dir):
    with pytest.raises(Exception):
        call("write_case", {"request": {"case_dir": str(case_dir), "path": "../escape", "text": "x"}})


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
