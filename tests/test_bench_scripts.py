"""Unit tests for the FoamBench helper scripts.

They are scripts rather than package code, but two of the things they do encode a quirk of
somebody else's evaluator -- where a log has to be for the run to count, and what the
official unpacker writes that this one must not -- and a quirk nobody can see from the code
is one that gets tidied away.

Nothing here runs a harness, a solver or a container.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts" / "bench"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"bench_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def unpack():
    return load("foambench_unpack")


@pytest.fixture(scope="module")
def runner():
    return load("foambench_run")


@pytest.fixture(scope="module")
def reference():
    return load("foambench_reference")


# ---------------------------------------------------------------------------
# Unpacking
# ---------------------------------------------------------------------------


def test_a_case_becomes_a_request_and_a_reference(unpack, tmp_path):
    payload = {
        "usr_requirement": "Simulate a lid-driven cavity.",
        "Allrun": "#!/bin/sh\nrunApplication blockMesh\n",
        "system/controlDict": "application pisoFoam;\n",
        "0/U": "internalField uniform (0 0 0);\n",
    }

    written = unpack.unpack_case("Cavity_SA", payload, tmp_path)

    case = tmp_path / "Cavity_SA"
    assert written == 3
    assert (case / "usr_requirement.txt").read_text() == "Simulate a lid-driven cavity."
    assert (case / "GT_Files" / "system" / "controlDict").is_file()
    assert (case / "GT_Files" / "0" / "U").is_file()


def test_the_reference_allrun_is_executable(unpack, tmp_path):
    """It is run as ./Allrun, and the JSON carries no file mode."""
    unpack.unpack_case("x", {"Allrun": "#!/bin/sh\n"}, tmp_path)

    import os

    assert os.access(tmp_path / "x" / "GT_Files" / "Allrun", os.X_OK)


def test_no_credentials_file_is_written(unpack, tmp_path):
    """The official unpacker writes an OpenAI key into a YAML beside the case. This must not."""
    unpack.unpack_case("x", {"usr_requirement": "r", "Allrun": "#!/bin/sh\n"}, tmp_path)

    written = {p.name for p in (tmp_path / "x").rglob("*") if p.is_file()}

    assert written == {"usr_requirement.txt", "Allrun"}
    assert not any(name.endswith((".yaml", ".yml")) for name in written)


# ---------------------------------------------------------------------------
# The layout the evaluator needs
# ---------------------------------------------------------------------------


def test_the_logs_are_copied_where_the_evaluator_looks(runner, tmp_path):
    """`execution_report.py` only walks the submission's subdirectories.

    A case laid out the ordinary way -- log.pisoFoam next to system/ -- scores zero for
    execution however well it ran. Measured, not inferred: a byte-for-byte copy of a run
    reference case scored 0 until this copy existed.
    """
    submission = tmp_path / "foamagent"
    (submission / "system").mkdir(parents=True)
    (submission / "log.pisoFoam").write_text("Time = 10\nEnd\n")
    (submission / "log.blockMesh").write_text("End\n")

    copied = runner.copy_logs_for_the_evaluator(submission)

    assert sorted(copied) == ["log.blockMesh", "log.pisoFoam"]
    assert (submission / "logs" / "log.pisoFoam").read_text() == "Time = 10\nEnd\n"
    # The originals stay where OpenFOAM put them.
    assert (submission / "log.pisoFoam").is_file()


def test_copying_logs_is_harmless_when_there_are_none(runner, tmp_path):
    submission = tmp_path / "foamagent"
    submission.mkdir()

    assert runner.copy_logs_for_the_evaluator(submission) == []
    assert not (submission / "logs").exists()


@pytest.mark.parametrize("module_name", ["foambench_run", "foambench_reference"])
def test_the_initial_time_is_not_counted_as_a_result(module_name, tmp_path):
    module = load(module_name)
    case = tmp_path / "case"
    for name in ("0", "0.5", "10", "constant", "system"):
        (case / name).mkdir(parents=True)

    assert module.time_directories(case) == ["0.5", "10"]


def test_the_benchmark_settings_switch_the_reviews_off(runner):
    """A benchmark run is scored against reference files; nothing reads a review."""
    import yaml

    settings = yaml.safe_load(
        runner.PROJECT_SETTINGS.format(
            runtime="docker", image="i", bashrc="/b", model=runner.DEFAULT_MODEL
        )
    )

    assert settings["review"]["mode"] == "off"
    assert settings["openfoam"]["runtime"] == "docker"


def test_one_model_is_named_for_the_whole_run(runner):
    """A score without a model beside it says nothing, so the model is never left implicit."""
    import yaml

    settings = yaml.safe_load(
        runner.PROJECT_SETTINGS.format(
            runtime="docker", image="i", bashrc="/b", model="claude-sonnet-5"
        )
    )

    # The session that writes the case and the review that would read it are the same model.
    assert settings["review"]["model"] == "claude-sonnet-5"
    assert runner.DEFAULT_MODEL == "claude-sonnet-5"


def test_the_request_is_passed_word_for_word(runner):
    """Only where the case goes, and that nobody is there to answer, may be added."""
    added = runner.INSTRUCTIONS.format(case_dir="/somewhere")

    assert "/somewhere" in added
    for word in ("solver", "mesh", "boundary", "turbulence", "viscosity"):
        assert word not in added.lower()
