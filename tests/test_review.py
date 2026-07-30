"""Unit tests for the independent review: settings, argv, rounds and documents.

No model is started anywhere here. The subprocess is stubbed, so what is under test is the
command line that would have been run, the enforcement of the round limits, and what lands
in the case directory -- which is where the acceptance conditions A3, A4, A7 and A10 live.
"""

from __future__ import annotations

import asyncio

import pytest

from foamagent.case_state import load_case_state
from foamagent.mcp import audit
from foamagent.review import (
    REPORT,
    RESULT_REVIEW,
    ROUND_LIMIT,
    SPEC_REVIEW,
    ChannelSettings,
    ChannelUnavailable,
    build_prompt,
    channel,
    documents,
    load_settings,
    resolve_command,
    settings as settings_module,
    templates,
)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point the settings and template lookups at an empty directory of our own."""
    home = tmp_path / "config"
    home.mkdir()
    monkeypatch.setenv("FOAMAGENT_CONFIG_HOME", str(home))
    monkeypatch.delenv("FOAMAGENT_CONFIG_FILE", raising=False)
    monkeypatch.delenv("FOAMAGENT_TEMPLATES_DIR", raising=False)
    return home


@pytest.fixture
def case_dir(tmp_path):
    case = tmp_path / "cavity"
    (case / "system").mkdir(parents=True)
    (case / "spec.md").write_text(
        "# Specification\n\n## The request, verbatim\n\n> Lid-driven cavity at Re=1000\n",
        encoding="utf-8",
    )
    return case


class FakeContext:
    def __init__(self):
        self.messages = {"info": [], "warning": []}

    async def info(self, message):
        self.messages["info"].append(message)

    async def warning(self, message):
        self.messages["warning"].append(message)


def write_config(home, text):
    (home / "config.yaml").write_text(text, encoding="utf-8")


def stub_channel(monkeypatch, text="findings", ok=True, detail=""):
    """Replace the subprocess with a recorder, and make the command look installed."""
    seen = {}

    def fake_run(prompt, *, cwd=None, settings=None):
        seen["prompt"] = prompt
        seen["cwd"] = cwd
        return channel.ChannelResult(ok=ok, text=text, detail=detail)

    monkeypatch.setattr(audit, "run_audit", fake_run)
    monkeypatch.setattr(audit, "resolve_command", lambda: ["claude", "-p"])
    return seen


# ---------------------------------------------------------------------------
# Settings and argv (A3)
# ---------------------------------------------------------------------------


def test_the_defaults_drive_claude_code():
    given = load_settings()

    assert given.command == ["claude", "-p"]
    assert "Read" in given.allowed_tools
    assert given.timeout_seconds > 0


def test_the_yaml_allowlist_reaches_the_command_line(isolated_config):
    write_config(
        isolated_config,
        "review:\n"
        "  command: [claude, -p]\n"
        "  allowed_tools: [Read, Glob, WebSearch]\n"
        "  timeout_seconds: 120\n",
    )

    given = load_settings()
    argv = given.argv("do the review")

    assert given.timeout_seconds == 120
    assert "--allowed-tools" in argv
    assert argv[argv.index("--allowed-tools") + 1] == "Read,Glob,WebSearch"
    assert argv[-1] == "do the review"


def test_the_prompt_is_kept_out_of_the_tool_list():
    """`--allowed-tools` takes a list, so the prompt has to be fenced off from it.

    Without the separator the prompt's own words are read as tool names, and the review
    starts with no task -- which is how this was found.
    """
    argv = load_settings().argv("check the specification")

    assert argv[-2] == "--"
    assert argv[-1] == "check the specification"


def test_the_separator_can_be_dropped(isolated_config):
    write_config(isolated_config, "review:\n  prompt_separator: ''\n")

    assert "--" not in load_settings().argv("x")


def test_the_command_itself_can_be_replaced(isolated_config):
    write_config(isolated_config, "review:\n  command: [my-harness, run, --quiet]\n")

    assert load_settings().argv("x")[:3] == ["my-harness", "run", "--quiet"]


def test_the_allowlist_flag_can_be_spelled_differently(isolated_config):
    write_config(
        isolated_config,
        "review:\n"
        "  allow_tools_flag: --tools\n"
        "  allow_tools_separator: ' '\n"
        "  allowed_tools: [Read, Grep]\n",
    )

    argv = load_settings().argv("x")

    assert argv[argv.index("--tools") + 1] == "Read Grep"


@pytest.mark.parametrize("tool", ["Bash", "write", "Edit", "NotebookEdit", "Bash(ls:*)"])
def test_a_tool_that_could_change_the_case_is_refused(isolated_config, tool):
    """A reviewer that can rewrite the case is not a reviewer."""
    write_config(isolated_config, f"review:\n  allowed_tools: [Read, {tool}]\n")

    given = load_settings()

    assert given.allowed_tools == ["Read"]
    assert tool not in " ".join(given.argv("x"))


def test_the_default_allowlist_is_read_only():
    for tool in load_settings().allowed_tools:
        assert tool.lower() not in settings_module.FORBIDDEN_TOOLS


def test_a_broken_settings_file_falls_back_to_the_defaults(isolated_config):
    write_config(isolated_config, "review: [this is not a mapping]\n")

    assert load_settings().command == ["claude", "-p"]


def test_a_missing_command_is_reported_rather_than_run(monkeypatch):
    monkeypatch.setattr(channel.shutil, "which", lambda name: None)

    with pytest.raises(ChannelUnavailable, match="not on PATH"):
        resolve_command(ChannelSettings(command=["no-such-harness"]))


# ---------------------------------------------------------------------------
# The prompt (A3): the task text and the case path, and nothing else
# ---------------------------------------------------------------------------


def test_the_prompt_is_the_task_text_and_the_case_path(case_dir):
    prompt = build_prompt(SPEC_REVIEW, str(case_dir))

    assert prompt.startswith(templates.load_template(SPEC_REVIEW).rstrip()[:40])
    assert prompt.rstrip().endswith(f"Case directory: {case_dir}")


def test_every_shipped_template_is_present():
    for name in templates.TEMPLATES:
        assert (templates.packaged_dir() / name).is_file()


def test_a_users_own_template_wins(isolated_config, case_dir):
    """A10: the file under the config directory replaces the shipped one."""
    own = isolated_config / "templates"
    own.mkdir()
    (own / SPEC_REVIEW).write_text("Check the specification differently.\n", encoding="utf-8")

    prompt = build_prompt(SPEC_REVIEW, str(case_dir))

    assert prompt.startswith("Check the specification differently.")
    assert "Correspondence" not in prompt  # i.e. not the shipped checklist


def test_the_templates_directory_can_be_moved(tmp_path, monkeypatch, case_dir):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / REPORT).write_text("Write the report like this.\n", encoding="utf-8")
    monkeypatch.setenv("FOAMAGENT_TEMPLATES_DIR", str(elsewhere))

    assert build_prompt(REPORT, str(case_dir)).startswith("Write the report like this.")


# ---------------------------------------------------------------------------
# request_review
# ---------------------------------------------------------------------------


def review(case_dir, stage, ctx=None):
    return asyncio.run(
        audit.request_review(audit.ReviewRequest(case_dir=str(case_dir), stage=stage), ctx)
    )


def test_a_spec_review_writes_its_findings_into_the_case(case_dir, monkeypatch):
    seen = stub_channel(monkeypatch, text="The Reynolds number does not match.")

    response = review(case_dir, "spec")

    assert response.available
    assert response.round == 1
    assert "Reynolds" in response.review
    assert (case_dir / "review-1.md").is_file()
    assert "The Reynolds number does not match." in (case_dir / "review-1.md").read_text()
    assert response.respond_to.endswith("response-1.md")
    assert str(case_dir) in seen["prompt"]


def test_the_review_starts_in_the_case_directory(case_dir, monkeypatch):
    """Started in the repository, a review reads the repository instead of the case."""
    seen = stub_channel(monkeypatch)

    review(case_dir, "spec")

    assert seen["cwd"] == str(case_dir)


def test_the_spec_and_result_stages_use_different_tasks(case_dir, monkeypatch):
    seen = stub_channel(monkeypatch)
    monkeypatch.setattr(audit, "build_prompt", lambda name, path: f"TEMPLATE={name}")

    review(case_dir, "spec")
    assert seen["prompt"] == f"TEMPLATE={SPEC_REVIEW}"

    (case_dir / "response-1.md").write_text("fixed", encoding="utf-8")
    review(case_dir, "result")
    assert seen["prompt"] == f"TEMPLATE={RESULT_REVIEW}"


def test_an_unknown_stage_is_refused(case_dir):
    with pytest.raises(ValueError, match="stage"):
        review(case_dir, "whenever")


def test_a_case_without_a_specification_cannot_be_reviewed(tmp_path):
    empty = tmp_path / "nospec"
    empty.mkdir()

    with pytest.raises(ValueError, match="spec.md"):
        review(empty, "spec")


def test_findings_must_be_answered_before_more_are_asked_for(case_dir, monkeypatch):
    stub_channel(monkeypatch)
    review(case_dir, "spec")

    with pytest.raises(ValueError, match="response-1.md"):
        review(case_dir, "spec")


# ---------------------------------------------------------------------------
# Round limits (A4)
# ---------------------------------------------------------------------------


def _answer(case_dir, number):
    (case_dir / f"response-{number}.md").write_text("answered", encoding="utf-8")


def test_a_stage_is_closed_after_two_rounds(case_dir, monkeypatch):
    stub_channel(monkeypatch)

    for round_number in range(1, ROUND_LIMIT + 1):
        response = review(case_dir, "spec")
        assert response.available
        _answer(case_dir, response.round)

    calls = []
    monkeypatch.setattr(audit, "run_audit", lambda prompt, **kw: calls.append(prompt))

    closed = review(case_dir, "spec")

    assert calls == []  # no model was started
    assert closed.rounds_left == 0
    assert "closed" in closed.review.lower()
    assert not (case_dir / f"review-{ROUND_LIMIT + 1}.md").exists()


def test_each_stage_has_its_own_allowance(case_dir, monkeypatch):
    stub_channel(monkeypatch)

    for _ in range(ROUND_LIMIT):
        response = review(case_dir, "spec")
        _answer(case_dir, response.round)

    result = review(case_dir, "result")

    assert result.available
    assert result.rounds_left == ROUND_LIMIT - 1


def test_the_rounds_are_counted_in_the_case_state_not_the_files(case_dir, monkeypatch):
    """Deleting a review document must not buy another round."""
    stub_channel(monkeypatch)
    response = review(case_dir, "spec")
    _answer(case_dir, response.round)
    (case_dir / "review-1.md").unlink()

    assert load_case_state(case_dir).spec_review_rounds == 1
    assert documents.rounds(case_dir).remaining("spec") == ROUND_LIMIT - 1


# ---------------------------------------------------------------------------
# No channel (A7)
# ---------------------------------------------------------------------------


def test_no_channel_returns_a_document_saying_so(case_dir, monkeypatch):
    def unavailable():
        raise ChannelUnavailable("claude is not on PATH")

    monkeypatch.setattr(audit, "resolve_command", unavailable)
    monkeypatch.setattr(
        audit, "run_audit", lambda *a, **k: pytest.fail("started a review with no channel")
    )
    ctx = FakeContext()

    response = review(case_dir, "spec", ctx)

    assert not response.available
    assert "not on PATH" in response.review
    assert "unreviewed" in response.review
    assert not (case_dir / "review-1.md").exists()  # nothing was recorded as a review
    assert ctx.messages["warning"]


def test_a_review_that_fails_costs_no_round(case_dir, monkeypatch):
    stub_channel(monkeypatch, ok=False, text="", detail="the harness exited with code 1")

    response = review(case_dir, "spec")

    assert not response.available
    assert "exited with code 1" in response.review
    assert documents.rounds(case_dir).spec == 0


# ---------------------------------------------------------------------------
# request_report
# ---------------------------------------------------------------------------


def report(case_dir, ctx=None):
    return asyncio.run(audit.request_report(audit.ReportRequest(case_dir=str(case_dir)), ctx))


def test_the_report_is_written_into_the_case(case_dir, monkeypatch):
    seen = stub_channel(monkeypatch, text="# Report\n\nIt converged.")
    monkeypatch.setattr(audit, "build_prompt", lambda name, path: f"TEMPLATE={name}")

    response = report(case_dir)

    assert response.available
    assert (case_dir / "report.md").read_text().startswith("# Report")
    assert seen["prompt"] == f"TEMPLATE={REPORT}"


def test_a_report_without_a_result_review_says_so(case_dir, monkeypatch):
    stub_channel(monkeypatch, text="# Report")

    response = report(case_dir)

    assert any("No result review" in w for w in response.warnings)


def test_a_report_names_the_findings_nobody_answered(case_dir, monkeypatch):
    stub_channel(monkeypatch, text="# Report")
    review(case_dir, "spec")

    response = report(case_dir)

    assert any("response-1.md" in w for w in response.warnings)


def test_no_channel_yields_a_report_document_saying_so(case_dir, monkeypatch):
    def unavailable():
        raise ChannelUnavailable("no harness configured")

    monkeypatch.setattr(audit, "resolve_command", unavailable)

    response = report(case_dir)

    assert not response.available
    assert "no harness configured" in response.report
    assert not (case_dir / "report.md").exists()
