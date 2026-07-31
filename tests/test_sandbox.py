"""The place a review does its arithmetic.

What is under test is mostly the command line: that the case is mounted read-only, that
there is no network, and that neither the model nor the settings file can widen either.
Running a real container is left to the manual checks -- what matters here is that no code
path can build a permissive one.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from fastmcp import Client

from foamagent.mcp import fastmcp_server as server
from foamagent.mcp import sandbox as sandbox_tool
from foamagent.review import channel, sandbox
from foamagent.review.settings import SANDBOX_TOOL_NAME, ChannelSettings, SandboxSettings, load_settings


@pytest.fixture(autouse=True)
def own_config(tmp_path, monkeypatch):
    """Never read the developer's own settings while testing."""
    monkeypatch.setenv("FOAMAGENT_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("FOAMAGENT_CONFIG_FILE", raising=False)


@pytest.fixture
def case(tmp_path):
    case_dir = tmp_path / "cavity"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "spec.md").write_text("Re=1000\n", encoding="utf-8")
    return case_dir


def _argv(case, work=None, settings=None):
    work = work or sandbox.work_dir(case, 1)
    script = sandbox.save_script("print(1)", Path(work))
    return sandbox.docker_argv(script, case_dir=case, settings=settings or SandboxSettings())


# ---------------------------------------------------------------------------
# A1: the container the script runs in
# ---------------------------------------------------------------------------


def test_the_case_is_mounted_read_only(case):
    argv = _argv(case)

    assert f"{case.resolve()}:/case:ro" in argv


def test_no_argument_mounts_the_case_writable(case):
    argv = _argv(case)

    mounts = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-v"]
    for mount in mounts:
        source = mount.split(":")[0]
        if Path(source) == case.resolve():
            assert mount.endswith(":ro")


def test_the_script_has_no_network(case):
    argv = _argv(case)

    assert "--network" in argv
    assert argv[argv.index("--network") + 1] == "none"


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--memory", sandbox.MEMORY_LIMIT),
        ("--memory-swap", sandbox.MEMORY_LIMIT),
        ("--cpus", sandbox.CPU_LIMIT),
        ("--pids-limit", sandbox.PIDS_LIMIT),
        ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges"),
    ],
)
def test_the_script_runs_under_limits(case, flag, value):
    argv = _argv(case)

    assert flag in argv
    assert argv[argv.index(flag) + 1] == value


def test_the_container_filesystem_is_read_only_apart_from_the_work_directory(case):
    argv = _argv(case)

    assert "--read-only" in argv
    assert argv[-2:] == ["python", "/work/script-1.py"]


def test_the_image_comes_from_the_settings_not_the_caller(case, tmp_path):
    config = tmp_path / "config" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("review:\n  sandbox:\n    image: my-image:1\n", encoding="utf-8")

    argv = _argv(case, settings=load_settings().sandbox)

    assert "my-image:1" in argv
    # And the tool the model calls takes a script and nothing else.
    assert set(sandbox_tool.ScriptRequest.model_fields) == {"script"}


def test_scripts_are_numbered_rather_than_overwritten(case):
    work = sandbox.work_dir(case, 1)

    first = sandbox.save_script("print(1)", work)
    second = sandbox.save_script("print(2)", work)

    assert first.name == "script-1.py"
    assert second.name == "script-2.py"
    assert first.read_text(encoding="utf-8") == "print(1)\n"


def test_the_work_directory_lives_in_the_case(case):
    assert sandbox.work_dir(case, 2) == case / "review-work" / "2"
    assert sandbox.work_dir(case, sandbox.REPORT_WORK) == case / "review-work" / "report"


def test_the_script_runs_as_the_user_who_owns_the_case(case):
    argv = _argv(case)

    assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"


# ---------------------------------------------------------------------------
# A4: nothing to run scripts with
# ---------------------------------------------------------------------------


def test_scripts_are_unavailable_when_switched_off():
    reason = sandbox.available(SandboxSettings(runtime="none"))

    assert reason and "none" in reason


def test_scripts_are_unavailable_without_docker(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)

    reason = sandbox.available(SandboxSettings())

    assert reason and "docker" in reason


def test_an_unavailable_sandbox_starts_nothing(case, monkeypatch):
    monkeypatch.setattr(
        sandbox.subprocess, "run", lambda *a, **k: pytest.fail("started a container")
    )

    result = sandbox.run_script(
        "print(1)",
        case_dir=case,
        destination=sandbox.work_dir(case, 1),
        settings=SandboxSettings(runtime="none"),
    )

    assert not result.ok
    assert not result.script_file
    assert "none" in result.detail


def test_the_tool_reports_an_unavailable_sandbox_rather_than_failing(case, monkeypatch):
    monkeypatch.setenv(sandbox_tool.CASE_DIR_ENV, str(case))
    monkeypatch.setenv(sandbox_tool.WORK_DIR_ENV, str(sandbox.work_dir(case, 1)))
    monkeypatch.setattr(sandbox, "available", lambda settings=None: "no docker here")

    response = asyncio.run(sandbox_tool.run_script(sandbox_tool.ScriptRequest(script="print(1)")))

    assert response.available is False
    assert "no docker here" in response.detail


def test_the_tool_refuses_when_it_was_given_no_case(monkeypatch):
    monkeypatch.delenv(sandbox_tool.CASE_DIR_ENV, raising=False)
    monkeypatch.delenv(sandbox_tool.WORK_DIR_ENV, raising=False)

    response = asyncio.run(sandbox_tool.run_script(sandbox_tool.ScriptRequest(script="print(1)")))

    assert response.available is False


