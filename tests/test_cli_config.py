"""Unit tests for `foamagent config` and `foamagent doctor`.

Acceptance conditions A7 to A11 of plan_docs/11a-phase7a-spec.md. Nothing here starts a
container, a solver or a model: the checks that would are stubbed, and what is under test
is what the commands print, what they write, and what they exit with.
"""

from __future__ import annotations

import pytest

from foamagent import settings as settings_module
from foamagent.cli import main


def test_version_prints_the_installed_package_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert "foamagent" in capsys.readouterr().out


@pytest.fixture(autouse=True)
def no_ambient_proxy(monkeypatch):
    """A proxy set on the machine running these tests must not add an unplanned wizard question."""
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                 "NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def user_config(tmp_path, monkeypatch):
    path = tmp_path / "user" / "config.yaml"
    path.parent.mkdir(parents=True)
    monkeypatch.setenv("FOAMAGENT_CONFIG_FILE", str(path))
    return path


@pytest.fixture
def work_dir(tmp_path, monkeypatch):
    """A directory to be in, without a project settings file in it or above it."""
    directory = tmp_path / "work"
    directory.mkdir()
    monkeypatch.chdir(directory)
    return directory


# ---------------------------------------------------------------------------
# A7: show every setting with its origin
# ---------------------------------------------------------------------------


def test_show_lists_every_setting_with_where_it_came_from(user_config, capsys, monkeypatch):
    user_config.write_text("review:\n  command: [my-harness]\n", encoding="utf-8")
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", "docker")

    assert main(["config", "show"]) == 0

    out = capsys.readouterr().out
    assert "openfoam.runtime" in out
    assert "review.sandbox.image" in out
    assert "env FOAMAGENT_OPENFOAM_RUNTIME" in out
    assert "my-harness" in out
    assert "default" in out
    assert str(user_config) in out


def test_show_says_which_files_are_being_read(user_config, capsys):
    user_config.write_text("openfoam:\n  image: mine\n", encoding="utf-8")

    main(["config", "show"])

    assert "user settings" in capsys.readouterr().out


def test_path_names_the_files(user_config, work_dir, capsys):
    assert main(["config", "path"]) == 0

    out = capsys.readouterr().out
    assert str(user_config) in out
    assert "templates" in out


# ---------------------------------------------------------------------------
# A8: writing one setting
# ---------------------------------------------------------------------------


def test_set_writes_one_key_and_keeps_the_others(user_config, capsys):
    user_config.write_text(
        "openfoam:\n  image: keep-me\nreview:\n  command: [old]\n", encoding="utf-8"
    )

    assert main(["config", "set", "review.command", "[new]"]) == 0

    data = settings_module.read_yaml(user_config)
    assert data["review"]["command"] == ["new"]
    assert data["openfoam"]["image"] == "keep-me"


def test_set_creates_the_file_when_there_is_none(user_config):
    assert not user_config.exists()

    main(["config", "set", "openfoam.runtime", "docker"])

    assert settings_module.read_yaml(user_config) == {"openfoam": {"runtime": "docker"}}


def test_set_reads_the_value_as_yaml(user_config):
    main(["config", "set", "review.timeout_seconds", "900"])
    main(["config", "set", "review.command", "[claude, -p]"])

    data = settings_module.read_yaml(user_config)
    assert data["review"]["timeout_seconds"] == 900
    assert data["review"]["command"] == ["claude", "-p"]


def test_set_project_writes_next_to_the_work(user_config, work_dir, monkeypatch):
    monkeypatch.delenv("FOAMAGENT_PROJECT_CONFIG", raising=False)

    assert main(["config", "set", "--project", "openfoam.image", "local-image"]) == 0

    written = work_dir / "foamagent.yaml"
    assert settings_module.read_yaml(written) == {"openfoam": {"image": "local-image"}}
    assert not user_config.exists()


def test_a_project_setting_beats_the_user_one(user_config, work_dir, monkeypatch):
    monkeypatch.delenv("FOAMAGENT_PROJECT_CONFIG", raising=False)
    main(["config", "set", "openfoam.image", "from-user"])
    main(["config", "set", "--project", "openfoam.image", "from-project"])

    from foamagent.config import Config

    assert Config().openfoam_image == "from-project"


