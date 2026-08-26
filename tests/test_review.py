"""Unit tests for the independent review: settings, argv, rounds and documents.

No model is started anywhere here. The subprocess is stubbed, so what is under test is the
command line that would have been run, the enforcement of the round limits, and what lands
in the case directory -- which is where the acceptance conditions A3, A4, A7 and A10 live.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from foamagent.case_state import load_case_state
from foamagent.mcp import audit
from foamagent.review import channel, documents, settings as settings_module, templates
from foamagent.review.channel import ChannelUnavailable, resolve_command
from foamagent.review.documents import ROUND_LIMIT
from foamagent.review.registry import ReviewRegistry, set_review_registry
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


@pytest.fixture(autouse=True)
def isolated_review_registry():
    """A fresh registry per test so state from one test never leaks into the next."""
    set_review_registry(ReviewRegistry())
    yield
    set_review_registry(ReviewRegistry())


@pytest.fixture
def case_dir(tmp_path):
    case = tmp_path / "cavity"
    (case / "system").mkdir(parents=True)
    (case / "spec.md").write_text(
        "# Specification\n\n## The request, verbatim\n\n> Lid-driven cavity at Re=1000\n",
        encoding="utf-8",
    )
    return case


def test_reserve_review_number_is_reflected_immediately(case_dir):
    """reserve_review_number must make next_review_number see the claim right away, or two
    callers racing on it would both get the same number -- this is the whole point."""
    first = documents.reserve_review_number(case_dir)
    second = documents.reserve_review_number(case_dir)

    assert first == 1
    assert second == 2


def test_a_reservation_does_not_look_like_an_unanswered_review(case_dir):
    """A review still computing must not trip unanswered_reviews()'s "answer the previous
    findings first" gate -- that gate is for a real finding nobody responded to, not a
    review that has not produced one yet."""
    documents.reserve_review_number(case_dir)

    assert documents.unanswered_reviews(case_dir) == []


def test_releasing_a_reservation_removes_it(case_dir):
    number = documents.reserve_review_number(case_dir)

    documents.release_reservation(case_dir, number)

    assert documents.next_review_number(case_dir) == number


def test_concurrent_reservations_never_collide(case_dir):
    """Regression: reserve_review_number's read (existing + reserved) then mark-taken must
    be atomic, or two threads racing on the same case_dir (concretely: the spec and result
    stages, which share this one number sequence) could both read the same count and pick
    the same number, one silently overwriting the other's review-<n>.md."""
    numbers = []
    lock = threading.Lock()

    def reserve():
        n = documents.reserve_review_number(case_dir)
        with lock:
            numbers.append(n)

    threads = [threading.Thread(target=reserve) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(numbers) == list(range(1, 21))


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

    def fake_run(prompt, *, cwd=None, work_dir=None, settings=None):
        seen["prompt"] = prompt
        seen["cwd"] = cwd
        seen["work_dir"] = work_dir
        return channel.ChannelResult(ok=ok, text=text, detail=detail)

    monkeypatch.setattr(audit, "run_audit", fake_run)
    monkeypatch.setattr(audit, "resolve_command", lambda: ["claude", "-p"])
    return seen


# ---------------------------------------------------------------------------
# Settings and argv (A3)
# ---------------------------------------------------------------------------


def test_the_defaults_drive_claude_code():
    given = load_settings()

    assert given.command == [
        "claude", "-p", "--model", "claude-sonnet-5", "--dangerously-skip-permissions",
    ]
    assert given.timeout_seconds > 0


def test_the_command_reaches_the_command_line(isolated_config):
    write_config(
        isolated_config,
        "review:\n"
        "  command: [claude, -p, --dangerously-skip-permissions]\n"
        "  timeout_seconds: 120\n",
    )

    given = load_settings()
    argv = given.argv("do the review")

    assert given.timeout_seconds == 120
    assert "--dangerously-skip-permissions" in argv
    assert argv[-1] == "do the review"


def test_the_review_names_its_model(isolated_config):
    """Which model reviewed the case is part of the configured command, not the harness's
    private default."""
    argv = load_settings().argv("x")

    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"


def test_the_model_can_be_chosen(isolated_config):
    write_config(
        isolated_config,
        "review:\n  command: [claude, -p, --model, claude-opus-5, "
        "--dangerously-skip-permissions]\n",
    )

    argv = load_settings().argv("x")

    assert argv[argv.index("--model") + 1] == "claude-opus-5"
    assert argv[-1] == "x"


def test_a_command_with_no_model_flag_is_left_alone(isolated_config):
    """A command that takes no --model has to be able to say so."""
    write_config(isolated_config, "review:\n  command: [my-harness]\n")

    assert "--model" not in load_settings().argv("x")


def test_the_prompt_comes_after_the_separator():
    """The separator ends option parsing before the prompt.

    Without it a prompt that starts with `-` is read as more flags, and the review starts
    with no task -- which is how this was found.
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
# The configured command (U-4 / A4-A7)
# ---------------------------------------------------------------------------


def test_an_unset_command_leaves_argv_unchanged(isolated_config):
    """A4: no review.command in the file still yields exactly the default argv."""
    given = load_settings()

    assert given.argv("x") == [
        "claude", "-p",
        "--model", "claude-sonnet-5",
        "--dangerously-skip-permissions",
        "--", "x",
    ]


def test_a_prompt_after_command_harness_puts_the_prompt_right_after_the_command(isolated_config):
    """A harness whose prompt-taking flag needs the prompt as its own immediately following
    argument (Hermes's `-z PROMPT`), unlike Claude Code's `-p` (trailing positional): model
    and tool flags must come after it, not between `-z` and the prompt, or the harness reads
    them as `-z`'s value and the real prompt is left dangling as an unrecognized positional."""
    write_config(
        isolated_config,
        "review:\n  command: [hermes, -z]\n  prompt_after_command: true\n"
        "  prompt_separator: ''\n",
    )

    argv = load_settings().argv("check this")

    assert argv == ["hermes", "-z", "check this"]


def test_a_broken_settings_file_falls_back_to_the_defaults(isolated_config):
    write_config(isolated_config, "review: [this is not a mapping]\n")

    assert load_settings().command == settings_module.DEFAULT_COMMAND


def test_a_missing_command_is_reported_rather_than_run(monkeypatch):
    monkeypatch.setattr(channel.shutil, "which", lambda name: None)

    with pytest.raises(ChannelUnavailable, match="not on PATH"):
        resolve_command(ChannelSettings(command=["no-such-harness"]))


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


def test_the_mode_does_not_change_the_command(isolated_config):
    write_config(
        isolated_config,
        "review:\n  mode: off\n  command: [claude, -p]\n",
    )

    assert load_settings().command == ["claude", "-p"]


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


def test_no_shipped_template_tells_the_model_to_read_everything():
    """Regression: "Read everything in the case directory" (judge-report.md) and "You may
    read anything in the case directory" (all three) were seen read literally as an
    instruction to read every field file at every time step -- megabytes of numbers -- into
    the reviewer's own context instead of computing over them with run_script, blowing the
    context up on a real case. Every template must instead say reading everything is not
    required, and point large data at run_script."""
    for name in templates.TEMPLATES:
        text = templates.load_template(name)
        assert "read everything" not in text.lower()
        assert "run_script" in text


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


def _settle(started, status_call, timeout=5.0):
    """Wait for a request_review/request_report response to reach state='done'.

    `request_review`/`request_report` return at once; the work happens on a background
    thread (see review/registry.py). Polls through the public review_status/report_status
    tools, since those (not the registry) are what request_review/request_report actually
    hand a caller to poll with.
    """
    if started.state == "done":
        return started
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = status_call()
        if status.state == "done":
            return status
        time.sleep(0.01)
    raise AssertionError("review did not finish")


def review(case_dir, stage, ctx=None):
    started = asyncio.run(
        audit.request_review(audit.ReviewRequest(case_dir=str(case_dir), stage=stage), ctx)
    )
    return _settle(
        started,
        lambda: asyncio.run(
            audit.review_status(audit.ReviewStatusRequest(review_id=started.review_id))
        ),
    )


def test_the_response_echoes_the_case_dir_it_read_and_wrote(case_dir, monkeypatch):
    """The one thing agents kept being unsure of: is there a separate read/write location?
    There is not -- both request_review and request_report echo back the single case_dir
    they operated on, at every stage (starting, running, and done)."""
    stub_channel(monkeypatch, text="# Findings")

    started = asyncio.run(
        audit.request_review(audit.ReviewRequest(case_dir=str(case_dir), stage="spec"))
    )
    assert started.case_dir == str(case_dir)

    done = _settle(
        started,
        lambda: asyncio.run(
            audit.review_status(audit.ReviewStatusRequest(review_id=started.review_id))
        ),
    )
    assert done.case_dir == str(case_dir)

    _answer(case_dir, done.round)
    report_started = asyncio.run(audit.request_report(audit.ReportRequest(case_dir=str(case_dir))))
    assert report_started.case_dir == str(case_dir)

    report_done = _settle(
        report_started,
        lambda: asyncio.run(
            audit.report_status(audit.ReportStatusRequest(report_id=report_started.report_id))
        ),
    )
    assert report_done.case_dir == str(case_dir)


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
    assert "not carried out" in response.review  # never started -- distinct from "failed" below
    assert not (case_dir / "review-1.md").exists()  # nothing was recorded as a review
    assert ctx.messages["warning"]


def test_a_review_that_fails_costs_no_round(case_dir, monkeypatch):
    """A command that is genuinely configured, starts, and exits badly is a different
    situation from one that was never runnable -- see test_no_channel_returns_a_document_
    saying_so above. Both report available=False, but only this one ran, and the document's
    heading says so: a caller that skims `available` alone must not conflate the two, which
    is exactly what happened with a hand-edited review.command missing a companion setting
    (hermes's usage dump for a rejected argv looked identical to "not configured")."""
    stub_channel(monkeypatch, ok=False, text="", detail="the harness exited with code 1")

    response = review(case_dir, "spec")

    assert not response.available
    assert "exited with code 1" in response.review
    assert "failed" in response.review
    assert "not carried out" not in response.review
    assert documents.rounds(case_dir).spec == 0


# ---------------------------------------------------------------------------
# request_report
# ---------------------------------------------------------------------------


def report(case_dir, ctx=None):
    started = asyncio.run(audit.request_report(audit.ReportRequest(case_dir=str(case_dir)), ctx))
    return _settle(
        started,
        lambda: asyncio.run(
            audit.report_status(audit.ReportStatusRequest(report_id=started.report_id))
        ),
    )


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


# ---------------------------------------------------------------------------
# Starting and polling (U-5): request_review/request_report return at once,
# review_status/report_status are polled for the result
# ---------------------------------------------------------------------------


def _blocking_channel(monkeypatch, release):
    """Like stub_channel, but run_audit blocks on ``release`` before returning."""
    def fake_run(prompt, *, cwd=None, work_dir=None, settings=None):
        release.wait(timeout=5)
        return channel.ChannelResult(ok=True, text="findings")

    monkeypatch.setattr(audit, "run_audit", fake_run)
    monkeypatch.setattr(audit, "resolve_command", lambda: ["claude", "-p"])


def test_request_review_returns_at_once_even_while_the_subprocess_is_still_running(
    case_dir, monkeypatch
):
    """The whole point: no caller waits out a multi-minute subprocess inline any more."""
    import threading

    release = threading.Event()
    _blocking_channel(monkeypatch, release)

    started = time.time()
    response = asyncio.run(
        audit.request_review(audit.ReviewRequest(case_dir=str(case_dir), stage="spec"))
    )
    elapsed = time.time() - started

    try:
        assert elapsed < 1.0
        assert response.state == "running"
        assert response.review_id

        status = asyncio.run(
            audit.review_status(audit.ReviewStatusRequest(review_id=response.review_id))
        )
        assert status.state == "running"
    finally:
        release.set()


def test_review_status_reports_done_once_the_thread_finishes(case_dir, monkeypatch):
    stub_channel(monkeypatch, text="# Findings")

    started = asyncio.run(
        audit.request_review(audit.ReviewRequest(case_dir=str(case_dir), stage="spec"))
    )
    status = _settle(
        started,
        lambda: asyncio.run(
            audit.review_status(audit.ReviewStatusRequest(review_id=started.review_id))
        ),
    )

    assert status.review_id == started.review_id
    assert status.state == "done"
    assert "Findings" in status.review


def test_review_status_wait_seconds_blocks_until_done(case_dir, monkeypatch):
    import threading

    release = threading.Event()
    _blocking_channel(monkeypatch, release)
    threading.Timer(0.02, release.set).start()

    started = asyncio.run(
        audit.request_review(audit.ReviewRequest(case_dir=str(case_dir), stage="spec"))
    )
    status = asyncio.run(
        audit.review_status(
            audit.ReviewStatusRequest(review_id=started.review_id, wait_seconds=5)
        )
    )

    assert status.state == "done"


def test_a_second_request_review_while_one_is_running_does_not_start_a_second_subprocess(
    case_dir, monkeypatch
):
    import threading

    calls = []
    started = threading.Event()
    release = threading.Event()

    def fake_run(prompt, *, cwd=None, work_dir=None, settings=None):
        calls.append(1)
        started.set()
        release.wait(timeout=5)
        return channel.ChannelResult(ok=True, text="findings")

    monkeypatch.setattr(audit, "run_audit", fake_run)
    monkeypatch.setattr(audit, "resolve_command", lambda: ["claude", "-p"])

    try:
        first = asyncio.run(
            audit.request_review(audit.ReviewRequest(case_dir=str(case_dir), stage="spec"))
        )
        # The first review runs on a background thread; without this, the second call
        # can land before that thread has actually reached fake_run(), making `calls`
        # empty by chance rather than because dedup failed.
        assert started.wait(timeout=5)
        second = asyncio.run(
            audit.request_review(audit.ReviewRequest(case_dir=str(case_dir), stage="spec"))
        )
    finally:
        release.set()

    assert first.review_id == second.review_id
    assert len(calls) == 1


def test_request_report_returns_at_once_too(case_dir, monkeypatch):
    import threading

    release = threading.Event()
    _blocking_channel(monkeypatch, release)

    started = time.time()
    response = asyncio.run(audit.request_report(audit.ReportRequest(case_dir=str(case_dir))))
    elapsed = time.time() - started

    try:
        assert elapsed < 1.0
        assert response.state == "running"
        assert response.report_id
    finally:
        release.set()


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


def test_an_api_error_banner_is_a_failure_not_a_review(monkeypatch, tmp_path):
    """A headless review subprocess that hits a billing/quota limit can still exit 0 with
    the API's own error banner as its only output -- there is no human to retry, so it just
    says so and returns. Confirmed for real on a downstream validation run: every review
    round and the report call returned exactly this text, exit 0, and it was written into
    review-N.md/report.md as if it were a genuine (if terse) review.
    """
    class _Completed:
        returncode = 0
        stdout = ("HTTP 400: Third-party apps now draw from your extra usage, not your plan "
                   "limits. Add more at claude.ai/settings/usage and keep going.")
        stderr = ""

    monkeypatch.setattr(channel.subprocess, "run", lambda argv, **kwargs: _Completed())
    monkeypatch.setattr(channel, "resolve_command", lambda settings=None: None)

    result = channel.run_audit("check this", cwd=str(tmp_path))

    assert not result.ok
    assert "HTTP 400" in result.detail


def test_run_audit_always_starts_in_the_real_case_directory(monkeypatch, tmp_path):
    """No case-copy isolation any more: the review starts in the real case directory,
    whatever the settings say -- there is no longer a setting that changes this."""
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

    settings = ChannelSettings(command=["stub"])
    channel.run_audit("check this", cwd=str(tmp_path), settings=settings)

    assert seen["cwd"] == str(tmp_path)
