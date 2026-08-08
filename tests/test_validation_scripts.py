"""Unit tests for the validation showcase scripts.

The comparison against published data is the whole claim these cases make, so the parts of
it that do not need a mesh -- which files come back with the case, how a table of published
values is turned into a verdict, how a coefficient history becomes a mean and a frequency --
are tested here rather than left to be right on the day.

Nothing here runs a harness, a solver or PyVista.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foamagent.validation import check as check_module
from foamagent.validation import run as run_module

CASES = Path(__file__).resolve().parent.parent / "examples" / "validation"


@pytest.fixture(scope="module")
def check():
    return check_module


@pytest.fixture(scope="module")
def runner():
    return run_module


# ---------------------------------------------------------------------------
# The cases themselves
# ---------------------------------------------------------------------------


def test_every_case_has_a_request_and_a_reference():
    cases = sorted(p for p in CASES.iterdir() if p.is_dir())

    assert cases, "the showcase has no cases"
    for case in cases:
        assert (case / "request.md").is_file(), f"{case.name} has no request"
        reference = json.loads((case / "reference.json").read_text(encoding="utf-8"))
        assert reference["source"]["citation"], f"{case.name} cites nothing"
        assert reference["comparison"]["kind"] in ("profile", "boundary_layer", "range")


def test_no_request_gives_away_the_answer():
    """The request says what to compute and what it will be checked against, not the values.

    The reference numbers live in the same repository as the request, one directory apart,
    which is exactly the arrangement that leaked the answer in the first benchmark run. Here
    the separation is the point rather than an accident, so it is asserted.
    """
    for case in sorted(p for p in CASES.iterdir() if p.is_dir()):
        request = (case / "request.md").read_text(encoding="utf-8")
        reference = json.loads((case / "reference.json").read_text(encoding="utf-8"))

        assert "reference.json" not in request
        for author in ("Ghia", "Blasius", "Williamson"):
            assert author not in request, f"{case.name} names the source it is checked against"
        for quantity in reference["comparison"].get("quantities", {}).values():
            assert str(quantity["low"]) not in request
            assert str(quantity["high"]) not in request


def test_the_reviews_are_on_here():
    """The opposite of the benchmark runner, and the reason these cases exist."""
    import yaml

    settings = yaml.safe_load(
        run_module.PROJECT_SETTINGS.format(runtime="docker", image="i", bashrc="/b", model="m")
    )

    assert settings["review"]["mode"] == "full"


def test_the_session_is_told_to_wait_for_its_own_solver(runner):
    """A session with nobody watching is the one that walks away mid-solve."""
    added = runner.INSTRUCTIONS.format(case_dir="/somewhere")

    assert "wait_seconds" in added
    assert "/somewhere" in added


# ---------------------------------------------------------------------------
# What comes back from a run
# ---------------------------------------------------------------------------


def test_the_inputs_come_back_and_the_mesh_does_not(runner, tmp_path):
    """`Allrun` regenerates the mesh and the fields; a repository is not a results archive."""
    built = tmp_path / "built"
    for name in ("0", "constant", "system"):
        (built / name).mkdir(parents=True)
    (built / "system" / "controlDict").write_text("application icoFoam;")
    (built / "constant" / "polyMesh").mkdir()
    (built / "constant" / "polyMesh" / "points").write_text("a million points")
    (built / "0.5").mkdir()
    (built / "0.5" / "U").write_text("a field")
    (built / "spec.md").write_text("the spec")
    (built / "review-1.md").write_text("the review")
    (built / "Allrun").write_text("#!/bin/sh\n")

    copied = runner.collect(built, tmp_path / "result")

    assert "system/controlDict" in copied
    assert "spec.md" in copied and "review-1.md" in copied and "Allrun" in copied
    assert not (tmp_path / "result" / "constant" / "polyMesh").exists()
    assert not (tmp_path / "result" / "0.5").exists()


# ---------------------------------------------------------------------------
# Turning numbers into a verdict
# ---------------------------------------------------------------------------


def test_a_coefficient_history_gives_a_mean_and_a_frequency(check, tmp_path):
    """Read out of forceCoeffs' own output rather than taken from the session's claim."""
    import math

    directory = tmp_path / "postProcessing" / "forceCoeffs" / "0"
    directory.mkdir(parents=True)
    lines = ["# Force coefficients", "# Time Cd Cd(f) Cd(r) Cl Cl(f) Cl(r) CmPitch"]
    # A settling transient well inside the first half, then clean cycles at St = 0.2 about
    # a mean Cd of 1.4. The check discards the first half, so the average sees only these.
    for step in range(1600):
        t = step * 0.05
        settled = t > 20
        cd = 1.4 if settled else 1.4 + 0.5 * math.exp(-t / 5)
        cl = math.sin(2 * math.pi * 0.2 * t) if settled else 0.0
        lines.append(f"{t} {cd} 0 0 {cl} 0 0 0")
    (directory / "coefficient.dat").write_text("\n".join(lines))

    measured, detail = check.coefficients_from_history(tmp_path)

    assert measured["Cd_mean"] == pytest.approx(1.4, abs=1e-6)
    assert measured["St"] == pytest.approx(0.2, abs=1e-3)
    assert detail["cycles"] >= 2


def test_a_case_with_no_force_output_says_so_rather_than_guessing(check, tmp_path):
    measured, detail = check.coefficients_from_history(tmp_path)

    assert measured == {}
    assert "postProcessing" in detail["note"]


def test_a_value_outside_the_published_range_is_measured_not_just_failed(check, tmp_path):
    """How far outside is the useful number; "fails" on its own starts no investigation."""
    reference = {
        "comparison": {
            "kind": "range",
            "quantities": {"Cd_mean": {"low": 1.32, "high": 1.38},
                           "St": {"low": 0.163, "high": 0.168}},
        }
    }
    directory = tmp_path / "postProcessing" / "forceCoeffs" / "0"
    directory.mkdir(parents=True)
    import math

    lines = ["# Time Cd Cl"]
    for step in range(400):
        t = step * 0.05
        lines.append(f"{t} 1.60 {math.sin(2 * math.pi * 0.2 * t)}")
    (directory / "coefficient.dat").write_text("\n".join(lines))
    (tmp_path / "results.json").write_text(json.dumps({"Cd_mean": 1.35, "St": 0.2}))

    result = check.compare_range(tmp_path, reference)

    assert result["agrees"] is False
    assert result["quantities"]["Cd_mean"]["outside_by"] == pytest.approx(0.22, abs=1e-3)
    # The session said 1.35 and its own output says 1.60; both are reported.
    assert result["quantities"]["Cd_mean"]["claimed"] == 1.35
    assert result["quantities"]["Cd_mean"]["case"] == pytest.approx(1.60, abs=1e-6)


def test_wall_patches_are_found_by_declared_type_not_by_name(check, tmp_path):
    """A patch called 'plate' or 'cylinder' is a wall because the dict says so, not its name.

    The function this replaced inferred the leading edge from a velocity threshold sampled
    at a fixed height above the floor, which on the real flat-plate case put the leading
    edge at x=0.39 on a plate that starts at x=0 -- the boundary layer at x<0.39 simply
    hadn't grown thick enough yet to register at that sampling height.
    """
    boundary_dir = tmp_path / "constant" / "polyMesh"
    boundary_dir.mkdir(parents=True)
    (boundary_dir / "boundary").write_text(
        "6\n(\n"
        "    inlet\n    {\n        type patch;\n        nFaces 10;\n    }\n"
        "    plate\n    {\n        type wall;\n        nFaces 20;\n    }\n"
        "    frontAndBack\n    {\n        type empty;\n        nFaces 5;\n    }\n"
        ")\n",
        encoding="utf-8",
    )

    assert check.wall_patch_names(tmp_path) == ["plate"]