def test_unset_puts_the_default_back(user_config):
    main(["config", "set", "openfoam.runtime", "docker"])

    assert main(["config", "unset", "openfoam.runtime"]) == 0

    from foamagent.config import Config

    assert Config().openfoam_runtime == "native"


def test_unset_of_something_absent_is_not_an_error(user_config, capsys):
    assert main(["config", "unset", "openfoam.runtime"]) == 0
    assert "nothing to remove" in capsys.readouterr().out


def test_the_review_mode_survives_being_written_and_read(user_config):
    """YAML 1.1 reads a bare `off` as false, and `review.mode: false` is not a mode."""
    assert main(["config", "set", "review.mode", "off"]) == 0

    from foamagent.review.settings import load_settings

    assert settings_module.read_yaml(user_config)["review"]["mode"] == "off"
    assert load_settings().mode == "off"


def test_show_lists_the_review_mode(user_config, capsys):
    main(["config", "show"])

    rows = [line for line in capsys.readouterr().out.splitlines() if line.split()[:1] == ["review.mode"]]
    assert rows and "full" in rows[0]


# ---------------------------------------------------------------------------
# A9: an unknown key is refused, with the known ones listed
# ---------------------------------------------------------------------------


def test_setting_an_unknown_key_lists_the_known_ones(user_config, capsys):
    assert main(["config", "set", "openfoam.runtimee", "docker"]) == 1

    out = capsys.readouterr().out
    assert "Unknown setting" in out
    assert "openfoam.runtime" in out
    assert "review.command" in out
    assert not user_config.exists()


# ---------------------------------------------------------------------------
# A10: the interactive setup needs a terminal
# ---------------------------------------------------------------------------


