"""Unit tests for the independent review: settings, argv, rounds and documents.

No model is started anywhere here. The subprocess is stubbed, so what is under test is the
command line that would have been run, the enforcement of the round limits, and what lands
in the case directory -- which is where the acceptance conditions A3, A4, A7 and A10 live.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from foamagent.case_state import load_case_state
from foamagent.mcp import audit
from foamagent.review import channel, documents, settings as settings_module, templates
from foamagent.review.channel import ChannelUnavailable, resolve_command
from foamagent.review.documents import ROUND_LIMIT
from foamagent.review.settings import ChannelSettings, load_settings
from foamagent.review.templates import REPORT, RESULT_REVIEW, SPEC_REVIEW, build_prompt


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
        self.progress = []

    async def info(self, message):
        self.messages["info"].append(message)

    async def warning(self, message):
        self.messages["warning"].append(message)

    async def report_progress(self, progress, total=None):
        self.progress.append((progress, total))


def write_config(home, text):
    (home / "config.yaml").write_text(text, encoding="utf-8")


def stub_channel(monkeypatch, text="findings", ok=True, detail=""):
    """Replace the subprocess with a recorder, and make the command look installed."""
    seen = {}

    def fake_run(prompt, *, cwd=None, work_dir=None, settings=None, role=None):
        seen["prompt"] = prompt
        seen["cwd"] = cwd
        seen["work_dir"] = work_dir
        seen["role"] = role
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


def test_the_review_names_its_model(isolated_config):
    """Which model reviewed the case is a setting, not the harness's private default."""
    argv = load_settings().argv("x")

    assert argv[argv.index("--model") + 1] == settings_module.DEFAULT_MODEL
    assert settings_module.DEFAULT_MODEL == "claude-sonnet-5"


def test_the_model_can_be_chosen(isolated_config):
    write_config(isolated_config, "review:\n  model: claude-opus-5\n")

    argv = load_settings().argv("x")

    assert argv[argv.index("--model") + 1] == "claude-opus-5"
    assert argv[-1] == "x"


def test_an_empty_model_leaves_the_choice_to_the_harness(isolated_config):
    """A command that takes no --model has to be able to say so."""
    write_config(isolated_config, "review:\n  model: ''\n")

    assert "--model" not in load_settings().argv("x")


def test_the_model_flag_can_be_spelled_differently(isolated_config):
    write_config(
        isolated_config,
        "review:\n  command: [my-harness]\n  model_flag: -m\n  model: fast\n",
    )

    assert load_settings().argv("x")[:3] == ["my-harness", "-m", "fast"]


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


# ---------------------------------------------------------------------------
# Harness profiles (U-4 / A4-A7)
# ---------------------------------------------------------------------------


def test_the_claude_code_profile_matches_the_old_defaults():
    """A4: pulling the defaults into a profile must not change a single value."""
    profile = settings_module.HARNESS_PROFILES["claude-code"]

    assert profile["command"] == settings_module.DEFAULT_COMMAND
    assert profile["model_flag"] == settings_module.DEFAULT_MODEL_FLAG
    assert profile["allow_tools_flag"] == settings_module.DEFAULT_ALLOW_TOOLS_FLAG
    assert profile["allow_tools_separator"] == settings_module.DEFAULT_ALLOW_TOOLS_SEPARATOR
    assert profile["disallow_tools_flag"] == settings_module.DEFAULT_DISALLOW_TOOLS_FLAG
    assert profile["prompt_separator"] == settings_module.DEFAULT_PROMPT_SEPARATOR
    assert profile["mcp_config_flag"] == settings_module.DEFAULT_MCP_CONFIG_FLAG
    assert profile["strict_mcp_config_flag"] == settings_module.DEFAULT_STRICT_MCP_CONFIG_FLAG