def test_a_failed_script_is_a_result_not_an_error(case, monkeypatch):
    class _Completed:
        returncode = 1
        stdout = "partial\n"
        stderr = "Traceback\n"

    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(sandbox, "ensure_image", lambda image: None)
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: _Completed())

    result = sandbox.run_script(
        "raise SystemExit(1)", case_dir=case, destination=sandbox.work_dir(case, 1)
    )

    assert not result.ok
    assert result.exit_code == 1
    assert "Traceback" in result.stderr
    # The script stays in the case even though it failed: what was attempted is part of
    # the record.
    assert Path(result.script_file).is_file()


def test_an_image_that_cannot_be_fetched_is_reported_rather_than_run(case, monkeypatch):
    class _Failed:
        returncode = 1
        stdout = ""
        stderr = "no such image\n"

    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: _Failed())

    result = sandbox.run_script("print(1)", case_dir=case, destination=sandbox.work_dir(case, 1))

    assert not result.ok
    assert "Could not fetch" in result.detail
    # Nothing was written, because nothing was attempted.
    assert not result.script_file


def test_output_is_clipped(case, monkeypatch):
    class _Completed:
        returncode = 0
        stdout = "x" * (sandbox.OUTPUT_LIMIT + 5000)
        stderr = ""

    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(sandbox, "ensure_image", lambda image: None)
    monkeypatch.setattr(sandbox.subprocess, "run", lambda *a, **k: _Completed())

    result = sandbox.run_script("print(1)", case_dir=case, destination=sandbox.work_dir(case, 1))

    assert "truncated" in result.stdout
    assert len(result.stdout) < sandbox.OUTPUT_LIMIT + 200


# ---------------------------------------------------------------------------
# A2: how the review is handed the sandbox
# ---------------------------------------------------------------------------


def test_the_review_is_given_its_own_server(case):
    settings = ChannelSettings()

    argv = settings.argv("review this", mcp_config=Path("/tmp/mcp.json"))

    assert argv[argv.index("--mcp-config") + 1] == "/tmp/mcp.json"
    assert "--strict-mcp-config" in argv
    assert SANDBOX_TOOL_NAME in argv[argv.index("--allowed-tools") + 1]
    # Still last, after every flag: the prompt is not a tool name.
    assert argv[-1] == "review this"


def test_without_a_sandbox_the_review_is_given_no_server():
    argv = ChannelSettings().argv("review this")

    assert "--mcp-config" not in argv
    assert SANDBOX_TOOL_NAME not in " ".join(argv)


def test_the_configuration_names_one_case_one_tool_and_one_server(case):
    config = channel.sandbox_config(str(case), sandbox.work_dir(case, 1))

    server_config = config["mcpServers"]["foamagent"]
    assert server_config["args"][-2:] == ["--profile", "sandbox"]
    assert server_config["env"][sandbox_tool.CASE_DIR_ENV] == str(case)
    assert server_config["env"][sandbox_tool.WORK_DIR_ENV].endswith("review-work/1")


def test_the_configuration_is_written_for_one_run_and_then_removed(case):
    settings = ChannelSettings()

    with channel._sandbox_config_file(str(case), sandbox.work_dir(case, 1), settings) as path:
        assert path.is_file()
        written = json.loads(path.read_text(encoding="utf-8"))
        assert "foamagent" in written["mcpServers"]

    assert not path.exists()


def test_a_switched_off_sandbox_is_not_configured(case):
    settings = ChannelSettings(sandbox=SandboxSettings(runtime="none"))

    with channel._sandbox_config_file(str(case), sandbox.work_dir(case, 1), settings) as path:
        assert path is None


def test_a_command_that_takes_no_server_flag_is_not_given_one(case, tmp_path):
    config = tmp_path / "config" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "review:\n  command: [my-harness, run]\n  mcp_config_flag: ''\n", encoding="utf-8"
    )

    settings = load_settings()

    assert settings.offers_sandbox is False
    with channel._sandbox_config_file(str(case), sandbox.work_dir(case, 1), settings) as path:
        assert path is None


# ---------------------------------------------------------------------------
# A2 (continued): which server tools a review may name
# ---------------------------------------------------------------------------


def test_only_this_packages_server_tool_survives_the_allowlist(tmp_path):
    config = tmp_path / "config" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "review:\n"
        "  allowed_tools: [Read, mcp__foamagent__run_script, mcp__github__create_issue, "
        "mcp__shell__exec]\n",
        encoding="utf-8",
    )

    tools = load_settings().allowed_tools

    assert tools == ["Read", SANDBOX_TOOL_NAME]


def test_a_write_tool_is_still_dropped(tmp_path):
    config = tmp_path / "config" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("review:\n  allowed_tools: [Read, Write, Bash]\n", encoding="utf-8")

    assert load_settings().allowed_tools == ["Read"]


# ---------------------------------------------------------------------------
# A6: what the sandbox profile serves
# ---------------------------------------------------------------------------


def _tool_names(profile):
    async def main():
        async with Client(server.build_server(profile)) as client:
            return sorted(t.name for t in await client.list_tools())

    return asyncio.run(main())


def test_the_sandbox_profile_serves_one_tool():
    assert _tool_names("sandbox") == ["run_script"]


def test_the_full_profile_does_not_serve_the_script_tool():
    names = _tool_names("full")

    assert "run_script" not in names
    assert "request_review" in names


def test_an_unknown_profile_is_refused():
    with pytest.raises(ValueError):
        server.build_server("everything")
