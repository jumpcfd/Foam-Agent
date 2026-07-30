"""Unit tests for library location, the tutorial scan and the CLI.

No OpenFOAM and no container: the tutorials are a handful of files in tmp_path, and the
execution backend is a stub. Building against a real installation is acceptance condition
A7, not a unit test.
"""

from __future__ import annotations

import re

import pytest

from foamagent.cli import main
from foamagent.environment import OpenFOAMEnvironment
from foamagent.execution import CommandResult, NativeBackend
from foamagent.indexing import (
    detected_environment,
    index_dir,
    index_name,
    index_root,
    list_indexes,
    resolve_library_dir,
)
from foamagent.indexing.build import (
    COMMAND_HELP_SCRIPT,
    BuildResult,
    build_index,
    collect_command_help,
    copy_tutorials,
)
from foamagent.indexing.tutorials import find_cases


FOUNDATION = OpenFOAMEnvironment(
    fork="foundation",
    version="10",
    solvers=("icoFoam", "simpleFoam"),
    tutorials="/opt/openfoam10/tutorials",
)
ESI = OpenFOAMEnvironment(
    fork="esi", version="v2406", solvers=("simpleFoam",), tutorials="/opt/esi/tutorials"
)


@pytest.fixture
def index_home(tmp_path, monkeypatch):
    home = tmp_path / "indexes"
    monkeypatch.setenv("FOAMAGENT_INDEX_DIR", str(home))
    return home


@pytest.fixture
def tutorial_tree(tmp_path):
    """A miniature $FOAM_TUTORIALS: incompressible/icoFoam/cavity."""
    case = tmp_path / "tutorials" / "incompressible" / "icoFoam" / "cavity"
    (case / "system").mkdir(parents=True)
    (case / "0").mkdir()
    (case / "system" / "controlDict").write_text(
        "/* licence header */\napplication icoFoam;  // trailing comment\n", encoding="utf-8"
    )
    (case / "system" / "blockMeshDict").write_text("convertToMeters 0.1;\n", encoding="utf-8")
    (case / "0" / "U").write_text("dimensions [0 1 -1 0 0 0 0];\n", encoding="utf-8")
    (case / "Allrun").write_text("#!/bin/sh\nblockMesh\nicoFoam\n", encoding="utf-8")
    return tmp_path / "tutorials"


# ---------------------------------------------------------------------------
# Index locations
# ---------------------------------------------------------------------------


def test_index_root_honours_the_override(index_home):
    assert index_root() == index_home.resolve()