def test_an_unset_harness_leaves_argv_unchanged(isolated_config):
    """A4: no review.harness in the file still yields exactly claude-code's argv."""
    given = load_settings()

    assert given.argv("x") == [
        "claude", "-p",
        "--model", "claude-sonnet-5",
        "--allowed-tools", ",".join(settings_module.DEFAULT_ALLOWED_TOOLS),
        "--disallowed-tools", ",".join(settings_module.DENIED_TOOLS),
        "--", "x",
    ]


def test_an_unknown_harness_falls_back_to_claude_code(isolated_config, caplog):
    write_config(isolated_config, "review:\n  harness: some-cli-nobody-wrote\n")

    given = load_settings()

    assert given.command == ["claude", "-p"]
    assert "some-cli-nobody-wrote" in caplog.text
    assert "claude-code" in caplog.text


def test_a_profile_key_can_still_be_overridden_individually(isolated_config):
    write_config(isolated_config, "review:\n  harness: claude-code\n  model_flag: -m\n")

    given = load_settings()

    assert given.model_flag == "-m"
    assert given.command == ["claude", "-p"]


def test_the_hermes_agent_profile_puts_the_prompt_right_after_the_command(isolated_config):
    """Hermes's `-z` takes the prompt as its own next argument, not a trailing positional
    the way Claude Code's `-p` does -- model and tool flags must come after it, not between
    `-z` and the prompt, or Hermes reads them as `-z`'s value and the real prompt is left
    dangling as an unrecognized positional."""
    write_config(isolated_config, "review:\n  harness: hermes-agent\n")

    argv = load_settings().argv("check this")

    assert argv[:3] == ["foamagent-review", "-z", "check this"]
    assert argv.index("--toolsets") > 2


def test_the_hermes_agent_profile_supplies_hermes_shaped_tool_names(isolated_config):
    """`review.allowed_tools` defaults to Claude Code's tool names (Read, Grep, ...), which
    mean nothing to Hermes -- a profile needs its own default tool list, the same way it
    already overrides the flag spellings, or the allowlist it passes is empty of anything
    Hermes recognizes."""
    write_config(isolated_config, "review:\n  harness: hermes-agent\n")

    given = load_settings()

    assert given.allowed_tools == ["file", "web"]
    # No universal default model the way claude-sonnet-5 is for Claude Code -- hands the
    # choice back to whatever the isolated Hermes profile itself is configured with.
    assert given.model == ""
    assert given.disallow_tools_flag == ""
    assert given.copy_case_dir is True
    assert given.prompt_after_command is True


def test_an_explicit_allowed_tools_still_overrides_the_hermes_profile(isolated_config):
    write_config(
        isolated_config,
        "review:\n  harness: hermes-agent\n  allowed_tools: [web]\n",
    )

    assert load_settings().allowed_tools == ["web"]


def test_the_harness_setting_is_shown_by_config_show(isolated_config):
    assert "review.harness" in settings_module.REVIEW_KEYS

    rows = {row.key: row for row in settings_module.describe()}
    assert rows["review.harness"].value == "claude-code"
    assert rows["review.harness"].is_default


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


def test_the_write_tools_are_denied_not_merely_left_out():
    """Leaving a tool out of the allowlist does not take it away.

    The harness merges that list with what the user's own settings already permit, and a
    review started with a read-only allowlist was seen shelling out through Bash anyway.
    """
    argv = load_settings().argv("x")

    denied = argv[argv.index("--disallowed-tools") + 1].split(",")

    assert "Bash" in denied
    for tool in ("Write", "Edit", "NotebookEdit"):
        assert tool in denied


def test_the_deny_list_is_not_a_setting(isolated_config):
    write_config(
        isolated_config,
        "review:\n  denied_tools: []\n  allowed_tools: [Read, Bash]\n",
    )

    argv = load_settings().argv("x")

    assert "Bash" in argv[argv.index("--disallowed-tools") + 1]


def test_a_command_that_takes_no_deny_flag_says_so(isolated_config, caplog):
    write_config(isolated_config, "review:\n  disallow_tools_flag: ''\n")

    argv = load_settings().argv("x")

    assert "--disallowed-tools" not in argv
    assert "may do to the case" in caplog.text


