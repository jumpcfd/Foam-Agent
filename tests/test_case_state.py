"""Tests for the per-case state file shared by the LangGraph and MCP entry points."""

import json

import pytest

from foamagent.case_state import (
    STATE_DIRNAME,
    STATE_FILENAME,
    STATE_VERSION,
    CaseState,
    load_case_state,
    save_case_state,
    state_path,
    update_case_state,
)


def test_state_path_is_inside_the_case_directory(tmp_path):
    assert state_path(tmp_path) == tmp_path.resolve() / STATE_DIRNAME / STATE_FILENAME


def test_load_returns_none_when_no_state_was_written(tmp_path):
    assert load_case_state(tmp_path) is None


def test_save_then_load_round_trips_every_field(tmp_path):
    state = CaseState(
        case_name="cavity",
        case_solver="icoFoam",
        case_domain="incompressible",
        case_category="lidDrivenCavity",
        user_requirement="Simulate the lid-driven cavity flow.",
        subtasks=[{"file_name": "controlDict", "folder_name": "system"}],
        loop_count=3,
    )
    save_case_state(tmp_path, state)

    assert load_case_state(tmp_path) == state


def test_save_creates_the_state_directory(tmp_path):
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    path = save_case_state(case_dir, CaseState(case_name="cavity"))

    assert path.is_file()
    assert path.parent.name == STATE_DIRNAME


def test_written_file_records_the_format_version(tmp_path):
    save_case_state(tmp_path, CaseState(case_solver="icoFoam"))

    data = json.loads(state_path(tmp_path).read_text())

    assert data["version"] == STATE_VERSION
    assert data["case_solver"] == "icoFoam"


def test_a_state_written_by_one_entry_point_is_read_by_the_other(tmp_path):
    """The point of the file: the writer and the reader share no memory."""
    save_case_state(tmp_path, CaseState(case_solver="interFoam", case_domain="multiphase"))

    # A second process would start from nothing but the directory path.
    recovered = load_case_state(str(tmp_path))

    assert recovered is not None
    assert recovered.case_solver == "interFoam"
    assert recovered.case_domain == "multiphase"


def test_update_preserves_fields_it_was_not_given(tmp_path):
    save_case_state(tmp_path, CaseState(case_solver="icoFoam", case_name="cavity"))

    updated = update_case_state(tmp_path, loop_count=2)

    assert updated.loop_count == 2
    assert updated.case_solver == "icoFoam"
    assert updated.case_name == "cavity"
    assert load_case_state(tmp_path) == updated


def test_update_starts_from_defaults_when_no_state_exists(tmp_path):
    updated = update_case_state(tmp_path, case_solver="simpleFoam")

    assert updated.case_solver == "simpleFoam"
    assert updated.loop_count == 0


def test_update_rejects_an_unknown_field(tmp_path):
    with pytest.raises(TypeError, match="solver_name"):
        update_case_state(tmp_path, solver_name="icoFoam")


def test_a_missing_key_falls_back_to_its_default(tmp_path):
    """A state file written by an older version must stay readable."""
    path = state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "case_solver": "icoFoam"}))

    state = load_case_state(tmp_path)

    assert state is not None
    assert state.case_solver == "icoFoam"
    assert state.subtasks == []
    assert state.loop_count == 0


def test_a_newer_version_is_read_for_the_fields_this_version_knows(tmp_path):
    path = state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": STATE_VERSION + 1,
                "case_solver": "icoFoam",
                "some_future_field": {"nested": True},
            }
        )
    )

    state = load_case_state(tmp_path)

    assert state is not None
    assert state.case_solver == "icoFoam"


def test_malformed_json_degrades_to_none_rather_than_raising(tmp_path):
    path = state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")

    assert load_case_state(tmp_path) is None


def test_a_json_document_that_is_not_an_object_degrades_to_none(tmp_path):
    path = state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("[1, 2, 3]")

    assert load_case_state(tmp_path) is None
