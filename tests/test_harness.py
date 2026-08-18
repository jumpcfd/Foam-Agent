"""Unit tests for `foamagent install`.

What matters is that the files a harness reads end up where it looks, that an existing
configuration survives, and that no credential is copied into them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from foamagent.cli import main
from foamagent import harness as harness_module
from foamagent.harness import (
    HARNESSES,
    HERMES_REVIEW_PROFILE,
    SERVER_NAME,
    SKILL_NAME,
    HermesNotFound,
    install,
    server_command,
    setup_hermes_review,
    skill_source,
)


@pytest.fixture(autouse=True)
def _hermes_home(tmp_path, monkeypatch):
    """Sandbox every install() call in this file: install_hermes_agent writes skills into
    $HERMES_HOME/skills, which defaults to the real ~/.hermes if left unset."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))


def test_the_skill_ships_with_the_package():
    skill = skill_source() / "SKILL.md"

    assert skill.is_file()
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---")  # the frontmatter a harness reads to decide relevance
    assert "describe_environment" in text


def test_the_skill_gives_the_review_steps():
    text = (skill_source() / "SKILL.md").read_text(encoding="utf-8")

    assert "spec.md" in text
    assert "verbatim" in text
    assert "request_review" in text
    assert "request_report" in text
    assert "response-<n>.md" in text
    # A review that could not be run has to reach the user, not be quietly absorbed.
    assert "unavailable" in text


@pytest.mark.parametrize("word", ["reviewer", "judge", "subagent", "sub-agent", "adversarial"])
def test_the_skill_describes_tools_rather_than_personalities(word):
    """What the review is made of is not the harness's business.

    Naming a reviewer invites writing for one -- answering the persona rather than the
    finding. The skill therefore says what the tools return and nothing about who returns
    it. Documentation for people (README) is free to explain the whole arrangement.
    """
    for path in sorted(skill_source().rglob("*")):
        if path.is_file():
            assert word not in path.read_text(encoding="utf-8").lower(), path


def test_no_template_is_shipped_to_the_harness():
    """The prompts the review runs on are not part of what the harness is handed."""
    names = {path.name for path in skill_source().rglob("*") if path.is_file()}

    assert names == {"SKILL.md"}


def test_the_server_command_is_runnable():
    command = server_command()

    assert command["command"]
    assert "--transport" in command["args"]
    assert "stdio" in command["args"]


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------


def test_claude_code_gets_a_server_entry_and_a_skill(tmp_path):
    result = install("claude-code", tmp_path)

    config = json.loads((tmp_path / ".mcp.json").read_text())
    assert SERVER_NAME in config["mcpServers"]
    assert (tmp_path / ".claude" / "skills" / "openfoam-cfd" / "SKILL.md").is_file()
    assert result.written


def test_an_existing_mcp_config_keeps_its_other_servers(tmp_path):
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"something-else": {"command": "keep-me"}}}), encoding="utf-8"
    )

    install("claude-code", tmp_path)

    servers = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]
    assert servers["something-else"]["command"] == "keep-me"
    assert SERVER_NAME in servers


def test_unparseable_json_is_replaced_rather_than_crashing(tmp_path):
    (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")

    install("claude-code", tmp_path)

    assert SERVER_NAME in json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]