def test_the_wizard_without_a_terminal_says_what_to_run_instead(user_config, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert main(["config"]) == 1

    out = capsys.readouterr().out
    assert "terminal" in out
    assert "foamagent config set" in out


def test_the_wizard_writes_the_answers(user_config, capsys, monkeypatch):
    answers = iter(["docker", "my-image:1", "/opt/foam/etc/bashrc", "custom",
                    "claude -p --dangerously-skip-permissions", "none", "y"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("foamagent.cli._cmd_doctor", lambda args: 0)
    monkeypatch.setattr("foamagent.execution.detect_docker_bashrc", lambda image, **kw: None)

    assert main(["config"]) == 0

    data = settings_module.read_yaml(user_config)
    assert data["openfoam"] == {
        "runtime": "docker", "image": "my-image:1", "bashrc": "/opt/foam/etc/bashrc"
    }
    assert data["review"]["command"] == ["claude", "-p", "--dangerously-skip-permissions"]
    assert data["review"]["sandbox"]["runtime"] == "none"


def test_the_wizard_writes_nothing_when_the_answer_is_no(user_config, monkeypatch):
    answers = iter(["native", "custom", "claude -p", "docker", "n"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert main(["config"]) == 0
    assert not user_config.exists()


def test_the_wizard_suggests_the_probed_bashrc(user_config, monkeypatch):
    """A detected bashrc becomes the suggested default, not the hard-coded v10 path."""
    answers = iter(["docker", "esi-image:2406", "", "custom", "claude -p", "none", "y"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("foamagent.cli._cmd_doctor", lambda args: 0)
    monkeypatch.setattr(
        "foamagent.execution.detect_docker_bashrc",
        lambda image, **kw: "/usr/lib/openfoam/openfoam2406/etc/bashrc" if image == "esi-image:2406" else None,
    )

    assert main(["config"]) == 0

    data = settings_module.read_yaml(user_config)
    assert data["openfoam"]["bashrc"] == "/usr/lib/openfoam/openfoam2406/etc/bashrc"


def test_the_wizard_falls_back_to_the_default_bashrc_when_detection_fails(user_config, monkeypatch):
    answers = iter(["docker", "my-image:1", "", "custom", "claude -p", "none", "y"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("foamagent.cli._cmd_doctor", lambda args: 0)
    monkeypatch.setattr("foamagent.execution.detect_docker_bashrc", lambda image, **kw: None)

    assert main(["config"]) == 0

    from foamagent.config import DEFAULT_BASHRC

    data = settings_module.read_yaml(user_config)
    assert data["openfoam"]["bashrc"] == DEFAULT_BASHRC


def test_the_wizard_offers_to_prefix_the_review_command_with_a_detected_proxy(
    user_config, monkeypatch
):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("http_proxy", "http://proxy.example:8080")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    answers = iter(["native", "custom", "claude -p", "y", "none", "y"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("foamagent.cli._cmd_doctor", lambda args: 0)

    assert main(["config"]) == 0

    data = settings_module.read_yaml(user_config)
    assert data["review"]["command"] == [
        "env", "HTTP_PROXY=http://proxy.example:8080", "http_proxy=http://proxy.example:8080",
        "claude", "-p",
    ]


def test_the_wizard_skips_the_proxy_question_with_no_proxy_set(user_config, monkeypatch):
    answers = iter(["native", "custom", "claude -p", "none", "y"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("foamagent.cli._cmd_doctor", lambda args: 0)

    assert main(["config"]) == 0

    data = settings_module.read_yaml(user_config)
    assert data["review"]["command"] == ["claude", "-p"]


def test_the_wizard_does_not_double_prefix_an_already_proxied_command(user_config, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    answers = iter(["native", "custom", "env HTTP_PROXY=http://proxy.example:8080 claude -p", "none", "y"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("foamagent.cli._cmd_doctor", lambda args: 0)

    assert main(["config"]) == 0

    data = settings_module.read_yaml(user_config)
    assert data["review"]["command"] == ["env", "HTTP_PROXY=http://proxy.example:8080", "claude", "-p"]


def test_the_wizard_choosing_claude_code_writes_the_whole_preset(user_config, monkeypatch):
    answers = iter(["native", "claude-code", "", "none", "y"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("foamagent.cli._cmd_doctor", lambda args: 0)

    assert main(["config"]) == 0

    from foamagent.review.settings import DEFAULT_COMMAND

    data = settings_module.read_yaml(user_config)
    assert data["review"]["command"] == DEFAULT_COMMAND
    assert data["review"]["prompt_after_command"] is False
    assert data["review"]["prompt_separator"] == "--"
    assert data["review"]["mcp_config_flag"] == "--mcp-config"
    assert data["review"]["strict_mcp_config_flag"] == "--strict-mcp-config"


def test_the_wizard_choosing_hermes_agent_writes_the_whole_preset(user_config, monkeypatch):
    answers = iter(["native", "hermes-agent", "", "none", "y"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("foamagent.cli._cmd_doctor", lambda args: 0)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/hermes" if name == "hermes" else None)

    assert main(["config"]) == 0

    data = settings_module.read_yaml(user_config)
    assert data["review"]["command"] == [
        "/usr/local/bin/hermes", "-p", "foamhermes-review", "--yolo", "-z",
    ]
    assert data["review"]["prompt_after_command"] is True
    assert data["review"]["prompt_separator"] == ""
    assert data["review"]["mcp_config_flag"] == ""
    assert data["review"]["strict_mcp_config_flag"] == ""


def test_the_wizard_falls_back_when_hermes_agent_is_chosen_without_hermes_on_path(
    user_config, monkeypatch
):
    user_config.write_text("review:\n  command: [my-existing-harness]\n", encoding="utf-8")
    answers = iter(["native", "hermes-agent", "my-existing-harness", "none", "y"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("foamagent.cli._cmd_doctor", lambda args: 0)
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert main(["config"]) == 0

    data = settings_module.read_yaml(user_config)
    assert data["review"]["command"] == ["my-existing-harness"]
    assert "prompt_after_command" not in data["review"]


def test_the_wizard_suggests_the_harness_that_matches_the_current_command(user_config, monkeypatch):
    """Pressing return on the harness question keeps whichever one is already configured."""
    user_config.write_text(
        "review:\n  command: [claude, -p, --model, claude-sonnet-5, "
        "--dangerously-skip-permissions]\n",
        encoding="utf-8",
    )
    answers = iter(["native", "", "", "none", "y"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr("foamagent.cli._cmd_doctor", lambda args: 0)

    assert main(["config"]) == 0

    from foamagent.review.settings import DEFAULT_COMMAND

    data = settings_module.read_yaml(user_config)
    assert data["review"]["command"] == DEFAULT_COMMAND


# ---------------------------------------------------------------------------
# A11: doctor reports, and changes nothing
# ---------------------------------------------------------------------------


def _stub_checks(monkeypatch, checks):
    from foamagent import diagnostics

    monkeypatch.setattr(diagnostics, "run_checks", lambda directory=None: checks)


def _check(name="OpenFOAM", ok=True, required=True):
    from foamagent.diagnostics import Check

    return Check(name=name, ok=ok, detail="detail", fix="do this", required=required)


def test_doctor_reports_every_check(monkeypatch, capsys, user_config):
    _stub_checks(monkeypatch, [_check("OpenFOAM"), _check("Reference library")])

    assert main(["doctor"]) == 0

    out = capsys.readouterr().out
    assert "OpenFOAM" in out and "Reference library" in out
    assert "Everything checked out" in out


def test_doctor_fails_on_a_required_check(monkeypatch, capsys, user_config):
    _stub_checks(monkeypatch, [_check("OpenFOAM", ok=False)])

    assert main(["doctor"]) == 1

    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "do this" in out


def test_doctor_only_warns_about_what_degrades_the_work(monkeypatch, capsys, user_config):
    """A machine with no review command still builds and runs cases."""
    _stub_checks(monkeypatch, [_check("Review command", ok=False, required=False)])

    assert main(["doctor"]) == 0

    out = capsys.readouterr().out
    assert "warn" in out
    assert "reduced" in out


def test_doctor_writes_no_settings(monkeypatch, user_config):
    _stub_checks(monkeypatch, [_check()])

    main(["doctor"])

    assert not user_config.exists()


# ---------------------------------------------------------------------------
# The checks themselves
# ---------------------------------------------------------------------------


def test_the_catalogue_check_names_the_command_that_builds_one(monkeypatch, user_config):
    from foamagent import diagnostics
    from foamagent.environment import OpenFOAMEnvironment

    monkeypatch.setattr(
        diagnostics, "check_library", diagnostics.check_library
    )
    monkeypatch.setattr(
        "foamagent.environment.environment_from_config",
        lambda config: OpenFOAMEnvironment(fork="foundation", version="10", detected=True),
    )
    monkeypatch.setattr("foamagent.indexing.resolve_library_dir", lambda environment: None)

    check = diagnostics.check_library()

    assert not check.ok
    assert check.fix == "foamagent index build"
    assert check.required


def test_a_missing_review_command_is_a_warning_not_a_failure(monkeypatch, user_config):
    from foamagent import diagnostics

    monkeypatch.setattr(diagnostics.shutil, "which", lambda _name: None)

    check = diagnostics.check_review_command()

    assert not check.ok
    assert not check.required
    assert "never checked" in check.fix


def test_a_stale_mcp_config_is_reported(tmp_path, user_config, monkeypatch):
    from foamagent import diagnostics

    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers": {"foamagent": {"command": "foamagent-mcp",'
        ' "env": {"FOAMAGENT_OPENFOAM_IMAGE": "old-image"}}}}',
        encoding="utf-8",
    )

    check = diagnostics.check_harness_configuration(tmp_path)

    assert not check.ok
    assert "old-image" in check.detail
    assert not check.required


def test_an_mcp_config_that_agrees_is_fine(tmp_path, user_config):
    from foamagent import diagnostics
    from foamagent.config import Config

    import json

    config = Config()
    (tmp_path / ".mcp.json").write_text(
        json.dumps({
            "mcpServers": {
                "foamagent": {
                    "command": "foamagent-mcp",
                    "env": {"FOAMAGENT_OPENFOAM_IMAGE": config.openfoam_image},
                }
            }
        }),
        encoding="utf-8",
    )

    assert diagnostics.check_harness_configuration(tmp_path, config).ok


def test_a_hermes_only_setup_is_not_reported_as_missing_config(tmp_path, user_config):
    """Hermes has no per-project .mcp.json -- `foamagent init hermes-agent` writes
    foamagent-hermes.yaml instead. Its presence is local evidence a Hermes setup was
    chosen on purpose, so this must not warn or point at `foamagent init claude-code`
    the way an actually-missing config does."""
    from foamagent import diagnostics

    (tmp_path / "foamagent-hermes.yaml").write_text("mcp_servers:\n  foamagent:\n    command: x\n", encoding="utf-8")

    check = diagnostics.check_harness_configuration(tmp_path)

    assert check.ok
    assert "claude-code" not in check.fix
    assert not check.required


# ---------------------------------------------------------------------------
# `doctor --review` (U-4 / A8-A12)
# ---------------------------------------------------------------------------


def test_doctor_review_flag_runs_the_extra_checks(monkeypatch, capsys, user_config):
    from foamagent import diagnostics

    _stub_checks(monkeypatch, [_check("OpenFOAM")])
    monkeypatch.setattr(
        diagnostics,
        "run_review_checks",
        lambda: [
            _check("Review: follows instructions"),
            _check("Review: sandbox usable"),
        ],
    )

    assert main(["doctor", "--review"]) == 0

    out = capsys.readouterr().out
    assert "Review: follows instructions" in out
    assert "Review: sandbox usable" in out


def test_doctor_review_flag_fails_the_command_when_a_check_fails(monkeypatch, capsys, user_config):
    from foamagent import diagnostics

    _stub_checks(monkeypatch, [_check("OpenFOAM")])
    monkeypatch.setattr(
        diagnostics, "run_review_checks", lambda: [_check("Review: follows instructions", ok=False)]
    )

    assert main(["doctor", "--review"]) == 1


def test_doctor_without_the_review_flag_does_not_start_a_harness(monkeypatch, capsys, user_config):
    """A12: doctor's ordinary behaviour is unchanged, including not paying the cost of this."""
    from foamagent import diagnostics

    _stub_checks(monkeypatch, [_check("OpenFOAM")])

    def not_called():
        raise AssertionError("run_review_checks must not run without --review")

    monkeypatch.setattr(diagnostics, "run_review_checks", not_called)

    assert main(["doctor"]) == 0


def test_run_review_checks_reports_when_no_command_is_configured(monkeypatch):
    from foamagent import diagnostics
    from foamagent.review import channel
    from foamagent.review.channel import ChannelUnavailable

    def unavailable(settings=None):
        raise ChannelUnavailable("no harness configured")

    monkeypatch.setattr(channel, "resolve_command", unavailable)

    checks = diagnostics.run_review_checks()

    assert len(checks) == 2
    assert all(not check.ok for check in checks)
    assert all("no harness configured" in check.detail for check in checks)


def test_review_instructions_check_passes_on_the_exact_reply(monkeypatch):
    from foamagent import diagnostics
    from foamagent.review import channel
    from foamagent.review.settings import ChannelSettings

    monkeypatch.setattr(
        channel, "run_audit",
        lambda prompt, **kwargs: channel.ChannelResult(ok=True, text=diagnostics.DOCTOR_TOKEN),
    )

    assert diagnostics._check_review_instructions(ChannelSettings()).ok


def test_review_instructions_check_fails_when_the_reply_is_not_exact(monkeypatch):
    from foamagent import diagnostics
    from foamagent.review import channel
    from foamagent.review.settings import ChannelSettings

    monkeypatch.setattr(
        channel, "run_audit",
        lambda prompt, **kwargs: channel.ChannelResult(
            ok=True, text=f"{diagnostics.DOCTOR_TOKEN} (Write is not permitted, so I did not create the file)"
        ),
    )

    assert not diagnostics._check_review_instructions(ChannelSettings()).ok


def test_sandbox_check_is_skipped_when_not_offered():
    from foamagent import diagnostics
    from foamagent.review.settings import ChannelSettings

    check = diagnostics._check_review_sandbox(ChannelSettings(mcp_config_flag=""))

    assert check.ok
    assert "not offered" in check.detail


def test_sandbox_check_passes_on_the_right_answer(monkeypatch):
    from foamagent import diagnostics
    from foamagent.review import channel
    from foamagent.review.settings import ChannelSettings

    monkeypatch.setattr(
        channel, "run_audit", lambda prompt, **kwargs: channel.ChannelResult(ok=True, text="2")
    )

    assert diagnostics._check_review_sandbox(ChannelSettings()).ok


def test_sandbox_check_fails_on_the_wrong_answer(monkeypatch):
    from foamagent import diagnostics
    from foamagent.review import channel
    from foamagent.review.settings import ChannelSettings

    monkeypatch.setattr(
        channel, "run_audit",
        lambda prompt, **kwargs: channel.ChannelResult(ok=True, text="I don't know"),
    )

    assert not diagnostics._check_review_sandbox(ChannelSettings()).ok


def test_the_starter_file_shows_the_real_default_command():
    """_starter_file()'s own docstring says it uses "the defaults actually in force" --
    the model and permission flags are part of review.command now, so the example must
    show the whole command rather than a separate model setting."""
    from foamagent.cli import _starter_file
    from foamagent.review.settings import DEFAULT_COMMAND

    text = _starter_file()

    assert "claude-sonnet-5" in text
    assert "--dangerously-skip-permissions" in text
    for token in DEFAULT_COMMAND:
        assert token in text


# ---------------------------------------------------------------------------
# R-9: sandbox wiring visibility, deployed-skill version
# ---------------------------------------------------------------------------


def test_sandbox_check_notes_when_docker_works_but_is_not_wired_in(monkeypatch):
    from foamagent import diagnostics
    from foamagent.review import settings as review_settings

    settings = review_settings.ChannelSettings(
        mcp_config_flag="", sandbox=review_settings.SandboxSettings(runtime="docker")
    )
    monkeypatch.setattr(review_settings, "load_settings", lambda: settings)
    monkeypatch.setattr("foamagent.review.sandbox.available", lambda s: None)

    check = diagnostics.check_sandbox()

    assert check.ok
    assert "not wired into review.command" in check.detail


def test_sandbox_check_is_quiet_when_docker_is_wired_in(monkeypatch):
    from foamagent import diagnostics
    from foamagent.review import settings as review_settings

    settings = review_settings.ChannelSettings(sandbox=review_settings.SandboxSettings(runtime="docker"))
    monkeypatch.setattr(review_settings, "load_settings", lambda: settings)
    monkeypatch.setattr("foamagent.review.sandbox.available", lambda s: None)

    check = diagnostics.check_sandbox()

    assert check.ok
    assert "not wired" not in check.detail


def test_skill_version_check_is_skipped_before_init(tmp_path, monkeypatch):
    from foamagent import diagnostics

    # check_skill_version also looks at the Hermes-agent skill path, which is not scoped to
    # `tmp_path` (Hermes has no per-project config) -- sandbox it so a real global install on
    # the machine running this test cannot make it find one anyway.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))

    assert diagnostics.check_skill_version(tmp_path) is None


def test_skill_version_check_reports_a_match(tmp_path, monkeypatch):
    from foamagent import diagnostics

    skill = tmp_path / ".claude" / "skills" / "openfoam-cfd" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: openfoam-cfd\nversion: 1.2.3\n---\nbody\n", encoding="utf-8")
    monkeypatch.setattr("importlib.metadata.version", lambda name: "1.2.3")

    check = diagnostics.check_skill_version(tmp_path)

    assert check.ok
    assert not check.required
    assert "matches this install" in check.detail


def test_skill_version_check_reports_a_mismatch(tmp_path, monkeypatch):
    from foamagent import diagnostics

    skill = tmp_path / ".claude" / "skills" / "openfoam-cfd" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: openfoam-cfd\nversion: 1.2.3\n---\nbody\n", encoding="utf-8")
    monkeypatch.setattr("importlib.metadata.version", lambda name: "9.9.9")

    check = diagnostics.check_skill_version(tmp_path)

    assert check.ok
    assert "foamagent sync" in check.detail
