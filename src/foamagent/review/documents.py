"""The documents a reviewed case carries, and the rounds they are allowed.

Everything the review produces stays in the case directory: the agreed specification, each
round of findings, the author's answer to each, and the final report. A case that has been
run is therefore also a case whose conditions and objections are on disk, which is the
record a CFD result needs and rarely has.

The round limits live here rather than in anyone's instructions. Two rounds per stage is
enough for an objection to be raised and answered; past that the argument stops converging,
and neither the author nor the reviewer is the right party to decide when to stop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from foamagent.case_state import STATE_DIRNAME, increment_case_state_field, load_case_state
from foamagent.locking import case_lock
from foamagent.logger import get_logger

logger = get_logger(__name__)

SPEC_FILE = "spec.md"
REPORT_FILE = "report.md"
REVIEW_PATTERN = "review-{n}.md"
RESPONSE_PATTERN = "response-{n}.md"

# Where a review number is claimed before the real review-<n>.md exists -- deliberately not
# a .md file next to it, so a reservation (a review still computing) is never mistaken by
# unanswered_reviews() for a finding awaiting a response. Under STATE_DIRNAME, alongside
# case_state.py's state.json, rather than a new top-level dotfile of its own.
RESERVED_DIRNAME = f"{STATE_DIRNAME}/reserved-reviews"

SPEC_STAGE = "spec"
RESULT_STAGE = "result"
STAGES = (SPEC_STAGE, RESULT_STAGE)

ROUND_LIMIT = 2


@dataclass(frozen=True)
class RoundState:
    """How many rounds each stage has used."""

    spec: int = 0
    result: int = 0

    def used(self, stage: str) -> int:
        return self.spec if stage == SPEC_STAGE else self.result

    def remaining(self, stage: str) -> int:
        return max(0, ROUND_LIMIT - self.used(stage))


def spec_path(case_dir: str | Path) -> Path:
    return Path(case_dir) / SPEC_FILE


def report_path(case_dir: str | Path) -> Path:
    return Path(case_dir) / REPORT_FILE


def review_path(case_dir: str | Path, number: int) -> Path:
    return Path(case_dir) / REVIEW_PATTERN.format(n=number)


def response_path(case_dir: str | Path, number: int) -> Path:
    return Path(case_dir) / RESPONSE_PATTERN.format(n=number)


def _numbers(case_dir: str | Path, pattern: str) -> List[int]:
    regex = re.compile("^" + re.escape(pattern).replace(r"\{n\}", r"(\d+)") + "$")
    found = []
    for path in Path(case_dir).glob("*.md"):
        match = regex.match(path.name)
        if match:
            found.append(int(match.group(1)))
    return sorted(found)


def existing_reviews(case_dir: str | Path) -> List[int]:
    """The numbers of the review documents already written for this case."""
    return _numbers(case_dir, REVIEW_PATTERN)


def existing_responses(case_dir: str | Path) -> List[int]:
    """The numbers of the response documents already written for this case."""
    return _numbers(case_dir, RESPONSE_PATTERN)


def _reserved_reviews(case_dir: str | Path) -> List[int]:
    """Numbers claimed by `reserve_review_number` for a review still computing -- not yet a
    real review-<n>.md, so not returned by `existing_reviews`."""
    directory = Path(case_dir) / RESERVED_DIRNAME
    if not directory.is_dir():
        return []
    return sorted(int(p.name) for p in directory.iterdir() if p.name.isdigit())


def next_review_number(case_dir: str | Path) -> int:
    """The number the next review document gets.

    One sequence across both stages, so the documents read in the order the argument
    happened. Which stage a document belongs to is stated in the document itself. Includes
    numbers `reserve_review_number` has claimed but not yet written, so a caller computing
    this while an earlier reservation is still in flight does not pick the same number.
    """
    numbers = existing_reviews(case_dir) + _reserved_reviews(case_dir)
    return (max(numbers) + 1) if numbers else 1


def reserve_review_number(case_dir: str | Path) -> int:
    """Claim the next review number before the review that will use it has even started.

    Reading the current number and marking it taken happen inside one `case_lock`, held
    here rather than left to the caller: two callers racing on the same case_dir (the spec
    and result stages, which share this one number sequence) must not both read the same
    starting count before either marks anything taken. Pair with `release_reservation` once
    the real review-<n>.md has been written (or the attempt has failed) -- not required for
    correctness (the real document then makes `existing_reviews` cover the number on its
    own), only to keep RESERVED_DIRNAME from accumulating stale entries.
    """
    with case_lock(case_dir, blocking=True):
        number = next_review_number(case_dir)
        marker_dir = Path(case_dir) / RESERVED_DIRNAME
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / str(number)).touch()
        return number


def release_reservation(case_dir: str | Path, number: int) -> None:
    """Clean up a reservation `reserve_review_number` made, once it is no longer needed."""
    (Path(case_dir) / RESERVED_DIRNAME / str(number)).unlink(missing_ok=True)


def rounds(case_dir: str | Path) -> RoundState:
    """How many review rounds this case has spent, per stage."""
    state = load_case_state(case_dir)
    if state is None:
        return RoundState()
    return RoundState(spec=state.spec_review_rounds, result=state.result_review_rounds)


def record_round(case_dir: str | Path, stage: str) -> RoundState:
    """Count one completed review round against ``stage``, atomically.

    Reading the current count and writing back `+1` happen as one step
    (`increment_case_state_field`), not two -- read here, then a separate
    `update_case_state` call with the computed value, is exactly the shape that let two
    concurrent calls (the `spec` and `result` stages, called independently) both read the
    same starting count and each overwrite the other's `+1`.
    """
    field = "spec_review_rounds" if stage == SPEC_STAGE else "result_review_rounds"
    state = increment_case_state_field(case_dir, field)
    return RoundState(spec=state.spec_review_rounds, result=state.result_review_rounds)


def unanswered_reviews(case_dir: str | Path) -> List[int]:
    """Review documents that have no matching response.

    The author's answer is not optional: the report is written by a third party from the
    documents alone, and a finding with no answer beside it reads as a finding nobody
    disputed.
    """
    responses = set(existing_responses(case_dir))
    return [n for n in existing_reviews(case_dir) if n not in responses]


def write_document(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    logger.info("Wrote %s", path)
    return path


def stage_heading(stage: str, number: int) -> str:
    title = "Specification review" if stage == SPEC_STAGE else "Result review"
    return f"<!-- foamagent: {stage} review, document {number} -->\n\n# {title} {number}\n\n"


def missing_spec_message(case_dir: str | Path) -> Optional[str]:
    """Why this case cannot be reviewed yet, or None when it can."""
    path = spec_path(case_dir)
    if not path.is_file():
        return (
            f"There is no {SPEC_FILE} in {case_dir}. Write one first: it must state the "
            "conditions agreed with the user and quote their request verbatim, because "
            "that quotation is what the specification is checked against."
        )
    if not path.read_text(encoding="utf-8").strip():
        return f"{path} is empty."
    return None
