"""Unit tests for starting a run and asking about it afterwards.

The execution backend is a stub, so no OpenFOAM and no container: what is under test is the
bookkeeping around a run, not the solver.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from foamagent.execution import CommandResult, ExecutionPlan, NativeBackend
from foamagent.services import run_async
from foamagent.services.run_async import (
    RUNNING,
    STOPPED,
    SUCCEEDED,
    FAILED,
    TIMED_OUT,
    RunRegistry,
    list_logs,
    tail_log,
)


class _Backend(NativeBackend):
    """Runs nothing. Writes whatever the test asked for into the case directory."""

    name = "stub"

    def __init__(self, result=None, *, on_run=None, block=None):
        super().__init__()
        self.result = result or CommandResult(0, "done\n", "")
        self.on_run = on_run
        self.block = block
        self.terminated = 0

    def plan(self, command, working_dir):
        return ExecutionPlan(argv=list(command), working_dir=working_dir)

    def run(self, command, working_dir, *, timeout=None, on_start=None):
        if on_start is not None:
            on_start(self.plan(command, working_dir), None)
        if self.on_run is not None:
            self.on_run(Path(working_dir))
        if self.block is not None:
            self.block.wait(timeout=5)
        return self.result

    def terminate(self, plan, process):
        self.terminated += 1


@pytest.fixture
def case_dir(tmp_path):
    (tmp_path / "system").mkdir()
    (tmp_path / "Allrun").write_text("#!/bin/sh\nblockMesh\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def registry(monkeypatch):
    return RunRegistry()


def _use(monkeypatch, backend):
    monkeypatch.setattr(run_async, "get_execution_backend", lambda: backend)


def _settle(registry, run_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = registry.get(run_id)
        if record and record.done:
            return record
        time.sleep(0.01)
    raise AssertionError("run did not finish")


# ---------------------------------------------------------------------------
# Starting
# ---------------------------------------------------------------------------


def test_start_returns_before_the_run_finishes(case_dir, registry, monkeypatch):
    import threading

    gate = threading.Event()
    _use(monkeypatch, _Backend(block=gate))

    started = time.time()
    record = registry.start(str(case_dir))
    elapsed = time.time() - started

    try:
        # The point of the whole module: no client timeout is spent waiting for a solver.
        assert elapsed < 1.0
        assert record.state == RUNNING
    finally:
        gate.set()
        _settle(registry, record.run_id)


def test_a_case_with_no_allrun_is_refused(tmp_path, registry):
    with pytest.raises(FileNotFoundError):
        registry.start(str(tmp_path))


def test_a_clean_run_removes_the_previous_attempt(case_dir, registry, monkeypatch):
    (case_dir / "log.blockMesh").write_text("old", encoding="utf-8")
    (case_dir / "0.5").mkdir()
    _use(monkeypatch, _Backend())

    record = registry.start(str(case_dir))
    _settle(registry, record.run_id)

    assert not (case_dir / "log.blockMesh").exists()
    assert not (case_dir / "0.5").exists()


def test_previous_output_is_kept_when_asked(case_dir, registry, monkeypatch):
    (case_dir / "log.blockMesh").write_text("End\n", encoding="utf-8")
    _use(monkeypatch, _Backend())

    record = registry.start(str(case_dir), clean=False)
    _settle(registry, record.run_id)

    assert (case_dir / "log.blockMesh").is_file()


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def test_a_clean_log_is_a_success(case_dir, registry, monkeypatch):
    _use(monkeypatch, _Backend(on_run=lambda d: (d / "log.blockMesh").write_text("End\n")))

    record = _settle(registry, registry.start(str(case_dir)).run_id)

    assert record.state == SUCCEEDED
    assert record.errors == []


def test_an_error_in_a_log_is_a_failure(case_dir, registry, monkeypatch):
    _use(
        monkeypatch,
        _Backend(on_run=lambda d: (d / "log.icoFoam").write_text("ERROR: keyword nu undefined\n")),
    )

    record = _settle(registry, registry.start(str(case_dir)).run_id)

    assert record.state == FAILED
    assert record.errors
    assert "log.icoFoam" in record.errors[0]


def test_a_timeout_is_reported_as_one(case_dir, registry, monkeypatch):
    _use(monkeypatch, _Backend(CommandResult(-9, "", "", timed_out=True)))

    record = _settle(registry, registry.start(str(case_dir), timeout=1).run_id)

    assert record.state == TIMED_OUT
    assert "1s" in record.detail


def test_a_backend_that_explodes_does_not_take_the_server_with_it(case_dir, registry, monkeypatch):
    class Exploding(_Backend):
        def run(self, command, working_dir, *, timeout=None, on_start=None):
            raise OSError("docker: command not found")

    _use(monkeypatch, Exploding())

    record = _settle(registry, registry.start(str(case_dir)).run_id)

    assert record.state == FAILED
    assert "docker" in record.detail


# ---------------------------------------------------------------------------
# Asking afterwards
# ---------------------------------------------------------------------------


def test_the_run_is_recorded_in_the_case_directory(case_dir, registry, monkeypatch):
    _use(monkeypatch, _Backend(on_run=lambda d: (d / "log.blockMesh").write_text("End\n")))

    record = _settle(registry, registry.start(str(case_dir)).run_id)

    written = json.loads((case_dir / ".foamagent" / "runs" / f"{record.run_id}.json").read_text())
    assert written["state"] == SUCCEEDED
    assert written["case_dir"] == str(case_dir)


def test_the_latest_run_of_a_case_can_be_found_without_its_id(case_dir, registry, monkeypatch):
    _use(monkeypatch, _Backend())

    first = _settle(registry, registry.start(str(case_dir)).run_id)
    second = _settle(registry, registry.start(str(case_dir)).run_id)

    assert registry.latest(str(case_dir)).run_id == second.run_id
    assert first.run_id != second.run_id


def test_a_run_from_a_previous_server_is_not_reported_as_running(case_dir, monkeypatch):
    directory = case_dir / ".foamagent" / "runs"
    directory.mkdir(parents=True)
    (directory / "abc123.json").write_text(
        json.dumps({"run_id": "abc123", "case_dir": str(case_dir), "state": "running",
                    "started_at": 1.0, "finished_at": None}),
        encoding="utf-8",
    )

    record = RunRegistry().latest(str(case_dir))

    assert record.state == STOPPED
    assert "no longer" in record.detail


def test_stopping_kills_the_process_and_the_container(case_dir, registry, monkeypatch):
    import threading

    gate = threading.Event()
    backend = _Backend(block=gate)
    _use(monkeypatch, backend)

    record = registry.start(str(case_dir))
    for _ in range(200):  # the thread has to reach the backend before a stop means anything
        if registry._processes.get(record.run_id):
            break
        time.sleep(0.01)

    registry.stop(record.run_id)
    gate.set()
    settled = _settle(registry, record.run_id)

    assert backend.terminated == 1
    assert settled.state == STOPPED


def test_stopping_an_unknown_run_says_so(registry):
    assert registry.stop("nosuchrun") is None


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


def test_the_tail_is_the_end_of_the_log(case_dir):
    (case_dir / "log.icoFoam").write_text("\n".join(str(i) for i in range(100)), encoding="utf-8")

    assert tail_log(str(case_dir), name="log.icoFoam", lines=3) == "97\n98\n99"


def test_latest_picks_the_log_being_written(case_dir):
    (case_dir / "log.blockMesh").write_text("older\n", encoding="utf-8")
    time.sleep(0.01)
    (case_dir / "log.icoFoam").write_text("newer\n", encoding="utf-8")

    assert tail_log(str(case_dir), name="latest") == "newer"


def test_a_missing_log_is_empty_rather_than_an_error(case_dir):
    assert tail_log(str(case_dir), name="log.nothing") == ""


def test_a_log_name_cannot_leave_the_case_directory(case_dir):
    with pytest.raises(ValueError):
        tail_log(str(case_dir), name="../../etc/passwd")


def test_logs_are_listed_newest_first(case_dir):
    (case_dir / "log.blockMesh").write_text("x", encoding="utf-8")
    time.sleep(0.01)
    (case_dir / "log.icoFoam").write_text("x", encoding="utf-8")

    assert list_logs(str(case_dir))[0] == "log.icoFoam"
