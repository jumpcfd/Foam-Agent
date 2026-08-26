"""Tests for the per-case state file the MCP entry points share."""

import json
import threading

import pytest

from foamagent.case_state import (
    STATE_DIRNAME,
    STATE_FILENAME,
    STATE_VERSION,
    CaseState,
    increment_case_state_field,
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
        note="Lid-driven cavity flow, Re=1000.",
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
    save_case_state(tmp_path, CaseState(note="icoFoam case"))

    data = json.loads(state_path(tmp_path).read_text())

    assert data["version"] == STATE_VERSION
    assert data["note"] == "icoFoam case"


def test_a_state_written_by_one_entry_point_is_read_by_the_other(tmp_path):
    """The point of the file: the writer and the reader share no memory."""
    save_case_state(tmp_path, CaseState(case_name="cavity", note="interFoam multiphase case"))

    # A second process would start from nothing but the directory path.
    recovered = load_case_state(str(tmp_path))

    assert recovered is not None
    assert recovered.case_name == "cavity"
    assert recovered.note == "interFoam multiphase case"


def test_update_preserves_fields_it_was_not_given(tmp_path):
    save_case_state(tmp_path, CaseState(note="icoFoam case", case_name="cavity"))

    updated = update_case_state(tmp_path, loop_count=2)

    assert updated.loop_count == 2
    assert updated.note == "icoFoam case"
    assert updated.case_name == "cavity"
    assert load_case_state(tmp_path) == updated


def test_update_starts_from_defaults_when_no_state_exists(tmp_path):
    updated = update_case_state(tmp_path, note="simpleFoam case")

    assert updated.note == "simpleFoam case"
    assert updated.loop_count == 0


def test_update_rejects_an_unknown_field(tmp_path):
    with pytest.raises(TypeError, match="solver_name"):
        update_case_state(tmp_path, solver_name="icoFoam")


def test_a_missing_key_falls_back_to_its_default(tmp_path):
    """A state file written by an older version must stay readable.

    `case_solver` was a real field once (see git history) and is now unknown -- exactly the
    shape a file written before a field was removed takes. It must be dropped, not raise.
    """
    path = state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "case_solver": "icoFoam"}))

    state = load_case_state(tmp_path)

    assert state is not None
    assert state.case_name == ""
    assert state.subtasks == []
    assert state.loop_count == 0


def test_a_newer_version_is_read_for_the_fields_this_version_knows(tmp_path):
    path = state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": STATE_VERSION + 1,
                "case_name": "cavity",
                "some_future_field": {"nested": True},
            }
        )
    )

    state = load_case_state(tmp_path)

    assert state is not None
    assert state.case_name == "cavity"


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


def test_increment_case_state_field_rejects_an_unknown_field(tmp_path):
    with pytest.raises(TypeError):
        increment_case_state_field(tmp_path, "not_a_real_field")


def test_increment_case_state_field_starts_from_zero(tmp_path):
    state = increment_case_state_field(tmp_path, "spec_review_rounds")

    assert state.spec_review_rounds == 1


def test_concurrent_increments_do_not_lose_a_write(tmp_path):
    """Regression: record_round used to read the current count, compute `current + 1`
    itself, and only then call update_case_state with that absolute value -- two concurrent
    callers (the spec and result stages, most concretely) could both read the same starting
    count and each write back the same `+1`, one silently clobbering the other's. Locking
    only inside update_case_state does not fix this: the read that decides the new value
    happens before it is even called. increment_case_state_field does the whole read-then-
    write as one atomic step instead."""

    def bump():
        increment_case_state_field(tmp_path, "spec_review_rounds")

    threads = [threading.Thread(target=bump) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert load_case_state(tmp_path).spec_review_rounds == 20
