"""The two tools that get a case checked by someone other than its author.

`request_review` returns findings on a case; `request_report` returns the report the user
is shown. Both write what they return into the case directory, so the case carries its own
record of what was agreed, what was objected to, and how it was settled.

The round limits are enforced here rather than requested politely. Two rounds per stage:
after that, `request_review` returns a closing document and starts nothing.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import List, Optional

from pydantic import BaseModel, Field

from foamagent.logger import get_logger
from foamagent.review import (
    REPORT,
    REPORT_WORK,
    RESULT_REVIEW,
    RESULT_STAGE,
    JUDGE_ROLE,
    REVIEWER_ROLE,
    ROUND_LIMIT,
    SPEC_REVIEW,
    SPEC_STAGE,
    ChannelUnavailable,
    build_prompt,
    load_settings,
    next_review_number,
    record_round,
    report_path,
    resolve_command,
    review_path,
    rounds,
    run_audit,
    unanswered_reviews,
    unavailable_document,
    work_dir,
    write_document,
)
from foamagent.review.documents import (
    RESPONSE_PATTERN,
    missing_spec_message,
    stage_heading,
)

logger = get_logger(__name__)

# How often a running review reports back while its subprocess is still going. A review
# takes minutes; without this the caller hears one line at the start and then nothing until
# it ends. Fixed rather than configurable -- a wrong value here costs a slightly early or
# late notification, not a broken review, so it is not worth a setting.
PROGRESS_INTERVAL_SECONDS = 60.0


async def _await_with_progress(
    coro, *, ctx, timeout_seconds: int, interval: float = PROGRESS_INTERVAL_SECONDS
):
    """Wait for ``coro``, telling ``ctx`` how long it has been running.

    ``coro`` is not touched otherwise: this only watches it from outside and reports back
    every ``interval`` seconds while it is still going, with the elapsed time and how much
    is left before ``timeout_seconds`` cuts it off.
    """
    task = asyncio.ensure_future(coro)
    started = time.monotonic()
    while True:
        done, _ = await asyncio.wait({task}, timeout=interval)
        if task in done:
            return task.result()
        elapsed = time.monotonic() - started
        if ctx is not None:
            remaining = max(0.0, timeout_seconds - elapsed)
            await ctx.report_progress(progress=elapsed, total=timeout_seconds)
            await ctx.info(
                f"Still running after {elapsed:.0f}s ({remaining:.0f}s left before it times out)."
            )


class ReviewRequest(BaseModel):
    case_dir: str = Field(description="Case directory holding spec.md and, after a run, the results")
    stage: str = Field(
        description=(
            "'spec' before anything is built -- checks the specification against what the "
            "user asked for. 'result' after a run has completed -- checks whether the "
            "result can be believed."
        )
    )


class ReviewResponse(BaseModel):
    stage: str
    review: str = Field(description="The findings, as Markdown. Present them to yourself, not the user")
    document: str = Field(default="", description="Where the findings were written, empty when none were")
    round: int = Field(default=0, description="Which round this was")
    rounds_left: int = Field(description="Rounds remaining for this stage")
    respond_to: str = Field(
        default="", description="The file your answer to these findings must be written to"
    )
    available: bool = Field(description="False when no review could be run; read `review` for why")


class ReportRequest(BaseModel):
    case_dir: str = Field(description="Case directory holding the specification, the reviews and the results")


class ReportResponse(BaseModel):
    report: str = Field(description="The report. Show it to the user unchanged")
    document: str = Field(default="", description="Where the report was written")
    available: bool = Field(description="False when no report could be produced; read `report` for why")
    warnings: List[str] = Field(default_factory=list)


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


async def request_review(request: ReviewRequest, ctx=None) -> ReviewResponse:
    """Have this case checked against what the user asked for.

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
            stage=stage,
            review=unavailable_document(reason, "Independent review"),
            rounds_left=rounds(case_dir).remaining(stage),
            available=False,
        )

    state = rounds(case_dir)
    if state.remaining(stage) <= 0:
        if ctx is not None:
            await ctx.info(f"The {stage} review is closed after {ROUND_LIMIT} rounds.")
        return ReviewResponse(
            stage=stage,
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

    template = SPEC_REVIEW if stage == SPEC_STAGE else RESULT_REVIEW

    try:
        resolve_command()
    except ChannelUnavailable as exc:
        if ctx is not None:
            await ctx.warning(str(exc))
        return ReviewResponse(
            stage=stage,
            review=unavailable_document(str(exc), "Independent review"),
            rounds_left=state.remaining(stage),
            available=False,
        )

    if ctx is not None:
        await ctx.info(f"Running the {stage} review of {case_dir}. This takes a few minutes.")

    # Fixed before the review starts, because it names the directory the review keeps its
    # calculations in, and that has to exist while the review is still running.
    number = next_review_number(case_dir)

    result = await _await_with_progress(
        asyncio.to_thread(
            run_audit,
            build_prompt(template, case_dir),
            cwd=case_dir,
            work_dir=work_dir(case_dir, number),
            role=REVIEWER_ROLE,
        ),
        ctx=ctx,
        timeout_seconds=load_settings(role=REVIEWER_ROLE).timeout_seconds,
    )

    if result.failed:
        if ctx is not None:
            await ctx.warning(f"The review did not complete: {result.detail}")
        return ReviewResponse(
            stage=stage,
            review=unavailable_document(result.detail, "Independent review"),
            rounds_left=state.remaining(stage),
            available=False,
        )

    path = write_document(review_path(case_dir, number), stage_heading(stage, number) + result.text)
    state = record_round(case_dir, stage)

    if ctx is not None:
        await ctx.info(f"Findings written to {path}; {state.remaining(stage)} round(s) left.")

    return ReviewResponse(
        stage=stage,
        review=result.text,
        document=str(path),
        round=number,
        rounds_left=state.remaining(stage),
        respond_to=str(os.path.join(case_dir, RESPONSE_PATTERN.format(n=number))),
        available=True,
    )


async def request_report(request: ReportRequest, ctx=None) -> ReportResponse:
    """Produce the report for the user, from everything this case has on disk.

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
            report=unavailable_document(str(exc), "Report"),
            available=False,
            warnings=warnings,
        )

    if ctx is not None:
        await ctx.info(f"Writing the report for {case_dir}. This takes a few minutes.")

    result = await _await_with_progress(
        asyncio.to_thread(
            run_audit,
            build_prompt(REPORT, case_dir),
            cwd=case_dir,
            work_dir=work_dir(case_dir, REPORT_WORK),
            role=JUDGE_ROLE,
        ),
        ctx=ctx,
        timeout_seconds=load_settings(role=JUDGE_ROLE).timeout_seconds,
    )

    if result.failed:
        if ctx is not None:
            await ctx.warning(f"The report was not produced: {result.detail}")
        return ReportResponse(
            report=unavailable_document(result.detail, "Report"),
            available=False,
            warnings=warnings,
        )

    path = write_document(report_path(case_dir), result.text)
    if ctx is not None:
        await ctx.info(f"Report written to {path}.")

    return ReportResponse(report=result.text, document=str(path), available=True, warnings=warnings)


TOOLS = (
    ("request_review", request_review),
    ("request_report", request_report),
)


def register(mcp) -> None:
    """Add the review tools to a FastMCP server."""
    for name, function in TOOLS:
        mcp.tool(name=name)(function)


__all__ = ["TOOLS", "register", "request_report", "request_review"]
