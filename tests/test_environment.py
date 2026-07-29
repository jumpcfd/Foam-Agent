"""Unit tests for OpenFOAM environment detection.

The probe's output is supplied as fixed text, so these run with no OpenFOAM installed and no
container started. The live checks against real images are the phase-3 acceptance conditions
A4 and A5, not unit tests.
"""

from __future__ import annotations

import pytest

from foamagent.environment import (
    ESI,
    FALLBACK_VERSION,
    FOUNDATION,
    OpenFOAMEnvironment,
    classify_fork,
    clear_environment_cache,
    detect_environment,
    environment_from_config,
    environment_from_probe,
    parse_probe_output,
    unavailable_solvers,
)
from foamagent.execution import CommandResult, DockerBackend, NativeBackend
from foamagent.services.plan import restrict_solvers_to_installed


FOUNDATION_PROBE = """
FOAMAGENT_PROBE_VERSION=10
FOAMAGENT_PROBE_API=
FOAMAGENT_PROBE_PROJECT_DIR=/opt/openfoam10
FOAMAGENT_PROBE_TUTORIALS=/opt/openfoam10/tutorials
FOAMAGENT_PROBE_APPBIN=/opt/openfoam10/platforms/linux64GccDPInt32Opt/bin
FOAMAGENT_PROBE_SOLVERS_BEGIN
icoFoam
simpleFoam
blockMesh
FOAMAGENT_PROBE_SOLVERS_END
"""

ESI_PROBE = """
FOAMAGENT_PROBE_VERSION=v2406
FOAMAGENT_PROBE_API=2406
FOAMAGENT_PROBE_PROJECT_DIR=/usr/lib/openfoam/openfoam2406
FOAMAGENT_PROBE_TUTORIALS=/usr/lib/openfoam/openfoam2406/tutorials
FOAMAGENT_PROBE_APPBIN=/usr/lib/openfoam/openfoam2406/platforms/linux64GccDPInt32Opt/bin
FOAMAGENT_PROBE_SOLVERS_BEGIN
simpleFoam
interFoam
FOAMAGENT_PROBE_SOLVERS_END
"""


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_environment_cache()
    yield
    clear_environment_cache()


# ---------------------------------------------------------------------------
# Fork classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["10", "11", "12", "9"])
def test_a_plain_number_is_the_foundation(version):
    assert classify_fork(version) == FOUNDATION


@pytest.mark.parametrize("version", ["v2406", "v2312", "v2512"])
def test_a_v_prefixed_number_is_esi(version):
    assert classify_fork(version) == ESI


def test_the_api_variable_marks_esi_even_without_the_v():
    assert classify_fork("2406", api="2406") == ESI


def test_an_unrecognised_version_falls_back_to_the_foundation():
    assert classify_fork("dev-branch") == FOUNDATION


# ---------------------------------------------------------------------------
# Probe parsing
# ---------------------------------------------------------------------------


def test_parses_the_foundation_probe():
    parsed = parse_probe_output(FOUNDATION_PROBE)

    assert parsed["version"] == "10"
    assert parsed["tutorials"] == "/opt/openfoam10/tutorials"
    assert parsed["solvers"] == ("blockMesh", "icoFoam", "simpleFoam")


def test_ignores_anything_the_bashrc_printed_around_the_probe():
    noisy = "Using: OpenFOAM-10\nsome banner\n" + FOUNDATION_PROBE + "\ntrailing chatter\n"

    parsed = parse_probe_output(noisy)

    assert parsed["version"] == "10"
    assert "some banner" not in parsed["solvers"]


def test_an_empty_appbin_yields_no_solvers():
    probe = "FOAMAGENT_PROBE_VERSION=10\nFOAMAGENT_PROBE_SOLVERS_BEGIN\nFOAMAGENT_PROBE_SOLVERS_END\n"

    assert parse_probe_output(probe)["solvers"] == ()


def test_environment_from_the_foundation_probe():
    environment = environment_from_probe(FOUNDATION_PROBE)

    assert environment.detected
    assert environment.fork == FOUNDATION
    assert environment.version == "10"
    assert environment.has_solver("icoFoam")
    assert not environment.has_solver("interFoam")


def test_environment_from_the_esi_probe():
    environment = environment_from_probe(ESI_PROBE)

    assert environment.fork == ESI
    assert environment.version == "v2406"
    assert environment.is_esi
    assert environment.has_solver("interFoam")


def test_a_probe_with_no_version_falls_back():
    environment = environment_from_probe("nothing useful here\n")

    assert not environment.detected
    assert environment.fork == FOUNDATION
    assert environment.version == FALLBACK_VERSION


# ---------------------------------------------------------------------------
# has_solver with no measurement
# ---------------------------------------------------------------------------


def test_an_undetected_environment_vouches_for_nothing_and_blocks_nothing():
    """With no measured list there is no evidence against any solver."""
    environment = OpenFOAMEnvironment.fallback()

    assert environment.has_solver("icoFoam")
    assert environment.has_solver("aSolverThatDoesNotExist")
    assert unavailable_solvers(environment, ["anything"]) == ()