@pytest.mark.parametrize("tool", ["Bash", "write", "Edit", "NotebookEdit", "Bash(ls:*)"])
def test_a_tool_that_could_change_the_case_is_refused(isolated_config, tool):
    """A reviewer that can rewrite the case is not a reviewer."""
    write_config(isolated_config, f"review:\n  allowed_tools: [Read, {tool}]\n")

    given = load_settings()
    argv = given.argv("x")

    assert given.allowed_tools == ["Read"]
    assert tool not in argv[argv.index("--allowed-tools") + 1]


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
# One model per role (A12, A13, A15)
# ---------------------------------------------------------------------------


def test_each_role_can_name_its_own_model(isolated_config):
    """The arithmetic and the ruling are not the same job, so they need not be the same model."""
    write_config(
        isolated_config,
        "review:\n"
        "  reviewer:\n"
        "    model: claude-sonnet-5\n"
        "  judge:\n"
        "    model: claude-opus-5\n",
    )

    reviewer = load_settings(role="reviewer").argv("x")
    judge = load_settings(role="judge").argv("x")

    assert reviewer[reviewer.index("--model") + 1] == "claude-sonnet-5"
    assert judge[judge.index("--model") + 1] == "claude-opus-5"


def test_a_role_without_its_own_model_uses_the_shared_one(isolated_config):
    write_config(
        isolated_config,
        "review:\n  model: my-model\n  judge:\n    model: claude-opus-5\n",
    )

    assert load_settings(role="reviewer").model == "my-model"
    assert load_settings(role="judge").model == "claude-opus-5"


def test_with_nothing_configured_every_role_gets_the_default_model(isolated_config):
    for role in (None, "reviewer", "judge"):
        assert load_settings(role=role).model == settings_module.DEFAULT_MODEL


def test_a_role_that_is_not_a_mapping_falls_back_to_the_shared_model(isolated_config):
    write_config(isolated_config, "review:\n  model: my-model\n  judge: claude-opus-5\n")

    assert load_settings(role="judge").model == "my-model"


def test_an_unknown_role_is_refused(isolated_config):
    with pytest.raises(ValueError):
        load_settings(role="worker")


def test_the_role_changes_the_model_and_nothing_else(isolated_config):
    """What a review may do must not depend on which role asked for it."""
    write_config(
        isolated_config,
        "review:\n"
        "  timeout_seconds: 42\n"
        "  allowed_tools: [Read, Grep]\n"
        "  reviewer:\n    model: a\n"
        "  judge:\n    model: b\n",
    )

    reviewer = load_settings(role="reviewer")
    judge = load_settings(role="judge")

    assert reviewer.model != judge.model
    assert reviewer.allowed_tools == judge.allowed_tools
    assert reviewer.timeout_seconds == judge.timeout_seconds == 42
    assert reviewer.command == judge.command
    assert reviewer.sandbox == judge.sandbox


# ---------------------------------------------------------------------------
# How much gets reviewed (U-7: A1 to A8)
# ---------------------------------------------------------------------------


def test_everything_is_reviewed_unless_told_otherwise(isolated_config):
    """A result nobody checked is what this fork exists to avoid, so full is the default."""
    settings = load_settings()

    assert settings.mode == "full"
    assert all(settings.covers(task) for task in ("spec", "result", "report"))


@pytest.mark.parametrize(
    "mode, covered",
    [
        ("full", {"spec": True, "result": True, "report": True}),
        ("spec", {"spec": True, "result": False, "report": False}),
        ("off", {"spec": False, "result": False, "report": False}),
    ],
)
def test_each_mode_covers_the_stages_it_says(isolated_config, mode, covered):
    write_config(isolated_config, f"review:\n  mode: {mode}\n")

    settings = load_settings()

    assert settings.mode == mode
    for task, expected in covered.items():
        assert settings.covers(task) is expected


