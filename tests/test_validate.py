"""Unit tests for the pre-run check.

Deliberately model-free, so testable with a directory of text files.
"""

from __future__ import annotations

import pytest

from foamagent.services.validate import ERROR, field_patches, mesh_patches, validate_case


BLOCK_MESH = """
convertToMeters 0.1;
vertices ( (0 0 0) (1 0 0) );
blocks ( hex (0 1 2 3 4 5 6 7) (20 20 1) simpleGrading (1 1 1) );
boundary
(
    movingWall
    {
        type wall;
        faces ( (3 7 6 2) );
    }
    fixedWalls
    {
        type wall;
        faces ( (0 4 7 3) );
    }
    frontAndBack
    {
        type empty;
        faces ( (0 3 2 1) );
    }
);
"""

U_FIELD = """
dimensions [0 1 -1 0 0 0 0];
internalField uniform (0 0 0);
boundaryField
{
    movingWall
    {
        type fixedValue;
        value uniform (1 0 0);
    }
    fixedWalls
    {
        type noSlip;
    }
    frontAndBack
    {
        type empty;
    }
}
"""


@pytest.fixture
def case(tmp_path):
    (tmp_path / "system").mkdir()
    (tmp_path / "0").mkdir()
    (tmp_path / "system" / "controlDict").write_text(
        "application icoFoam;\nendTime 10;\ndeltaT 0.005;\nwriteInterval 100;\n", encoding="utf-8"
    )
    (tmp_path / "system" / "fvSchemes").write_text("ddtSchemes { default Euler; }\n", encoding="utf-8")
    (tmp_path / "system" / "fvSolution").write_text("solvers { }\n", encoding="utf-8")
    (tmp_path / "system" / "blockMeshDict").write_text(BLOCK_MESH, encoding="utf-8")
    (tmp_path / "0" / "U").write_text(U_FIELD, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Reading names out of the dictionaries
# ---------------------------------------------------------------------------


def test_patches_come_from_blockmeshdict_before_the_mesh_exists(case):
    assert mesh_patches(case) == ["movingWall", "fixedWalls", "frontAndBack"]


def test_patches_come_from_the_mesh_once_it_does(case):
    boundary = case / "constant" / "polyMesh"
    boundary.mkdir(parents=True)
    (boundary / "boundary").write_text(
        "3\n(\n    inlet\n    {\n        type patch;\n    }\n"
        "    outlet\n    {\n        type patch;\n    }\n)\n",
        encoding="utf-8",
    )

    assert mesh_patches(case) == ["inlet", "outlet"]


def test_a_field_lists_the_patches_it_assigns(case):
    assert field_patches(U_FIELD) == ["movingWall", "fixedWalls", "frontAndBack"]


# ---------------------------------------------------------------------------
# What the check catches
# ---------------------------------------------------------------------------


def test_a_sound_case_passes(case):
    result = validate_case(str(case), installed_solvers=("icoFoam",))

    assert result.ok, result.describe()
    assert result.application == "icoFoam"


def test_a_missing_dictionary_is_an_error(case):
    (case / "system" / "fvSolution").unlink()

    result = validate_case(str(case))

    assert not result.ok
    assert any("fvSolution" in f.where for f in result.findings)


def test_a_solver_this_installation_lacks_is_an_error(case):
    result = validate_case(str(case), installed_solvers=("simpleFoam", "interFoam"))

    assert not result.ok
    assert any("icoFoam is not installed" in f.message for f in result.findings)


def test_a_patch_the_field_forgot_is_an_error(case):
    (case / "0" / "U").write_text(U_FIELD.replace(
        "    frontAndBack\n    {\n        type empty;\n    }\n", ""), encoding="utf-8")

    result = validate_case(str(case), installed_solvers=("icoFoam",))

    assert not result.ok
    assert any("frontAndBack" in f.message for f in result.findings)


def test_a_patch_the_mesh_does_not_have_is_an_error(case):
    (case / "0" / "U").write_text(
        U_FIELD.replace("fixedWalls", "walls"), encoding="utf-8"
    )

    result = validate_case(str(case), installed_solvers=("icoFoam",))

    assert not result.ok
    assert any("walls" in f.message and "does not define" in f.message for f in result.findings)


def test_a_regex_patch_entry_counts_as_covering_everything(case):
    (case / "0" / "U").write_text(
        'dimensions [0 1 -1 0 0 0 0];\nboundaryField\n{\n    ".*"\n    {\n        type zeroGradient;\n    }\n}\n',
        encoding="utf-8",
    )

    result = validate_case(str(case), installed_solvers=("icoFoam",))

    assert result.ok, result.describe()


def test_a_missing_zero_directory_says_what_to_do(case):
    for entry in (case / "0").iterdir():
        entry.unlink()
    (case / "0").rmdir()

    result = validate_case(str(case))

    assert not result.ok
    assert any("0.orig" in f.message for f in result.findings)


def test_a_case_directory_that_is_not_there(tmp_path):
    result = validate_case(str(tmp_path / "nope"))

    assert not result.ok
    assert result.findings[0].severity == ERROR
