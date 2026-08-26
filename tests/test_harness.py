"""Unit tests for `foamagent init`.

What matters is that the files a harness reads end up where it looks, that an existing
configuration survives, and that no credential is copied into them.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from foamagent import knowledge
from foamagent.cli import main
from foamagent.harness import (
    HARNESSES,
    SERVER_NAME,
    SKILL_NAME,
    install,
    server_command,
    skill_source,
)


@pytest.fixture(autouse=True)
def _hermes_home(tmp_path, monkeypatch):
    """Sandbox every install() call in this file: install_hermes_agent writes skills into
    $HERMES_HOME/skills, which defaults to the real ~/.hermes if left unset. It also now
    writes review.command into Foam-Agent's own settings file, which defaults to the real
    ~/.config/foamagent/config.yaml if left unset."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
    monkeypatch.setenv("FOAMAGENT_CONFIG_HOME", str(tmp_path / "foamagent_config"))
    monkeypatch.delenv("FOAMAGENT_CONFIG_FILE", raising=False)


def test_the_skill_ships_with_the_package():
    skill = skill_source() / "SKILL.md"

    assert skill.is_file()
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---")  # the frontmatter a harness reads to decide relevance
    assert "describe_environment" in text


def test_the_skills_version_matches_the_package(pytestconfig):
    """The bundled skill is tightly coupled to this package's own tool contract, so a
    deployed copy's version is meaningful only if it is kept equal to pyproject.toml's --
    bump one without the other and this fails, rather than the two drifting silently."""
    import re

    import yaml

    repo_root = Path(pytestconfig.rootpath)
    pyproject_text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject_text)
    assert match, "pyproject.toml has no [project].version"
    package_version = match.group(1)

    skill_text = (skill_source() / "SKILL.md").read_text(encoding="utf-8")
    _, frontmatter, _ = skill_text.split("---", 2)
    skill_version = yaml.safe_load(frontmatter).get("version")

    assert skill_version == package_version


def test_the_skill_gives_the_review_steps():
    text = (skill_source() / "SKILL.md").read_text(encoding="utf-8")

    assert "spec.md" in text
    assert "verbatim" in text
    assert "request_review" in text
    assert "request_report" in text
    assert "response-<n>.md" in text
    # A review that could not be run has to reach the user, not be quietly absorbed.
    assert "unavailable" in text


def test_the_skill_places_case_work_in_the_bigger_loop():
    """Building and running a case is one stage of a larger loop, not the whole job."""
    text = (skill_source() / "SKILL.md").read_text(encoding="utf-8")

    assert "set the objective" in text
    assert "does not always fit this neatly" in text


def test_the_skill_gives_task_granularity_examples():
    text = (skill_source() / "SKILL.md").read_text(encoding="utf-8")

    assert "duct-flow benchmark" in text
    assert "arXiv" in text
    assert "internal to-do list" in text


def test_the_skill_asks_before_searching_the_literature():
    """A published reference beats a guessed or invented value -- but the search itself
    costs time, so the skill asks the user before doing it rather than doing it silently."""
    text = (skill_source() / "SKILL.md").read_text(encoding="utf-8")

    assert "Check the literature before guessing" in text
    assert "do you want me to?" in text


@pytest.mark.parametrize("word", ["reviewer", "judge", "subagent", "sub-agent", "adversarial"])
def test_the_skill_describes_tools_rather_than_personalities(word):
    """What the review is made of is not the harness's business.

    Naming a reviewer invites writing for one -- answering the persona rather than the
    finding. The skill therefore says what the tools return and nothing about who returns
    it. Documentation for people (README) is free to explain the whole arrangement. The
    knowledge files are shipped with the same skill and read by the same agent, so the rule
    applies to them too.
    """
    paths = [path for path in sorted(skill_source().rglob("*")) if path.is_file()]
    paths += sorted(knowledge.bundled_dir().glob("*.md"))
    for path in paths:
        assert word not in path.read_text(encoding="utf-8").lower(), path


def test_the_skill_points_at_the_knowledge_directory_instead_of_repeating_it():
    """The OpenFOAM know-how moved to `foamagent.knowledge`; SKILL.md only says where."""
    text = (skill_source() / "SKILL.md").read_text(encoding="utf-8")

    for gone in ("sigFpe", "Guardrails", "Classify before you write"):
        assert gone not in text
    assert "knowledge" in text
    assert "describe_environment" in text


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


def _fake_paraview_checkout(tmp_path: Path) -> Path:
    directory = tmp_path / "paraview_mcp"
    (directory / "skills" / "paraview").mkdir(parents=True)
    (directory / "skills" / "paraview" / "SKILL.md").write_text("---\nname: paraview\n---\n", encoding="utf-8")
    return directory


def test_paraview_is_not_configured_when_paraview_dir_is_unset(tmp_path):
    result = install("claude-code", tmp_path)

    config = json.loads((tmp_path / ".mcp.json").read_text())
    assert "paraview" not in config["mcpServers"]
    assert not (tmp_path / ".claude" / "skills" / "paraview").exists()
    assert any("paraview.dir is not set" in note for note in result.notes)


def test_paraview_dir_adds_the_server_and_skill_for_claude_code(tmp_path, monkeypatch):
    checkout = _fake_paraview_checkout(tmp_path)
    monkeypatch.setenv("FOAMAGENT_PARAVIEW_MCP_DIR", str(checkout))

    install("claude-code", tmp_path / "project")

    config = json.loads((tmp_path / "project" / ".mcp.json").read_text())
    server = config["mcpServers"]["paraview"]
    assert server["command"] == "uv"
    assert server["args"] == ["run", "--directory", str(checkout), "paraview-mcp"]
    assert "foamagent" in config["mcpServers"]  # the worker's own server is still there
    assert (tmp_path / "project" / ".claude" / "skills" / "paraview" / "SKILL.md").is_file()