def test_an_unknown_mode_falls_back_to_reviewing_everything(isolated_config, caplog):
    write_config(isolated_config, "review:\n  mode: sometimes\n")

    settings = load_settings()

    assert settings.mode == "full"
    assert "review.mode" in caplog.text


def test_the_mode_does_not_change_which_model_a_role_uses(isolated_config):
    write_config(
        isolated_config,
        "review:\n  mode: off\n  judge:\n    model: claude-opus-5\n",
    )

    assert load_settings(role="judge").model == "claude-opus-5"
    assert load_settings(role="reviewer").model == settings_module.DEFAULT_MODEL


def test_a_stage_that_is_switched_off_starts_no_model(case_dir, monkeypatch, isolated_config):
    write_config(isolated_config, "review:\n  mode: spec\n")
    seen = stub_channel(monkeypatch)

    response = review(case_dir, "result")

    assert not response.available
    assert "review.mode" in response.review
    assert "treat the case as unreviewed" in response.review
    assert seen == {}


def test_the_spec_stage_still_runs_in_spec_mode(case_dir, monkeypatch, isolated_config):
    write_config(isolated_config, "review:\n  mode: spec\n")
    stub_channel(monkeypatch, text="# Findings")

    assert review(case_dir, "spec").available


def test_switching_the_review_off_spends_no_rounds(case_dir, monkeypatch, isolated_config):
    write_config(isolated_config, "review:\n  mode: off\n")
    stub_channel(monkeypatch)

    for stage in ("spec", "result"):
        assert not review(case_dir, stage).available

    # Nothing was recorded at all, so the case has no state file yet.
    state = load_case_state(str(case_dir))
    if state is not None:
        assert state.spec_review_rounds == 0
        assert state.result_review_rounds == 0
    assert not list(case_dir.glob("review-*.md"))


def test_the_report_is_refused_when_the_review_is_off(case_dir, monkeypatch, isolated_config):
    write_config(isolated_config, "review:\n  mode: off\n")
    seen = stub_channel(monkeypatch)

    response = report(case_dir)

    assert not response.available
    assert "review.mode" in response.report
    assert not (case_dir / "report.md").exists()
    assert seen == {}


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


def test_the_review_runs_as_the_reviewer_and_the_report_as_the_judge(case_dir, monkeypatch):
    """A14: which role each tool starts, since that is what selects the model."""
    seen = stub_channel(monkeypatch, text="# Findings")
    review(case_dir, "spec")
    assert seen["role"] == "reviewer"

    seen = stub_channel(monkeypatch, text="# Report")
    report(case_dir)
    assert seen["role"] == "judge"


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


# ---------------------------------------------------------------------------
# Progress while a review is running (U-5 / A13-A18)
# ---------------------------------------------------------------------------


def test_a_slow_review_reports_progress_while_it_waits():
    """A13/A15: past the interval, ctx hears the elapsed time and the total to time out."""
    ctx = FakeContext()

    async def slow():
        await asyncio.sleep(0.05)
        return "done"

    result = asyncio.run(
        audit._await_with_progress(slow(), ctx=ctx, timeout_seconds=600, interval=0.01)
    )

    assert result == "done"
    assert any("Still running" in message for message in ctx.messages["info"])
    assert ctx.progress
    elapsed, total = ctx.progress[0]
    assert elapsed > 0
    assert total == 600


def test_a_fast_review_reports_no_extra_progress():
    """A14: finishing inside one interval means no ticker notification at all."""
    ctx = FakeContext()

    async def fast():
        return "done"

    result = asyncio.run(
        audit._await_with_progress(fast(), ctx=ctx, timeout_seconds=600, interval=60)
    )

    assert result == "done"
    assert ctx.progress == []
    assert not any("Still running" in message for message in ctx.messages["info"])