def test_the_openfoam_runtime_travels_with_the_server(tmp_path, monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", "docker")
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_IMAGE", "foam-bench:latest")

    install("claude-code", tmp_path)

    env = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"][SERVER_NAME]["env"]
    assert env["FOAMAGENT_OPENFOAM_RUNTIME"] == "docker"
    assert env["FOAMAGENT_OPENFOAM_IMAGE"] == "foam-bench:latest"


def test_no_api_key_is_written_into_the_configuration(tmp_path, monkeypatch):
    # The whole point of host_delegate is that no key is involved; copying one into a file
    # the user commits would undo that quietly.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-appear")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-appear")

    install("claude-code", tmp_path)

    assert "should-not-appear" not in (tmp_path / ".mcp.json").read_text()


# ---------------------------------------------------------------------------
# Other harnesses
# ---------------------------------------------------------------------------


def test_hermes_agent_gets_yaml_and_installs_skill_into_hermes_home(tmp_path):
    result = install("hermes-agent", tmp_path)

    yaml_text = (tmp_path / "foamagent-hermes.yaml").read_text()
    assert "mcp_servers:" in yaml_text
    assert f"{SERVER_NAME}:" in yaml_text
    hermes_home = Path(os.environ["HERMES_HOME"])
    assert (hermes_home / "skills" / "cfd" / SKILL_NAME / "SKILL.md").is_file()
    assert not (tmp_path / ".foamagent").exists()
    assert any("merge" in note.lower() for note in result.notes)


@pytest.mark.parametrize("harness", sorted(HARNESSES))
def test_every_harness_writes_something_and_says_what(tmp_path, harness):
    result = install(harness, tmp_path / harness)

    assert result.written
    assert all(path.is_file() for path in result.written)
    assert result.notes


def test_an_unknown_harness_lists_the_known_ones(tmp_path):
    with pytest.raises(ValueError) as excinfo:
        install("emacs", tmp_path)

    assert "claude-code" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Through the command line
# ---------------------------------------------------------------------------


def test_install_from_the_cli(tmp_path, capsys):
    assert main(["install", "claude-code", "--directory", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "Configured Claude Code" in out
    assert "foamagent index build" in out
    assert (tmp_path / ".mcp.json").is_file()


# ---------------------------------------------------------------------------
# Setting up Hermes as the review command (--with-review)
# ---------------------------------------------------------------------------


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeHermes:
    """Answers each `hermes` invocation setup_hermes_review makes, the way a real Hermes
    CLI would for a profile that either already exists or does not yet -- see
    src/foamagent/harness/__init__.py's own docstring for the real sequence this mirrors."""

    def __init__(self, *, profile_exists=False, default_model="deepseek/x", default_provider="openrouter"):
        self.profile_exists = profile_exists
        self.default_model = default_model
        self.default_provider = default_provider
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        args = argv[1:]
        if args[:1] == ["-p"]:
            args = args[2:]

        if args == ["profile", "show", HERMES_REVIEW_PROFILE]:
            return _Completed(0 if self.profile_exists else 1)
        if args[:2] == ["profile", "create"]:
            self.profile_exists = True
            return _Completed(0)
        if args[:2] == ["config", "get"]:
            value = self.default_model if args[2] == "model.default" else self.default_provider
            return _Completed(0, stdout=value)
        return _Completed(0)


@pytest.fixture
def fake_hermes_binary(monkeypatch):
    """setup_hermes_review shells out to `hermes` itself, which this test machine may or
    may not have -- make it discoverable so HermesNotFound is not raised by accident."""
    monkeypatch.setattr(harness_module.shutil, "which", lambda name: f"/fake/bin/{name}")


@pytest.fixture
def isolated_review_config(tmp_path, monkeypatch):
    """setup_hermes_review writes review.harness into Foam-Agent's own settings -- keep
    that off this machine's real ~/.config/foamagent/config.yaml."""
    home = tmp_path / "config"
    home.mkdir()
    monkeypatch.setenv("FOAMAGENT_CONFIG_HOME", str(home))
    monkeypatch.delenv("FOAMAGENT_CONFIG_FILE", raising=False)
    # setup_hermes_review also looks at this -- keep tests deterministic regardless of
    # whether the machine running them happens to have a real key exported.
    monkeypatch.delenv(harness_module.REVIEW_API_KEY_ENV, raising=False)
    return home


def test_setup_hermes_review_creates_a_new_profile_when_none_exists(
    monkeypatch, fake_hermes_binary, isolated_review_config, tmp_path
):
    fake = _FakeHermes(profile_exists=False)
    monkeypatch.setattr(harness_module.subprocess, "run", fake)

    setup_hermes_review(tmp_path)

    commands = [call[1:] for call in fake.calls]
    assert ["profile", "create", HERMES_REVIEW_PROFILE, "--no-skills"] in commands


def test_setup_hermes_review_never_touches_terminal_backend(
    monkeypatch, fake_hermes_binary, isolated_review_config, tmp_path
):
    """Regression: two earlier versions of this function wrote terminal.backend -- first to
    "docker" (which rerouted `file`'s reads through a container mount that was unreliable on
    WSL2), then to "host" as the "fix". Writing terminal.backend at all -- confirmed by
    isolating it on a series of throwaway profiles, changing exactly one setting at a time
    -- makes Hermes stop exposing the `file` toolset to the model, even when the value is
    "host", Hermes's own default. `hermes tools disable ... terminal ...` is the isolation
    that actually holds; this function must never write terminal.backend, to any value."""
    fake = _FakeHermes(profile_exists=False)
    monkeypatch.setattr(harness_module.subprocess, "run", fake)

    setup_hermes_review(tmp_path)

    commands = [call[1:] for call in fake.calls]
    assert not any("terminal.backend" in call for call in commands)
    assert not any(c[:3] == ["-p", HERMES_REVIEW_PROFILE, "config"] and "terminal" in " ".join(c) for c in commands)


def test_setup_hermes_review_reuses_an_existing_profile(
    monkeypatch, fake_hermes_binary, isolated_review_config, tmp_path
):
    """Re-running the setup on an already-configured profile must not fail or double up --
    `foamagent install hermes-agent --with-review` twice should just work."""
    fake = _FakeHermes(profile_exists=True)
    monkeypatch.setattr(harness_module.subprocess, "run", fake)

    setup_hermes_review(tmp_path)

    commands = [call[1:] for call in fake.calls]
    assert not any(c[:2] == ["profile", "create"] for c in commands)


def test_setup_hermes_review_copies_the_default_model(
    monkeypatch, fake_hermes_binary, isolated_review_config, tmp_path
):
    """There is no universal default model the way claude-sonnet-5 is for Claude Code, so
    the isolated review profile inherits whatever the user's own default Hermes profile is
    already set up with, rather than being left unset."""
    fake = _FakeHermes(default_model="anthropic/claude-x", default_provider="openrouter")
    monkeypatch.setattr(harness_module.subprocess, "run", fake)

    setup_hermes_review(tmp_path)

    commands = [call[1:] for call in fake.calls]
    assert ["-p", HERMES_REVIEW_PROFILE, "config", "set", "model.default", "anthropic/claude-x"] in commands
    assert ["-p", HERMES_REVIEW_PROFILE, "config", "set", "model.provider", "openrouter"] in commands


def test_setup_hermes_review_skips_the_model_when_none_is_configured(
    monkeypatch, fake_hermes_binary, isolated_review_config, tmp_path
):
    fake = _FakeHermes(default_model="", default_provider="")
    monkeypatch.setattr(harness_module.subprocess, "run", fake)

    result = setup_hermes_review(tmp_path)

    assert not any("set" in call and "model.default" in call for call in fake.calls)
    assert any("no model configured" in note.lower() for note in result.notes)


def test_setup_hermes_review_points_review_harness_at_hermes_agent(
    monkeypatch, fake_hermes_binary, isolated_review_config, tmp_path
):
    from foamagent import settings as settings_module

    monkeypatch.setattr(harness_module.subprocess, "run", _FakeHermes())

    setup_hermes_review(tmp_path)

    assert settings_module.load().resolve("review.harness", default="claude-code").value == "hermes-agent"


def test_setup_hermes_review_without_hermes_on_path_raises(monkeypatch, isolated_review_config, tmp_path):
    monkeypatch.setattr(harness_module.shutil, "which", lambda name: None)

    with pytest.raises(HermesNotFound):
        setup_hermes_review(tmp_path)


def test_with_review_only_applies_to_hermes_agent(tmp_path, capsys):
    assert main(["install", "claude-code", "--with-review", "--directory", str(tmp_path)]) == 1

    assert "only applies to hermes-agent" in capsys.readouterr().out


def test_install_with_review_from_the_cli(
    monkeypatch, fake_hermes_binary, isolated_review_config, tmp_path, capsys
):
    monkeypatch.setattr(harness_module.subprocess, "run", _FakeHermes())

    assert main(["install", "hermes-agent", "--with-review", "--directory", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "Configured Hermes Agent (review)" in out
    assert "review.harness set to hermes-agent" in out


# ---------------------------------------------------------------------------
# The review's API key (see harness/__init__.py's _inject_review_api_key)
# ---------------------------------------------------------------------------


def test_with_review_adds_the_api_key_to_the_workers_mcp_yaml(
    monkeypatch, fake_hermes_binary, isolated_review_config, tmp_path, capsys
):
    """Confirmed on a real run: without this, the review fails every time with Hermes's own
    "No LLM provider configured" -- Hermes hands the MCP server subprocess (and everything
    it spawns, including the review) a stripped environment that never includes this key."""
    monkeypatch.setattr(harness_module.subprocess, "run", _FakeHermes())
    monkeypatch.setenv(harness_module.REVIEW_API_KEY_ENV, "sk-or-test-key")

    assert main(["install", "hermes-agent", "--with-review", "--directory", str(tmp_path)]) == 0

    yaml_text = (tmp_path / "foamagent-hermes.yaml").read_text()
    assert 'OPENROUTER_API_KEY: "sk-or-test-key"' in yaml_text
    assert "env:" in yaml_text
    assert "now holds a real secret" in capsys.readouterr().out


def test_with_review_warns_when_no_api_key_is_set(
    monkeypatch, fake_hermes_binary, isolated_review_config, tmp_path, capsys
):
    monkeypatch.setattr(harness_module.subprocess, "run", _FakeHermes())

    assert main(["install", "hermes-agent", "--with-review", "--directory", str(tmp_path)]) == 0

    yaml_text = (tmp_path / "foamagent-hermes.yaml").read_text()
    assert "OPENROUTER_API_KEY" not in yaml_text
    assert "is not set in this environment" in capsys.readouterr().out


def test_with_review_does_not_duplicate_an_existing_key(
    monkeypatch, fake_hermes_binary, isolated_review_config, tmp_path
):
    """Idempotency: running --with-review twice must not write the key line twice."""
    monkeypatch.setattr(harness_module.subprocess, "run", _FakeHermes())
    monkeypatch.setenv(harness_module.REVIEW_API_KEY_ENV, "sk-or-test-key")

    main(["install", "hermes-agent", "--with-review", "--directory", str(tmp_path)])
    main(["install", "hermes-agent", "--with-review", "--directory", str(tmp_path)])

    yaml_text = (tmp_path / "foamagent-hermes.yaml").read_text()
    assert yaml_text.count("OPENROUTER_API_KEY") == 1


def test_a_plain_install_never_gets_the_api_key(tmp_path, monkeypatch):
    """Only --with-review touches this file with a secret -- a plain `foamagent install
    hermes-agent` (no review) must stay exactly as free of API keys as install_hermes_agent
    always was."""
    monkeypatch.setenv(harness_module.REVIEW_API_KEY_ENV, "sk-or-test-key")

    install("hermes-agent", tmp_path)

    assert "OPENROUTER_API_KEY" not in (tmp_path / "foamagent-hermes.yaml").read_text()