def test_paraview_dir_also_wires_into_hermes_agent(tmp_path, monkeypatch):
    checkout = _fake_paraview_checkout(tmp_path)
    monkeypatch.setenv("FOAMAGENT_PARAVIEW_MCP_DIR", str(checkout))

    install("hermes-agent", tmp_path / "project")

    yaml_text = (tmp_path / "project" / "foamagent-hermes.yaml").read_text()
    assert "paraview:" in yaml_text
    hermes_home = Path(os.environ["HERMES_HOME"])
    assert (hermes_home / "skills" / "cfd" / "paraview" / "SKILL.md").is_file()


def test_a_paraview_dir_that_does_not_exist_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setenv("FOAMAGENT_PARAVIEW_MCP_DIR", str(tmp_path / "nowhere"))

    with pytest.raises(ValueError):
        install("claude-code", tmp_path / "project")


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


def test_hermes_agent_yaml_raises_the_mcp_client_timeout_to_match_review(tmp_path):
    """Regression: Hermes's own per-tool-call MCP client timeout defaults to 300s
    (tools/mcp_tool.py's _DEFAULT_TOOL_TIMEOUT), shorter than review.timeout_seconds'
    own 1800s default -- a real review that legitimately took longer than 300s but well
    under 1800s was cut off client-side ("MCP TimeoutError") before the server-side
    subprocess, still well within its own budget, ever finished."""
    install("hermes-agent", tmp_path)

    yaml_text = (tmp_path / "foamagent-hermes.yaml").read_text()
    assert "timeout: 1800" in yaml_text


def test_hermes_agent_install_alone_points_review_at_it(tmp_path):
    """`foamagent init hermes-agent` must be enough by itself -- no separate
    `--with-review` step. Regression for the isolated-profile setup this replaced."""
    from foamagent import settings as settings_module
    from foamagent.review.settings import load_settings

    result = install("hermes-agent", tmp_path)

    assert settings_module.load().resolve("review.command", default=None).value == ["hermes", "-z"]
    assert load_settings().argv("check this") == ["hermes", "-z", "check this"]
    assert any("review.command set" in note for note in result.notes)


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
# Knowledge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("harness", sorted(HARNESSES))
def test_install_seeds_the_knowledge_directory(tmp_path, harness):
    install(harness, tmp_path / harness)

    bundled_names = {path.name for path in knowledge.bundled_dir().glob("*.md")}
    seeded_names = {path.name for path in knowledge.user_dir().glob("*.md")}
    assert seeded_names == bundled_names
    for name in bundled_names:
        assert (knowledge.user_dir() / name).read_text(encoding="utf-8") == (
            knowledge.bundled_dir() / name
        ).read_text(encoding="utf-8")


def test_reinstall_keeps_edits_and_user_added_knowledge_files(tmp_path):
    install("claude-code", tmp_path)
    edited = next(iter(knowledge.user_dir().glob("*.md")))
    edited.write_text("# my own words\n", encoding="utf-8")
    extra = knowledge.user_dir() / "my-notes.md"
    extra.write_text("# extra notes\n", encoding="utf-8")

    install("claude-code", tmp_path)

    assert edited.read_text(encoding="utf-8") == "# my own words\n"
    assert extra.is_file()


def test_any_cli_command_seeds_the_knowledge_directory():
    """`~/.config/foamagent/knowledge/` is the canonical, editable copy now -- it should be
    populated the first time `foamagent` runs anything, not only after `init`."""
    assert not knowledge.user_dir().exists()

    assert main(["config", "show"]) == 0

    seeded = {path.name for path in knowledge.user_dir().glob("*.md")}
    assert seeded == {path.name for path in knowledge.bundled_dir().glob("*.md")}


# ---------------------------------------------------------------------------
# Through the command line
# ---------------------------------------------------------------------------


def test_init_from_the_cli(tmp_path, capsys):
    assert main(["init", "claude-code", "--directory", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "Configured Claude Code" in out
    assert "foamagent index build" in out
    assert (tmp_path / ".mcp.json").is_file()


def test_init_without_a_harness_needs_a_terminal(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert main(["init", "--directory", str(tmp_path)]) == 1

    out = capsys.readouterr().out
    assert "terminal" in out
    assert "foamagent init claude-code" in out
    assert not (tmp_path / ".mcp.json").exists()


def test_init_asks_which_harness_over_a_tty(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "hermes-agent")

    assert main(["init", "--directory", str(tmp_path)]) == 0

    assert (tmp_path / "foamagent-hermes.yaml").is_file()


def test_init_runs_git_init_when_not_already_a_repository(tmp_path, capsys):
    assert main(["init", "claude-code", "--directory", str(tmp_path)]) == 0

    assert (tmp_path / ".git").is_dir()
    assert "Initialized a git repository" in capsys.readouterr().out


def test_init_does_not_disturb_an_existing_repository(tmp_path, capsys):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    marker = (tmp_path / ".git").stat().st_mtime_ns

    assert main(["init", "claude-code", "--directory", str(tmp_path)]) == 0

    assert (tmp_path / ".git").stat().st_mtime_ns == marker
    assert "Initialized a git repository" not in capsys.readouterr().out