def test_both_tools_wait_through_the_progress_ticker(case_dir, monkeypatch):
    """A18: request_review and request_report both go through the same wrapper."""
    calls = []
    real = audit._await_with_progress

    async def spy(coro, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        return await real(coro, **kwargs)

    monkeypatch.setattr(audit, "_await_with_progress", spy)

    stub_channel(monkeypatch, text="# Findings")
    review(case_dir, "spec")

    stub_channel(monkeypatch, text="# Report")
    report(case_dir)

    assert len(calls) == 2
    assert all(seconds == settings_module.DEFAULT_TIMEOUT_SECONDS for seconds in calls)


# ---------------------------------------------------------------------------
# The review must not hold the server's stdin
# ---------------------------------------------------------------------------


def test_the_review_is_started_with_its_stdin_closed(monkeypatch, tmp_path):
    """A review that inherits stdin reads the harness's JSON-RPC pipe.

    Over stdio transport the server's stdin is the connection the harness sends requests
    on. `capture_output=True` redirects stdout and stderr only, so without this the review
    subprocess sits on that descriptor: it waits for an EOF a live connection never sends,
    and it consumes the requests meant for the server, which are then never answered. That
    is what stalled `validate_case` behind a running review in the 2026-08-01 session.
    """
    import subprocess

    seen = {}

    class _Completed:
        returncode = 0
        stdout = "a review\n"
        stderr = ""

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return _Completed()

    monkeypatch.setattr(channel.subprocess, "run", fake_run)
    monkeypatch.setattr(channel, "resolve_command", lambda settings=None: None)

    result = channel.run_audit("check this", cwd=str(tmp_path))

    assert result.ok
    assert seen["stdin"] is subprocess.DEVNULL


def test_copy_case_dir_hands_the_review_a_throwaway_copy(monkeypatch, tmp_path):
    """A harness with no way to grant read without also granting write (see the
    hermes-agent profile's `copy_case_dir`) must never be handed the real case -- only a
    copy indistinguishable from it -- and that copy must be gone once the review returns,
    not left behind for the next one to find."""
    real_case = tmp_path / "case"
    real_case.mkdir()
    (real_case / "spec.md").write_text("original", encoding="utf-8")

    seen = {}

    class _Completed:
        returncode = 0
        stdout = "a review\n"
        stderr = ""

    def fake_run(argv, *, cwd=None, **kwargs):
        seen["cwd"] = cwd
        # A review that writes into whatever directory it was handed -- exactly the
        # capability copy_case_dir exists because Hermes's own tools cannot be denied.
        (Path(cwd) / "probe.txt").write_text("touched", encoding="utf-8")
        return _Completed()

    monkeypatch.setattr(channel.subprocess, "run", fake_run)
    monkeypatch.setattr(channel, "resolve_command", lambda settings=None: None)

    settings = ChannelSettings(command=["stub"], copy_case_dir=True)
    result = channel.run_audit("check this", cwd=str(real_case), settings=settings)

    assert result.ok
    assert seen["cwd"] != str(real_case)
    assert not (real_case / "probe.txt").exists()
    assert (real_case / "spec.md").read_text(encoding="utf-8") == "original"
    assert not Path(seen["cwd"]).exists()


def test_copy_case_dir_false_uses_the_real_directory(monkeypatch, tmp_path):
    """The default (Claude Code, and anything else that did not ask for a copy) is
    unchanged: the review still starts in the real case directory."""
    seen = {}

    class _Completed:
        returncode = 0
        stdout = "a review\n"
        stderr = ""

    def fake_run(argv, *, cwd=None, **kwargs):
        seen["cwd"] = cwd
        return _Completed()

    monkeypatch.setattr(channel.subprocess, "run", fake_run)
    monkeypatch.setattr(channel, "resolve_command", lambda settings=None: None)

    settings = ChannelSettings(command=["stub"], copy_case_dir=False)
    channel.run_audit("check this", cwd=str(tmp_path), settings=settings)

    assert seen["cwd"] == str(tmp_path)
