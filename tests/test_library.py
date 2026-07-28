"""Unit tests for the reference library an AI harness reads.

No OpenFOAM and no container: the tutorials are a handful of files in tmp_path. Building
against a real installation is acceptance condition A2.
"""

from __future__ import annotations

import pytest

from foamagent.indexing.library import (
    BY_SOLVER_FILE,
    CASES_SUBDIR,
    CATALOG_FILE,
    COMMANDS_SUBDIR,
    library_paths,
    write_library,
)
from foamagent.indexing.tutorials import excluded_reason, find_cases, max_file_bytes


@pytest.fixture
def tutorials(tmp_path):
    """Two cases, one of which carries a 27 MB geometry file like planingHullW3 does."""
    root = tmp_path / "tutorials"

    cavity = root / "incompressible" / "icoFoam" / "cavity"
    (cavity / "system").mkdir(parents=True)
    (cavity / "0").mkdir()
    (cavity / "system" / "controlDict").write_text("application icoFoam;\n", encoding="utf-8")
    (cavity / "0" / "U").write_text("internalField uniform (0 0 0);\n", encoding="utf-8")
    (cavity / "Allrun").write_text("#!/bin/sh\nblockMesh\nicoFoam\n", encoding="utf-8")

    hull = root / "multiphase" / "interFoam" / "hull"
    (hull / "system").mkdir(parents=True)
    (hull / "constant" / "triSurface").mkdir(parents=True)
    (hull / "system" / "controlDict").write_text("application interFoam;\n", encoding="utf-8")
    (hull / "constant" / "triSurface" / "hull.stl").write_text(
        "solid hull\n" + "  facet normal 0 0 1\n" * 200000 + "endsolid\n", encoding="utf-8"
    )
    return root


@pytest.fixture
def library(tmp_path, tutorials):
    cases, _ = find_cases(tutorials)
    destination = tmp_path / "index"
    result = write_library(
        cases, destination, environment_description="foundation 10", command_help=""
    )
    return destination, result, cases


# ---------------------------------------------------------------------------
# What is left out
# ---------------------------------------------------------------------------


def test_geometry_is_left_out():
    assert excluded_reason("constant/triSurface", "hull.stl", "solid hull") == "geometry/mesh data"


def test_a_generated_mesh_is_left_out_but_its_dictionary_is_kept():
    assert excluded_reason("constant/polyMesh", "points", "(0 0 0)") == "generated mesh"
    assert excluded_reason("system", "blockMeshDict", "convertToMeters 1;") == ""


def test_binary_content_is_left_out():
    assert excluded_reason("constant", "data", "text\x00more") == "binary"


def test_a_file_over_the_limit_is_left_out():
    assert "larger than" in excluded_reason("system", "controlDict", "x" * (max_file_bytes() + 1))


def test_the_limit_is_configurable(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_INDEX_MAX_FILE_KB", "1")

    assert max_file_bytes() == 1024
    assert excluded_reason("system", "controlDict", "x" * 2000) != ""


def test_a_nonsense_limit_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_INDEX_MAX_FILE_KB", "plenty")

    assert max_file_bytes() == 100 * 1024


def test_the_scan_records_what_it_left_out(tutorials):
    cases, stats = find_cases(tutorials)
    hull = next(c for c in cases if c["case_name"] == "hull")

    assert [e["file_name"] for e in hull["excluded"]] == ["hull.stl"]
    assert hull["excluded"][0]["bytes"] > 1_000_000
    assert stats["files_excluded"] == 1
    assert all(e["file_name"] != "hull.stl" for e in hull["entries"])


# ---------------------------------------------------------------------------
# The written library
# ---------------------------------------------------------------------------


def test_cases_are_written_where_the_installation_has_them(library):
    destination, _, _ = library

    case = destination / CASES_SUBDIR / "incompressible/icoFoam/cavity"
    assert (case / "system" / "controlDict").read_text() == "application icoFoam;\n"
    assert (case / "0" / "U").is_file()
    assert (case / "Allrun").is_file()


def test_the_library_holds_no_geometry(library):
    destination, result, _ = library

    written = [p for p in (destination / CASES_SUBDIR).rglob("*") if p.is_file()]
    assert not [p for p in written if p.suffix == ".stl"]
    assert max(p.stat().st_size for p in written) < max_file_bytes()
    assert result.excluded_count == 1
    assert result.excluded_bytes > 1_000_000


def test_the_catalog_has_one_row_per_case(library):
    destination, _, cases = library

    rows = [
        line for line in (destination / CATALOG_FILE).read_text().splitlines()
        if line.startswith("| ") and not line.startswith("| case ")
    ]
    assert len(rows) == len(cases)


def test_the_catalog_names_the_case_its_solver_and_its_path(library):
    destination, _, _ = library

    catalog = (destination / CATALOG_FILE).read_text()
    assert "| cavity | icoFoam | incompressible |" in catalog
    assert "`cases/incompressible/icoFoam/cavity`" in catalog


def test_the_catalog_says_what_was_left_out(library):
    destination, _, _ = library

    row = next(
        line for line in (destination / CATALOG_FILE).read_text().splitlines()
        if line.startswith("| hull |")
    )
    assert "hull.stl" in row
    assert "geometry/mesh data" in row


def test_a_case_that_lost_nothing_says_so(library):
    destination, _, _ = library

    row = next(
        line for line in (destination / CATALOG_FILE).read_text().splitlines()
        if line.startswith("| cavity |")
    )
    assert row.rstrip().endswith("| - |")


def test_the_catalog_is_small_enough_to_read_whole(library):
    destination, _, cases = library

    # ~100 bytes a row: a full installation's 248 cases has to fit in a context window
    # alongside everything else, or the agent is back to searching.
    per_case = len((destination / CATALOG_FILE).read_text().encode()) / len(cases)
    assert per_case < 500


def test_solvers_are_listed_with_their_cases(library):
    destination, _, _ = library

    by_solver = (destination / BY_SOLVER_FILE).read_text()
    assert "## icoFoam (1)" in by_solver
    assert "## interFoam (1)" in by_solver
    assert "`cases/incompressible/icoFoam/cavity`" in by_solver


def test_command_help_becomes_one_file_per_command(tmp_path, tutorials):
    cases, _ = find_cases(tutorials)
    dump = (
        "<command_begin><command>icoFoam</command><help_text>Usage: icoFoam</help_text></command_end>\n\n"
        "<command_begin><command>blockMesh</command><help_text>Usage: blockMesh</help_text></command_end>\n"
    )

    result = write_library(
        cases, tmp_path / "index", environment_description="foundation 10", command_help=dump
    )

    commands = tmp_path / "index" / COMMANDS_SUBDIR
    assert result.command_count == 2
    assert (commands / "icoFoam.txt").read_text().strip() == "Usage: icoFoam"
    assert (commands / "blockMesh.txt").is_file()


def test_a_command_name_cannot_escape_its_directory(tmp_path, tutorials):
    cases, _ = find_cases(tutorials)
    dump = "<command_begin><command>../evil</command><help_text>x</help_text></command_end>\n"

    write_library(
        cases, tmp_path / "index", environment_description="foundation 10", command_help=dump
    )

    assert not (tmp_path / "evil.txt").exists()
    assert (tmp_path / "index" / COMMANDS_SUBDIR / ".._evil.txt").is_file()


def test_library_paths_point_at_the_written_files(library):
    destination, _, _ = library
    paths = library_paths(destination)

    assert paths["catalog"].is_file()
    assert paths["by_solver"].is_file()
    assert paths["cases"].is_dir()
