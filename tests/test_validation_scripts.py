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


def test_zero_or_negative_timeout_disables_it(runner, tmp_path, monkeypatch):
    """A case complex enough to need more than two review rounds should not be cut off.

    `subprocess.run`'s own sentinel for "no timeout" is `None`, not 0 or a negative number --
    either of those would time out almost immediately instead. `run_case` has to translate.
    """
    import subprocess

    case_dir = tmp_path / "some_case"
    case_dir.mkdir()
    (case_dir / runner.REQUEST).write_text("Simulate something.")
    (case_dir / runner.RESULT).mkdir()

    seen_timeouts = []

    def session(argv, **kwargs):
        seen_timeouts.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(argv, 0, "done", "")

    monkeypatch.setattr(runner.subprocess, "run", session)

    for requested in (0, -1, -3600):
        runner.run_case(case_dir, harness_dir=tmp_path, workspace=tmp_path / "ws",
                        harness="claude", model="m", timeout=requested)

    assert seen_timeouts == [None, None, None]

    runner.run_case(case_dir, harness_dir=tmp_path, workspace=tmp_path / "ws",
                    harness="claude", model="m", timeout=45)

    assert seen_timeouts[-1] == 45


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
# The case-local checker hook
# ---------------------------------------------------------------------------

STUB_CHECKER = """\
import argparse, json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("case_dir", type=Path)
parser.add_argument("--reference", type=Path)
parser.add_argument("--out", type=Path)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
(args.out / "comparison.json").write_text(json.dumps({"agrees": True, "from": "stub"}))
"""


def test_a_case_local_checker_runs_instead_of_the_built_in(runner, tmp_path):
    case_dir, built, destination = tmp_path / "case", tmp_path / "built", tmp_path / "result"
    case_dir.mkdir()
    built.mkdir()
    (case_dir / "reference.json").write_text("{}")
    (case_dir / "check.py").write_text(STUB_CHECKER)

    comparison = runner.run_comparison(built, case_dir, destination)

    assert comparison == {"agrees": True, "from": "stub"}


def test_a_case_without_a_checker_uses_the_built_in(runner, tmp_path):
    case_dir, built, destination = tmp_path / "case", tmp_path / "built", tmp_path / "result"
    case_dir.mkdir()
    built.mkdir()
    reference = {
        "case": "stub", "title": "stub", "source": {"citation": "n/a"},
        "comparison": {"kind": "range", "quantities": {}},
    }
    (case_dir / "reference.json").write_text(json.dumps(reference))

    comparison = runner.run_comparison(built, case_dir, destination)

    assert comparison["agrees"] is True
    assert comparison["quantities"] == {}


def test_a_checker_that_writes_nothing_is_reported_not_crashed(runner, tmp_path):
    case_dir, built, destination = tmp_path / "case", tmp_path / "built", tmp_path / "result"
    case_dir.mkdir()
    built.mkdir()
    (case_dir / "reference.json").write_text("{}")
    (case_dir / "check.py").write_text("import sys\nsys.exit('boom')\n")

    comparison = runner.run_comparison(built, case_dir, destination)

    assert comparison["agrees"] is None
    assert "error" in comparison


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


class _FakeSampledLine:
    """Just enough of a PyVista `sample_over_line()` result for `sample_line` to read.

    A case-local checker (`cases/bfs_re_h_36000/check.py`) needed fields other than U from
    the same line probe -- a Reynolds-shear-stress estimate via the Boussinesq approximation
    needs p and nut too -- which is why `sample_line` grew the `fields` parameter this tests.
    """

    def __init__(self, points, data, valid_mask=None):
        self.points = points
        self._data = data
        self.point_data = {"vtkValidPointMask": valid_mask} if valid_mask is not None else {}

    def __getitem__(self, name):
        return self._data[name]


class _FakeBlock:
    def __init__(self, line: _FakeSampledLine):
        self._line = line

    def sample_over_line(self, start, end, resolution):
        return self._line


def test_sample_line_default_matches_the_pre_existing_single_field_shape(check):
    line = _FakeSampledLine(
        points=[[0, 0, 0], [1, 0, 0]],
        data={"U": [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]},
    )
    coords, U = check.sample_line(_FakeBlock(line), (0, 0, 0), (1, 0, 0))

    assert list(U[0]) == [1.0, 0.0, 0.0]
    assert list(U[1]) == [2.0, 0.0, 0.0]
    assert len(coords) == 2


def test_sample_line_with_multiple_fields_returns_a_dict_and_respects_the_valid_mask(check):
    line = _FakeSampledLine(
        points=[[0, 0, 0], [1, 0, 0], [2, 0, 0]],
        data={
            "U": [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            "p": [10.0, 11.0, 0.0],
            "nut": [1e-5, 2e-5, 0.0],
        },
        valid_mask=[1, 1, 0],  # the third point missed the mesh
    )
    coords, values = check.sample_line(_FakeBlock(line), (0, 0, 0), (2, 0, 0),
                                        fields=("U", "p", "nut"))

    assert set(values) == {"U", "p", "nut"}
    assert len(coords) == 2, "the invalid third point should have been dropped"
    assert list(values["p"]) == [10.0, 11.0]
    assert list(values["nut"]) == [1e-5, 2e-5]