def test_unavailable_solvers_lists_what_is_missing():
    environment = environment_from_probe(FOUNDATION_PROBE)

    assert unavailable_solvers(environment, ["icoFoam", "interFoam", "chtMultiRegionFoam"]) == (
        "interFoam",
        "chtMultiRegionFoam",
    )


# ---------------------------------------------------------------------------
# detect_environment
# ---------------------------------------------------------------------------


class _StubBackend(NativeBackend):
    name = "stub"

    def __init__(self, result):
        super().__init__()
        self.result = result
        self.runs = 0

    def run(self, command, working_dir, *, timeout=None):
        self.runs += 1
        return self.result


def test_detection_reads_the_probe_output():
    backend = _StubBackend(CommandResult(0, FOUNDATION_PROBE, ""))

    environment = detect_environment(backend)

    assert environment.fork == FOUNDATION
    assert environment.version == "10"


def test_detection_is_cached_per_backend():
    backend = _StubBackend(CommandResult(0, FOUNDATION_PROBE, ""))

    detect_environment(backend)
    detect_environment(backend)

    assert backend.runs == 1


def test_detection_is_shared_between_backends_reaching_the_same_openfoam(monkeypatch):
    # The retrievers build a backend per call, so a cache keyed on the object would probe
    # once per retrieval -- a container launch each time under the docker runtime.
    monkeypatch.setenv("WM_PROJECT_DIR", "/opt/openfoam10")
    first = _StubBackend(CommandResult(0, FOUNDATION_PROBE, ""))
    second = _StubBackend(CommandResult(0, FOUNDATION_PROBE, ""))

    detect_environment(first)
    detect_environment(second)

    assert second.runs == 0


def test_detection_is_not_shared_between_different_openfoams():
    first = DockerBackend(image="foam-bench:latest", bashrc="/opt/openfoam10/etc/bashrc")
    second = DockerBackend(
        image="opencfd/openfoam-default:2406",
        bashrc="/usr/lib/openfoam/openfoam2406/etc/bashrc",
    )

    assert first.identity() != second.identity()


def test_the_cache_can_be_cleared():
    backend = _StubBackend(CommandResult(0, FOUNDATION_PROBE, ""))

    detect_environment(backend)
    clear_environment_cache()
    detect_environment(backend)

    assert backend.runs == 2


def test_a_failed_probe_falls_back_instead_of_raising():
    backend = _StubBackend(CommandResult(127, "", "bash: source: No such file"))

    environment = detect_environment(backend)

    assert not environment.detected
    assert environment.fork == FOUNDATION


def test_a_timed_out_probe_falls_back():
    backend = _StubBackend(CommandResult(-9, "", "", timed_out=True))

    assert not detect_environment(backend).detected


def test_a_backend_that_cannot_start_falls_back():
    class ExplodingBackend(NativeBackend):
        name = "exploding"

        def run(self, command, working_dir, *, timeout=None):
            raise OSError("docker: command not found")

    assert not detect_environment(ExplodingBackend()).detected


# ---------------------------------------------------------------------------
# environment_from_config
# ---------------------------------------------------------------------------


def test_an_unpinned_fork_is_whatever_is_installed(monkeypatch):
    """Regression: the fork default used to be the string "foundation", which the pinning
    branch could not tell apart from a deliberate choice. An ESI installation was reported
    as Foundation to every caller, including the harness that writes the dictionaries."""
    monkeypatch.setattr(
        "foamagent.execution.backend_for_config",
        lambda config: _StubBackend(CommandResult(0, ESI_PROBE, "")),
    )

    class FakeConfig:
        openfoam_runtime = "native"
        openfoam_fork = ""

    assert environment_from_config(FakeConfig()).fork == ESI


def test_a_pinned_fork_overrides_what_was_measured(monkeypatch):
    """The fork setting says which conventions to generate for, not what is installed."""
    monkeypatch.setattr(
        "foamagent.execution.backend_for_config",
        lambda config: _StubBackend(CommandResult(0, FOUNDATION_PROBE, "")),
    )

    class FakeConfig:
        openfoam_runtime = "native"
        openfoam_fork = "esi"

    environment = environment_from_config(FakeConfig())

    assert environment.fork == ESI
    # The measured facts are kept.
    assert environment.version == "10"
    assert environment.has_solver("icoFoam")


# ---------------------------------------------------------------------------
# Feeding the measurement into planning
# ---------------------------------------------------------------------------


def test_the_solver_catalog_is_narrowed_to_what_is_installed():
    catalog = ["icoFoam", "simpleFoam", "chtMultiRegionFoam"]

    assert restrict_solvers_to_installed(catalog, ["icoFoam", "simpleFoam", "blockMesh"]) == [
        "icoFoam",
        "simpleFoam",
    ]


def test_the_catalog_survives_when_nothing_was_measured():
    catalog = ["icoFoam", "simpleFoam"]

    assert restrict_solvers_to_installed(catalog, None) == catalog
    assert restrict_solvers_to_installed(catalog, ()) == catalog


def test_an_empty_intersection_keeps_the_catalog():
    """An empty choice list would leave the planner with nothing to pick."""
    catalog = ["icoFoam", "simpleFoam"]

    assert restrict_solvers_to_installed(catalog, ["someOtherFoam"]) == catalog