def test_index_root_defaults_under_the_cache_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("FOAMAGENT_INDEX_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    assert index_root() == (tmp_path / "foamagent" / "indexes").resolve()


def test_index_root_is_outside_the_repository(index_home, monkeypatch):
    """A rebuilt index is machine state; it must not land in the working tree."""
    monkeypatch.delenv("FOAMAGENT_INDEX_DIR", raising=False)

    from foamagent import paths

    assert paths.repo_root() not in index_root().parents


def test_each_fork_and_version_gets_its_own_directory(index_home):
    assert index_name(FOUNDATION) == "foundation-10"
    assert index_name(ESI) == "esi-v2406"
    assert index_dir(FOUNDATION) != index_dir(ESI)


def test_listing_is_empty_when_nothing_was_built(index_home):
    assert list_indexes() == []


def test_listing_reports_what_a_built_library_contains(index_home):
    index_dir(FOUNDATION).mkdir(parents=True)
    (index_dir(FOUNDATION) / "catalog.md").write_text("# catalogue\n")

    (info,) = list_indexes()

    assert info.name == "foundation-10"
    assert info.has_library
    assert info.size_bytes > 0

# ---------------------------------------------------------------------------
# Finding the library built for this installation
# ---------------------------------------------------------------------------


def test_there_is_no_library_until_one_is_built(index_home):
    # The library has no shipped fallback: it is this installation's own tutorials, and
    # somebody else's would list cases that are not here.
    assert resolve_library_dir(FOUNDATION) is None


def test_a_built_library_is_found(index_home):
    index_dir(FOUNDATION).mkdir(parents=True)
    (index_dir(FOUNDATION) / "catalog.md").write_text("# catalogue")

    assert resolve_library_dir(FOUNDATION) == index_dir(FOUNDATION)


def test_a_library_built_for_another_installation_is_not_used(index_home):
    index_dir(ESI).mkdir(parents=True)
    (index_dir(ESI) / "catalog.md").write_text("# catalogue")

    assert resolve_library_dir(FOUNDATION) is None


def test_an_undetectable_environment_is_reported_as_none(monkeypatch):
    def explode(*args, **kwargs):
        raise OSError("docker: command not found")

    monkeypatch.setattr("foamagent.environment.detect_environment", explode)

    assert detected_environment() is None


# ---------------------------------------------------------------------------
# Scanning tutorials
# ---------------------------------------------------------------------------


def test_a_case_is_found_with_its_classification(tutorial_tree):
    cases, stats = find_cases(tutorial_tree)

    assert len(cases) == 1
    case = cases[0]
    assert case["case_name"] == "cavity"
    assert case["solver"] == "icoFoam"
    assert case["domain"] == "incompressible"
    assert stats["directories_with_system"] == 1


def test_the_allrun_script_is_read(tutorial_tree):
    (case,) = find_cases(tutorial_tree)[0]

    assert "icoFoam" in case["allrun"]


def test_a_shared_blockmeshdict_is_pulled_into_the_case(tmp_path):
    """A case whose Allrun points at resources/blockMesh has no dict of its own."""
    tutorials = tmp_path / "tutorials"
    resource = tutorials / "resources" / "blockMesh"
    resource.mkdir(parents=True)
    (resource / "pipe").write_text("convertToMeters 1;\n", encoding="utf-8")

    case = tutorials / "incompressible" / "icoFoam" / "pipe"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application icoFoam;\n", encoding="utf-8")
    (case / "Allrun").write_text(
        "blockMesh -dict $FOAM_TUTORIALS/resources/blockMesh/pipe\n", encoding="utf-8"
    )

    cases, _ = find_cases(tutorials)

    found = next(c for c in cases if c["case_name"] == "pipe")
    names = [e["file_name"] for e in found["entries"]]
    assert "blockMeshDict" in names


# ---------------------------------------------------------------------------
# Copying tutorials out of the environment
# ---------------------------------------------------------------------------


class _StubBackend(NativeBackend):
    name = "stub"

    def __init__(self, result=None):
        super().__init__()
        self.result = result or CommandResult(0, "", "")
        self.commands = []

    def run(self, command, working_dir, *, timeout=None):
        self.commands.append(list(command))
        return self.result


def test_a_readable_tutorials_directory_is_copied_directly(tmp_path, tutorial_tree):
    environment = OpenFOAMEnvironment(tutorials=str(tutorial_tree))
    backend = _StubBackend()

    target = copy_tutorials(environment, tmp_path / "work", backend)

    assert (target / "incompressible" / "icoFoam" / "cavity" / "system" / "controlDict").is_file()
    assert backend.commands == []  # no container needed


def test_the_scan_never_touches_the_installation(tmp_path, tutorial_tree):
    """find_cases writes into the cases it reads, so it must see a copy."""
    environment = OpenFOAMEnvironment(tutorials=str(tutorial_tree))

    target = copy_tutorials(environment, tmp_path / "work", _StubBackend())

    assert target != tutorial_tree
    assert not str(target).startswith(str(tutorial_tree))


def test_an_unreadable_tutorials_path_is_copied_by_the_environment(tmp_path):
    environment = OpenFOAMEnvironment(tutorials="/opt/openfoam10/tutorials")
    backend = _StubBackend()

    with pytest.raises(RuntimeError, match="not copied"):
        copy_tutorials(environment, tmp_path / "work", backend)

    assert backend.commands[0][:2] == ["cp", "-a"]
    assert backend.commands[0][2] == "/opt/openfoam10/tutorials"


def test_a_failed_copy_is_reported(tmp_path):
    environment = OpenFOAMEnvironment(tutorials="/opt/openfoam10/tutorials")
    backend = _StubBackend(CommandResult(1, "", "cp: cannot stat"))

    with pytest.raises(RuntimeError, match="cannot stat"):
        copy_tutorials(environment, tmp_path / "work", backend)


def test_an_environment_with_no_tutorials_path_is_reported(tmp_path):
    with pytest.raises(RuntimeError, match="FOAM_TUTORIALS"):
        copy_tutorials(OpenFOAMEnvironment(tutorials=""), tmp_path, _StubBackend())


# ---------------------------------------------------------------------------
# Command help
# ---------------------------------------------------------------------------


def test_command_help_is_collected_in_one_pass(tmp_path):
    """One shell loop inside the environment, not one container per command."""
    backend = _StubBackend(
        CommandResult(0, "<command_begin><command>icoFoam</command><help_text>x</help_text></command_end>\n", "")
    )

    output = collect_command_help(backend, working_dir=tmp_path)

    assert len(backend.commands) == 1
    assert backend.commands[0][:2] == ["bash", "-c"]
    assert "<command_begin>" in output


def test_a_missing_appbin_is_reported(tmp_path):
    backend = _StubBackend(CommandResult(3, "", ""))

    with pytest.raises(RuntimeError, match="FOAM_APPBIN"):
        collect_command_help(backend, working_dir=tmp_path)


def test_the_help_script_survives_a_failing_command():
    """One application that exits non-zero on -help must not end the sweep."""
    assert "|| true" in COMMAND_HELP_SCRIPT


# ---------------------------------------------------------------------------
# build_index
# ---------------------------------------------------------------------------


def test_build_writes_the_reference_library(index_home, tutorial_tree):
    environment = OpenFOAMEnvironment(
        fork="foundation", version="10", solvers=("icoFoam",), tutorials=str(tutorial_tree)
    )
    backend = _StubBackend(
        CommandResult(0, "<command_begin><command>icoFoam</command><help_text>h</help_text></command_end>\n", "")
    )

    result = build_index(environment, backend=backend)

    assert result.case_count == 1
    assert result.command_count == 1
    assert result.library is not None
    assert result.library.case_count == 1
    assert (index_dir(environment) / "catalog.md").is_file()
    assert (index_dir(environment) / "cases" / "incompressible/icoFoam/cavity/system/controlDict").is_file()
    assert (index_dir(environment) / "commands" / "icoFoam.txt").is_file()
    assert resolve_library_dir(environment) == index_dir(environment)


def test_build_removes_the_copied_tutorials(index_home, tutorial_tree):
    environment = OpenFOAMEnvironment(
        fork="foundation", version="10", tutorials=str(tutorial_tree)
    )
    backend = _StubBackend(
        CommandResult(0, "<command_begin><command>icoFoam</command><help_text>h</help_text></command_end>\n", "")
    )

    result = build_index(environment, backend=backend)

    assert not (result.index_path / "work").exists()


def test_build_refuses_an_undetected_environment(index_home):
    with pytest.raises(RuntimeError, match="Could not detect"):
        build_index(OpenFOAMEnvironment.fallback(), backend=_StubBackend())


def test_build_reports_an_empty_tutorials_tree(index_home, tmp_path):
    empty = tmp_path / "tutorials"
    empty.mkdir()
    environment = OpenFOAMEnvironment(fork="foundation", version="10", tutorials=str(empty))

    with pytest.raises(RuntimeError, match="No tutorial cases"):
        build_index(environment, backend=_StubBackend())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_index_list_says_where_to_look(index_home, capsys):
    assert main(["index", "list"]) == 0

    assert "No built indexes" in capsys.readouterr().out


def test_index_list_shows_a_built_index(index_home, capsys):
    index_dir(FOUNDATION).mkdir(parents=True)
    (index_dir(FOUNDATION) / "catalog.md").write_text("# catalogue")

    main(["index", "list"])

    assert "foundation-10" in capsys.readouterr().out


def test_no_subcommand_prints_help(capsys):
    assert main([]) == 1

    # Python 3.14 colours argparse output, so compare against the text without the escapes.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert "usage: foamagent" in plain


def _record_build_flags(monkeypatch, index_home):
    """Drive `index build` with a fake builder and return the kwargs it was called with."""
    monkeypatch.setattr(
        "foamagent.environment.environment_from_config", lambda config: FOUNDATION
    )
    monkeypatch.setattr("foamagent.execution.backend_for_config", lambda config: _StubBackend())

    seen = {}

    def fake_build(environment, **kwargs):
        seen.update(kwargs)
        return BuildResult(
            environment=environment,
            index_path=index_dir(environment),
            case_count=1,
            command_count=1,
            seconds=0.0,
        )

    monkeypatch.setattr("foamagent.indexing.build.build_index", fake_build)
    return seen


def test_index_build_keeps_no_tutorial_copy_by_default(index_home, monkeypatch):
    seen = _record_build_flags(monkeypatch, index_home)

    assert main(["index", "build"]) == 0

    assert seen["keep_tutorials"] is False


def test_index_build_can_keep_the_tutorial_copy(index_home, monkeypatch):
    seen = _record_build_flags(monkeypatch, index_home)

    assert main(["index", "build", "--keep-tutorials"]) == 0

    assert seen["keep_tutorials"] is True


def test_index_build_reports_an_undetectable_environment(index_home, monkeypatch, capsys):
    monkeypatch.setattr(
        "foamagent.environment.environment_from_config",
        lambda config: OpenFOAMEnvironment.fallback(),
    )
    monkeypatch.setattr("foamagent.execution.backend_for_config", lambda config: _StubBackend())

    assert main(["index", "build"]) == 1

    assert "No OpenFOAM environment could be detected" in capsys.readouterr().out
