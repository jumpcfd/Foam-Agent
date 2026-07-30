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

from foamagent.case_state import load_case_state, update_case_state
from foamagent.logger import get_logger

logger = get_logger(__name__)

SPEC_FILE = "spec.md"
REPORT_FILE = "report.md"
REVIEW_PATTERN = "review-{n}.md"
RESPONSE_PATTERN = "response-{n}.md"

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


def next_review_number(case_dir: str | Path) -> int:
    """The number the next review document gets.

    One sequence across both stages, so the documents read in the order the argument
    happened. Which stage a document belongs to is stated in the document itself.
    """
    numbers = existing_reviews(case_dir)
    return (numbers[-1] + 1) if numbers else 1


def rounds(case_dir: str | Path) -> RoundState:
    """How many review rounds this case has spent, per stage."""
    state = load_case_state(case_dir)
    if state is None:
        return RoundState()
    return RoundState(spec=state.spec_review_rounds, result=state.result_review_rounds)


def record_round(case_dir: str | Path, stage: str) -> RoundState:
    """Count one completed review round against ``stage``."""
    current = rounds(case_dir)
    if stage == SPEC_STAGE:
        update_case_state(case_dir, spec_review_rounds=current.spec + 1)
        return RoundState(spec=current.spec + 1, result=current.result)

    update_case_state(case_dir, result_review_rounds=current.result + 1)
    return RoundState(spec=current.spec, result=current.result + 1)


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
