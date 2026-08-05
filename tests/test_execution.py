"""Unit tests for the OpenFOAM execution backends.

Nothing here starts a container or needs OpenFOAM installed: the tests cover the argv a
backend builds, how it reports outcomes, and which backend a given setting selects. Actually
running a command uses /bin/echo and friends through a stub bashrc.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from foamagent.execution import (
    DEFAULT_IMAGE,
    CommandResult,
    DockerBackend,
    ExecutionPlan,
    NativeBackend,
    OpenFOAMEnvironmentError,
    backend_for_config,
    get_execution_backend,
)


@pytest.fixture
def openfoam_root(tmp_path, monkeypatch):
    """A fake $WM_PROJECT_DIR with an etc/bashrc, so native plans can be built."""
    root = tmp_path / "openfoam_root"
    (root / "etc").mkdir(parents=True)
    (root / "etc" / "bashrc").write_text("# fake bashrc\n", encoding="utf-8")
    monkeypatch.setenv("WM_PROJECT_DIR", str(root))
    return root


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runtime_env", [None, "native", "NATIVE", " native "])
def test_native_is_the_default_and_is_matched_case_insensitively(monkeypatch, runtime_env):
    if runtime_env is None:
        monkeypatch.delenv("FOAMAGENT_OPENFOAM_RUNTIME", raising=False)
    else:
        monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", runtime_env)

    assert isinstance(get_execution_backend(), NativeBackend)


def test_docker_runtime_selects_the_docker_backend(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", "docker")

    assert isinstance(get_execution_backend(), DockerBackend)


def test_an_unknown_runtime_falls_back_to_native(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", "podman")

    assert isinstance(get_execution_backend(), NativeBackend)


def test_backend_for_config_carries_the_image_and_bashrc(monkeypatch):
    monkeypatch.delenv("FOAMAGENT_OPENFOAM_IMAGE", raising=False)
    monkeypatch.delenv("FOAMAGENT_OPENFOAM_BASHRC", raising=False)

    class FakeConfig:
        openfoam_runtime = "docker"
        openfoam_image = "my-image:test"
        openfoam_bashrc = "/opt/openfoam11/etc/bashrc"

    backend = backend_for_config(FakeConfig())

    assert isinstance(backend, DockerBackend)
    assert backend.image == "my-image:test"
    assert backend.bashrc == "/opt/openfoam11/etc/bashrc"


# ---------------------------------------------------------------------------
# NativeBackend argv
# ---------------------------------------------------------------------------


def test_native_plan_sources_the_bashrc_then_runs_the_command(tmp_path, openfoam_root):
    plan = NativeBackend().plan(["bash", str(tmp_path / "Allrun")], str(tmp_path))

    assert plan.container_name is None
    assert plan.argv[:2] == ["bash", "-c"]
    assert f"source {openfoam_root / 'etc' / 'bashrc'}" in plan.argv[2]
    assert f"bash {tmp_path / 'Allrun'}" in plan.argv[2]


def test_native_plan_resolves_a_relative_working_dir(tmp_path, openfoam_root, monkeypatch):
    work_dir = tmp_path / "case"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)

    plan = NativeBackend().plan(["blockMesh"], ".")

    assert plan.working_dir == str(work_dir.resolve())
    assert os.path.isabs(plan.working_dir)


def test_native_plan_quotes_arguments_that_need_it(tmp_path, openfoam_root):
    plan = NativeBackend().plan(["postProcess", "-func", "mag(U)"], str(tmp_path))

    assert "'mag(U)'" in plan.argv[2]


def test_native_plan_without_wm_project_dir_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.delenv("WM_PROJECT_DIR", raising=False)

    with pytest.raises(OpenFOAMEnvironmentError, match="WM_PROJECT_DIR"):
        NativeBackend().plan(["blockMesh"], str(tmp_path))


def test_native_plan_reports_a_missing_bashrc(tmp_path, monkeypatch):
    monkeypatch.setenv("WM_PROJECT_DIR", str(tmp_path / "not_openfoam"))

    with pytest.raises(OpenFOAMEnvironmentError, match="bashrc not found"):
        NativeBackend().plan(["blockMesh"], str(tmp_path))


# ---------------------------------------------------------------------------
# DockerBackend argv
# ---------------------------------------------------------------------------


def test_docker_plan_mounts_the_working_dir_at_the_same_absolute_path(tmp_path):
    work_dir = tmp_path / "case"
    work_dir.mkdir()

    plan = DockerBackend(image="my-image:test").plan(["blockMesh"], str(work_dir))
    argv = plan.argv
    abs_work_dir = str(work_dir.resolve())

    assert argv[:3] == ["docker", "run", "--rm"]
    assert argv[argv.index("-v") + 1] == f"{abs_work_dir}:{abs_work_dir}"
    assert argv[argv.index("-w") + 1] == abs_work_dir


def test_docker_plan_runs_as_the_invoking_user(tmp_path):
    plan = DockerBackend().plan(["blockMesh"], str(tmp_path))

    argv = plan.argv
    assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"


def test_docker_plan_names_the_container_so_it_can_be_killed(tmp_path):
    plan = DockerBackend().plan(["blockMesh"], str(tmp_path))

    assert plan.container_name
    assert plan.argv[plan.argv.index("--name") + 1] == plan.container_name


def test_two_runs_in_the_same_second_get_different_container_names(tmp_path):
    """Docker refuses a name a live container already has, and refuses the whole run.

    Measured: the reference cases run six at a time from one process, and 107 of 110 died
    with "the container name is already in use" because the name was the pid and the wall
    clock second.
    """
    # A fresh backend per run, as `backend_for_config` hands out: a per-instance counter
    # would restart at one for each of them and collide all over again.
    names = {DockerBackend().plan(["blockMesh"], str(tmp_path)).container_name
             for _ in range(50)}

    assert len(names) == 50


def test_docker_plan_uses_the_configured_image_and_bashrc(tmp_path):
    plan = DockerBackend(image="my-image:test", bashrc="/opt/openfoam11/etc/bashrc").plan(
        ["blockMesh"], str(tmp_path)
    )

    assert "my-image:test" in plan.argv
    assert "source /opt/openfoam11/etc/bashrc" in plan.argv[-1]


def test_docker_plan_falls_back_to_the_default_image(tmp_path, monkeypatch):
    monkeypatch.delenv("FOAMAGENT_OPENFOAM_IMAGE", raising=False)

    plan = DockerBackend().plan(["blockMesh"], str(tmp_path))

    assert DEFAULT_IMAGE in plan.argv


def test_docker_plan_resolves_a_relative_working_dir(tmp_path, monkeypatch):
    work_dir = tmp_path / "case"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)

    plan = DockerBackend().plan(["blockMesh"], ".")

    abs_work_dir = str(work_dir.resolve())
    assert plan.argv[plan.argv.index("-v") + 1] == f"{abs_work_dir}:{abs_work_dir}"


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


class _EchoBackend(NativeBackend):
    """Runs the command directly, with no OpenFOAM environment in the way."""

    def plan(self, command, working_dir):
        return ExecutionPlan(argv=list(command), working_dir=os.path.abspath(working_dir))


def test_run_returns_output_and_a_zero_return_code(tmp_path):
    result = _EchoBackend().run(["echo", "hello"], str(tmp_path))

    assert result.ok
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


def test_run_reports_a_failure_instead_of_raising(tmp_path):
    result = _EchoBackend().run(["false"], str(tmp_path))

    assert not result.ok
    assert result.returncode != 0


def test_run_marks_a_timeout(tmp_path):
    result = _EchoBackend().run(["sleep", "10"], str(tmp_path), timeout=0.2)

    assert result.timed_out
    assert not result.ok


def test_run_checked_raises_on_failure(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        _EchoBackend().run_checked(["false"], str(tmp_path))


def test_run_checked_returns_the_result_on_success(tmp_path):
    result = _EchoBackend().run_checked(["echo", "ok"], str(tmp_path))

    assert result.stdout.strip() == "ok"


def test_run_uses_the_working_dir(tmp_path):
    (tmp_path / "marker.txt").write_text("x")

    result = _EchoBackend().run(["ls"], str(tmp_path))

    assert "marker.txt" in result.stdout


def test_docker_timeout_kills_the_container(tmp_path, monkeypatch):
    """Killing the docker client alone leaves the container running."""
    killed = []

    real_run = subprocess.run

    def fake_run(argv, *args, **kwargs):
        if argv[:2] == ["docker", "kill"]:
            killed.append(argv[2])
            return subprocess.CompletedProcess(argv, 0)
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    backend = DockerBackend()
    plan = ExecutionPlan(argv=["sleep", "10"], working_dir=str(tmp_path), container_name="c1")
    monkeypatch.setattr(backend, "plan", lambda command, working_dir: plan)

    result = backend.run(["sleep", "10"], str(tmp_path), timeout=0.2)

    assert result.timed_out
    assert killed == ["c1"]


def test_command_result_ok_requires_both_conditions():
    assert CommandResult(0, "", "").ok
    assert not CommandResult(1, "", "").ok
    assert not CommandResult(0, "", "", timed_out=True).ok
