"""The two tools that get a case checked by someone other than its author.

`request_review` starts a review of a case and returns at once; `review_status` is polled
for the findings. `request_report` and `report_status` are the same shape for the report the
user is shown. Both write what they produce into the case directory, so the case carries its
own record of what was agreed, what was objected to, and how it was settled.

Starting and polling are two tools rather than one blocking call because a review can take
tens of minutes, and no MCP client's timeout survives a tool call left open that long -- the
same reason `run_start`/`run_status` replaced a blocking `run` tool in `mcp/deterministic.py`.

The round limits are enforced here rather than requested politely. Two rounds per stage:
after that, `request_review` returns a closing document and starts nothing.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import List

from pydantic import BaseModel, Field

from foamagent.logger import get_logger
from foamagent.mcp.deterministic import MAX_WAIT, POLL_SECONDS
from foamagent.review.channel import (
    ChannelUnavailable,
    resolve_command,
    run_audit,
    unavailable_document,
)
from foamagent.review.documents import (
    RESPONSE_PATTERN,
    RESULT_STAGE,
    ROUND_LIMIT,
    SPEC_STAGE,
    missing_spec_message,
    record_round,
    release_reservation,
    report_path,
    reserve_review_number,
    review_path,
    rounds,
    stage_heading,
    unanswered_reviews,
    write_document,
)
from foamagent.review.registry import FAILED, SUCCEEDED, ReviewRecord, get_review_registry
from foamagent.review.sandbox import REPORT_WORK, work_dir
from foamagent.review.settings import JUDGE_ROLE, REVIEWER_ROLE, load_settings
from foamagent.review.templates import REPORT, RESULT_REVIEW, SPEC_REVIEW, build_prompt

logger = get_logger(__name__)

REPORT_TASK = "report"


class ReviewRequest(BaseModel):
    case_dir: str = Field(
        description=(
            "The case directory: the same one holding spec.md and, after a run, the "
            "results. The reviewer reads this directory and nothing else, and its "
            "findings are written directly into it as review-<n>.md -- there is no "
            "separate input or output location to pass"
        )
    )
    stage: str = Field(
        description=(
            "'spec' before anything is built -- checks the specification against what the "
            "user asked for. 'result' after a run has completed -- checks whether the "
            "result can be believed."
        )
    )


class ReviewResponse(BaseModel):
    review_id: str = Field(default="", description="Pass to review_status; empty when nothing was started")
    case_dir: str = Field(default="", description="The case directory this review read from and wrote into")
    stage: str
    state: str = Field(description="'running' -- call review_status again; 'done' -- read the rest")
    review: str = Field(default="", description="The findings, as Markdown, once done. Present them to yourself, not the user")
    document: str = Field(default="", description="The review-<n>.md this was written to, inside case_dir; empty when none were")
    round: int = Field(default=0, description="Which round this was")
    rounds_left: int = Field(description="Rounds remaining for this stage")
    respond_to: str = Field(
        default="", description="The file your answer to these findings must be written to"
    )
    available: bool = Field(
        default=False,
        description="False when no review could be run; read `review` for why. Meaningless while state='running'",
    )


class ReviewStatusRequest(BaseModel):
    review_id: str = Field(default="", description="Identifier from request_review")
    case_dir: str = Field(default="", description="Alternative to review_id: the case's most recent review")
    stage: str = Field(default="", description="Required with case_dir when review_id is not given")
    wait_seconds: float = Field(
        default=0.0,
        description=(
            "Wait up to this long for the review to finish before answering (0 answers at "
            f"once, {MAX_WAIT:.0f} is the most that will be waited). Returns normally when "
            "the wait runs out, with state still 'running' -- call again. Your client "
            "applies its own timeout to this call, so ask for a few minutes at a time "
            "rather than half an hour."
        ),
    )


class ReportRequest(BaseModel):
    case_dir: str = Field(
        description=(
            "The case directory: the same one holding the specification, the reviews and "
            "the results. The judge reads this directory and nothing else, and writes the "
            "report directly into it as report.md -- there is no separate input or output "
            "location to pass"
        )
    )


class ReportResponse(BaseModel):
    report_id: str = Field(default="", description="Pass to report_status; empty when nothing was started")
    case_dir: str = Field(default="", description="The case directory this report read from and wrote into")
    state: str = Field(description="'running' -- call report_status again; 'done' -- read the rest")
    report: str = Field(default="", description="The report, once done. Show it to the user unchanged")
    document: str = Field(default="", description="The report.md this was written to, inside case_dir")
    available: bool = Field(
        default=False,
        description="False when no report could be produced; read `report` for why. Meaningless while state='running'",
    )
    warnings: List[str] = Field(default_factory=list)


class ReportStatusRequest(BaseModel):
    report_id: str = Field(default="", description="Identifier from request_report")
    case_dir: str = Field(default="", description="Alternative to report_id: the case's most recent report")
    wait_seconds: float = Field(
        default=0.0,
        description=(
            "Wait up to this long for the report to finish before answering (0 answers at "
            f"once, {MAX_WAIT:.0f} is the most that will be waited). Returns normally when "
            "the wait runs out, with state still 'running' -- call again. Your client "
            "applies its own timeout to this call, so ask for a few minutes at a time "
            "rather than half an hour."
        ),
    )


def _closing_document(stage: str) -> str:
    subject = "specification" if stage == SPEC_STAGE else "result"
    return (
        f"# {subject.capitalize()} review: closed\n\n"
        f"This case has used both of its {subject} review rounds. No further review of the "
        f"{subject} will be carried out.\n\n"
        "Anything still disputed stays disputed: carry it forward rather than settling it "
        "yourself, and it will appear in the report's account of what this calculation "
        "does not establish.\n"
    )


def _review_work(case_dir: str, stage: str, number: int) -> dict:
    """Run one review round and report what to fill into its `ReviewRecord`.

    Runs on the registry's background thread -- everything this touches (`run_audit`,
    `write_document`, `record_round`) is safe to call off the request that started it.
    """
    template = SPEC_REVIEW if stage == SPEC_STAGE else RESULT_REVIEW
    result = run_audit(
        build_prompt(template, case_dir),
        cwd=case_dir,
        work_dir=work_dir(case_dir, number),
        role=REVIEWER_ROLE,
    )

    if result.failed:
        # `number` was only reserved (see reserve_review_number) before this thread
        # started, not written -- release it rather than leave request_review's next
        # caller stepping over a number nothing will ever occupy.
        release_reservation(case_dir, number)
        return {
            "state": FAILED,
            "detail": result.detail,
            "text": unavailable_document(result.detail, "Independent review"),
            "available": False,
            "rounds_left": rounds(case_dir).remaining(stage),
        }

    path = write_document(review_path(case_dir, number), stage_heading(stage, number) + result.text)
    release_reservation(case_dir, number)
    state = record_round(case_dir, stage)

    return {
        "state": SUCCEEDED,
        "text": result.text,
        "document": str(path),
        "round": number,
        "rounds_left": state.remaining(stage),
        "respond_to": str(os.path.join(case_dir, RESPONSE_PATTERN.format(n=number))),
        "available": True,
    }


def _report_work(case_dir: str, warnings: List[str]) -> dict:
    """Write the report and report what to fill into its `ReviewRecord`."""
    result = run_audit(
        build_prompt(REPORT, case_dir),
        cwd=case_dir,
        work_dir=work_dir(case_dir, REPORT_WORK),
        role=JUDGE_ROLE,
    )

    if result.failed:
        return {
            "state": FAILED,
            "detail": result.detail,
            "text": unavailable_document(result.detail, "Report"),
            "available": False,
            "warnings": warnings,
        }

    path = write_document(report_path(case_dir), result.text)
    return {
        "state": SUCCEEDED,
        "text": result.text,
        "document": str(path),
        "available": True,
        "warnings": warnings,
    }


def _finished_review_response(record: ReviewRecord, stage: str) -> ReviewResponse:
    return ReviewResponse(
        review_id=record.review_id,
        case_dir=record.case_dir,
        stage=stage,
        state="done",
        review=record.text,
        document=record.document,
        round=record.round,
        rounds_left=record.rounds_left,
        respond_to=record.respond_to,
        available=record.available,
    )


async def request_review(request: ReviewRequest, ctx=None) -> ReviewResponse:
    """Start an independent check of this case against what the user asked for, and return
    at once. Poll `review_status` (with `wait_seconds`) until it reports `state='done'`.

    There is one location, not two: the reviewer reads `case_dir` and writes its findings
    directly into it as `review-<n>.md`. You do not choose a separate place for either.

    Call this twice in a case's life:

    - **stage='spec'**, before building anything. `spec.md` must exist and must quote the
      user's request word for word. A specification that answers the wrong question wastes
      every step that follows, so this one is not optional.
    - **stage='result'**, once a run has completed. Not for a case that is still failing:
      mechanical failures are yours to fix, and this stage asks whether a finished result
      can be believed.

    Findings come back as Markdown and are written into the case. Answer each one — fix it,
    or say why it does not hold — in the file named by `respond_to`. That answer is read
    later by whoever writes the report, and a finding with no answer beside it reads as one
    nobody disputed.

    Two rounds per stage. After that this returns a closing document and starts nothing.
    """
    stage = (request.stage or "").strip().lower()
    if stage not in (SPEC_STAGE, RESULT_STAGE):
        raise ValueError(f"stage must be 'spec' or 'result', not {request.stage!r}")

    case_dir = os.path.abspath(request.case_dir)
    if not os.path.isdir(case_dir):
        raise ValueError(f"Case directory does not exist: {case_dir}")

    missing = missing_spec_message(case_dir)
    if missing:
        raise ValueError(missing)

    settings = load_settings()
    if not settings.covers(stage):
        reason = settings.why_not_covered(stage)
        logger.warning("%s", reason)
        if ctx is not None:
            await ctx.warning(reason)
        return ReviewResponse(
            case_dir=case_dir,
            stage=stage,
            state="done",
            review=unavailable_document(reason, "Independent review"),
            rounds_left=rounds(case_dir).remaining(stage),
            available=False,
        )

    state = rounds(case_dir)
    if state.remaining(stage) <= 0:
        if ctx is not None:
            await ctx.info(f"The {stage} review is closed after {ROUND_LIMIT} rounds.")
        return ReviewResponse(
            case_dir=case_dir,
            stage=stage,
            state="done",
            review=_closing_document(stage),
            rounds_left=0,
            available=True,
        )

    pending = unanswered_reviews(case_dir)
    if pending:
        files = ", ".join(RESPONSE_PATTERN.format(n=n) for n in pending)
        raise ValueError(
            f"Answer the previous findings before asking for more: {files} "
            f"{'is' if len(pending) == 1 else 'are'} missing from {case_dir}."
        )

    try:
        resolve_command()
    except ChannelUnavailable as exc:
        if ctx is not None:
            await ctx.warning(str(exc))
        return ReviewResponse(
            case_dir=case_dir,
            stage=stage,
            state="done",
            review=unavailable_document(str(exc), "Independent review"),
            rounds_left=state.remaining(stage),
            available=False,
        )

    # A retried client call for the exact same (case_dir, stage) while one is already
    # running is registry.start()'s own job to dedupe (see its docstring) -- checked here,
    # before reserving a number, so a duplicate call is not left having burned one on a
    # review that never actually runs.
    registry = get_review_registry()
    in_flight = registry.latest(case_dir, stage)
    if in_flight is not None and not in_flight.done:
        record = in_flight
    else:
        # Fixed before the review starts, because it names the directory the review keeps
        # its calculations in, and that has to exist while the review is still running.
        # reserve_review_number() reads existing_reviews() and marks the number taken in one
        # case_lock of its own, so two concurrent request_review calls on the same case_dir
        # for *different* stages (spec and result draw from the same number sequence)
        # cannot both read the same starting count and pick the same number, one silently
        # overwriting the other's review-<n>.md.
        number = reserve_review_number(case_dir)

        record = registry.start(case_dir, stage, lambda: _review_work(case_dir, stage, number))

    if ctx is not None:
        await ctx.info(f"Started the {stage} review of {case_dir} as {record.review_id}.")

    if record.done:
        return _finished_review_response(record, stage)

    return ReviewResponse(
        review_id=record.review_id,
        case_dir=case_dir,
        stage=stage,
        state="running",
        rounds_left=state.remaining(stage),
    )


async def review_status(request: ReviewStatusRequest, ctx=None) -> ReviewResponse:
    """Report how a review is going, optionally waiting for it to finish first.

    With `wait_seconds` unset this answers at once, running or not. With it set the call
    sleeps until the review finishes or the wait expires, whichever comes first, and either
    way returns a state rather than an error. Use it: a review nobody waited for is findings
    nobody has read.
    """
    registry = get_review_registry()
    record = registry.get(request.review_id) if request.review_id else None
    if record is None and request.case_dir and request.stage:
        record = registry.latest(request.case_dir, request.stage.strip().lower())

    if record is None:
        raise ValueError(
            "No such review. Pass the review_id returned by request_review, or a case_dir "
            "and stage that have been reviewed at least once."
        )

    if request.wait_seconds > 0 and not record.done:
        deadline = time.monotonic() + min(request.wait_seconds, MAX_WAIT)
        while not record.done and time.monotonic() < deadline:
            await asyncio.sleep(min(POLL_SECONDS, max(0.0, deadline - time.monotonic())))
            record = registry.get(record.review_id) or record

    if not record.done:
        left = rounds(record.case_dir).remaining(record.task) if record.task in (SPEC_STAGE, RESULT_STAGE) else 0
        return ReviewResponse(
            review_id=record.review_id,
            case_dir=record.case_dir,
            stage=record.task,
            state="running",
            rounds_left=left,
        )

    return _finished_review_response(record, record.task)


async def request_report(request: ReportRequest, ctx=None) -> ReportResponse:
    """Start the report for the user, from everything this case has on disk, and return at
    once. Poll `report_status` (with `wait_seconds`) until it reports `state='done'`.

    There is one location, not two: the judge reads `case_dir` and writes the report
    directly into it as `report.md`. You do not choose a separate place for either.

    Call this once the result review is done and answered. The report is written by
    weighing the specification, the findings and your answers to them; it rules on each
    disputed point and states what the calculation does not establish.

    **Show the user what comes back, unchanged.** Do not summarise it, soften its
    conclusions, or drop the part about limits. If you disagree with it, say so in your own
    words after presenting it.
    """
    case_dir = os.path.abspath(request.case_dir)
    if not os.path.isdir(case_dir):
        raise ValueError(f"Case directory does not exist: {case_dir}")

    missing = missing_spec_message(case_dir)
    if missing:
        raise ValueError(missing)

    settings = load_settings()
    if not settings.covers("report"):
        reason = settings.why_not_covered("report")
        logger.warning("%s", reason)
        if ctx is not None:
            await ctx.warning(reason)
        return ReportResponse(
            case_dir=case_dir,
            state="done",
            report=unavailable_document(reason, "Report"),
            available=False,
            warnings=[reason],
        )

    warnings: List[str] = []
    state = rounds(case_dir)
    if state.result == 0:
        warnings.append(
            "No result review has been run for this case, so the report is written from an "
            "unchecked result."
        )
    pending = unanswered_reviews(case_dir)
    if pending:
        warnings.append(
            "These findings have no answer recorded: "
            + ", ".join(RESPONSE_PATTERN.format(n=n) for n in pending)
            + ". They will be read as undisputed."
        )

    for warning in warnings:
        logger.warning("%s", warning)
        if ctx is not None:
            await ctx.warning(warning)

    try:
        resolve_command()
    except ChannelUnavailable as exc:
        if ctx is not None:
            await ctx.warning(str(exc))
        return ReportResponse(
            case_dir=case_dir,
            state="done",
            report=unavailable_document(str(exc), "Report"),
            available=False,
            warnings=warnings,
        )

    record = get_review_registry().start(case_dir, REPORT_TASK, lambda: _report_work(case_dir, warnings))

    if ctx is not None:
        await ctx.info(f"Started the report for {case_dir} as {record.review_id}.")

    if record.done:
        return ReportResponse(
            report_id=record.review_id,
            case_dir=case_dir,
            state="done",
            report=record.text,
            document=record.document,
            available=record.available,
            warnings=record.warnings,
        )

    return ReportResponse(
        report_id=record.review_id, case_dir=case_dir, state="running", warnings=warnings
    )


async def report_status(request: ReportStatusRequest, ctx=None) -> ReportResponse:
    """Report how the report is going, optionally waiting for it to finish first.

    Same shape as `review_status`: with `wait_seconds` unset this answers at once; with it
    set the call sleeps until the report finishes or the wait expires.
    """
    registry = get_review_registry()
    record = registry.get(request.report_id) if request.report_id else None
    if record is None and request.case_dir:
        record = registry.latest(request.case_dir, REPORT_TASK)

    if record is None:
        raise ValueError(
            "No such report. Pass the report_id returned by request_report, or a case_dir "
            "that has had a report requested at least once."
        )

    if request.wait_seconds > 0 and not record.done:
        deadline = time.monotonic() + min(request.wait_seconds, MAX_WAIT)
        while not record.done and time.monotonic() < deadline:
            await asyncio.sleep(min(POLL_SECONDS, max(0.0, deadline - time.monotonic())))
            record = registry.get(record.review_id) or record

    if not record.done:
        return ReportResponse(
            report_id=record.review_id, case_dir=record.case_dir, state="running"
        )

    return ReportResponse(
        report_id=record.review_id,
        case_dir=record.case_dir,
        state="done",
        report=record.text,
        document=record.document,
        available=record.available,
        warnings=record.warnings,
    )


TOOLS = (
    ("request_review", request_review),
    ("review_status", review_status),
    ("request_report", request_report),
    ("report_status", report_status),
)


def register(mcp) -> None:
    """Add the review tools to a FastMCP server."""
    for name, function in TOOLS:
        mcp.tool(name=name)(function)


__all__ = ["TOOLS", "register", "report_status", "request_report", "request_review", "review_status"]
