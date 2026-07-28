"""Reading OpenFOAM's failures without asking a model what they mean.

OpenFOAM reports a small, stable set of failures, and each one names its own cause: a
keyword that is not there, a patch that does not exist, a mesh that was never generated, a
solution that diverged. Matching those shapes is a job for a regular expression, and doing
it here means the agent receives "keyword nu missing from constant/physicalProperties"
rather than eighty lines of stack trace to summarise.

The categories are what a fix has to key on; the excerpt is what a human would read.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from foamagent.logger import get_logger

logger = get_logger(__name__)

# (category, pattern, what to do about it). Order matters: the first match wins, so the
# specific patterns come before the general ones.
PATTERNS = [
    (
        "missing_keyword",
        re.compile(r"keyword (\w+) is undefined in dictionary [\"']?([^\"'\n]+)", re.IGNORECASE),
        "Add the entry to that dictionary.",
    ),
    (
        "missing_mesh",
        re.compile(r"Cannot find file \"?points\"? in directory \"?polyMesh", re.IGNORECASE),
        "The mesh was never written. Run blockMesh (or the mesher the case uses) first.",
    ),
    (
        "missing_file",
        re.compile(r"cannot find file \"?([^\"'\n]+)\"?", re.IGNORECASE),
        "Create the file, or correct the path that refers to it.",
    ),
    (
        "patch_mismatch",
        re.compile(
            r"(?:patch|Patch) ([\w.]+)[^\n]*?(?:not found|does not exist|cannot be found)",
            re.IGNORECASE,
        ),
        "The field files and the mesh disagree on patch names. validate_case lists both.",
    ),
    (
        "duplicate_face",
        re.compile(r"boundary face .*? already belongs to some other patch", re.IGNORECASE),
        "A face is assigned to two patches in blockMeshDict. Remove it from one of them.",
    ),
    (
        "unknown_solver",
        re.compile(r"Unknown (\w+) type (\w+)", re.IGNORECASE),
        "The name is not one this OpenFOAM provides; the message lists the valid ones.",
    ),
    (
        "diverged",
        re.compile(r"(Floating point exception|floating point exception|FOAM FATAL IO ERROR.*nan|solution diverged|Maximum number of iterations exceeded)", re.IGNORECASE),
        "The solution blew up. Reduce the time step or relaxation, or start from upwind schemes.",
    ),
    (
        "dimension_mismatch",
        re.compile(r"dimensions? (?:of|are not) ?[^\n]*(?:do not match|dimensionSet)", re.IGNORECASE),
        "Two quantities have incompatible units. Check the dimensions line of the fields involved.",
    ),
    (
        "command_not_found",
        re.compile(r"(?:command not found|No such file or directory).*?(\w+Foam|blockMesh|\w+Mesh)", re.IGNORECASE),
        "That application is not on PATH in the OpenFOAM environment being used.",
    ),
]

FATAL = re.compile(r"(FOAM FATAL (?:IO )?ERROR|^ERROR:|--> FOAM Warning)", re.MULTILINE)


@dataclass
class Diagnosis:
    log: str
    category: str
    message: str
    hint: str

    def to_dict(self) -> Dict[str, str]:
        return {"log": self.log, "category": self.category, "message": self.message, "hint": self.hint}


def _excerpt(text: str, position: int, *, before: int = 200, after: int = 400) -> str:
    start = max(0, position - before)
    return text[start:position + after].strip()


def classify_text(text: str, *, log_name: str = "") -> List[Diagnosis]:
    """Every failure this log text names, most specific match first."""
    found: List[Diagnosis] = []
    seen = set()

    for category, pattern, hint in PATTERNS:
        for match in pattern.finditer(text):
            message = " ".join(match.group(0).split())
            key = (category, message[:120])
            if key in seen:
                continue
            seen.add(key)
            found.append(
                Diagnosis(log=log_name, category=category, message=message, hint=hint)
            )

    if found:
        return found

    # Nothing matched a known shape, but the log may still have failed. Report the fatal
    # block itself rather than claiming the run was clean.
    fatal = FATAL.search(text)
    if fatal:
        found.append(
            Diagnosis(
                log=log_name,
                category="unrecognised",
                message=_excerpt(text, fatal.start()),
                hint="No known pattern matched. Read the excerpt; the cause is usually in it.",
            )
        )
    return found


def classify_case(case_dir: str, *, logs: Optional[List[str]] = None) -> List[Diagnosis]:
    """Classify the failures in a case directory's logs.

    Reads log.* plus Allrun.err, which is where a failure outside any solver lands.
    """
    directory = Path(os.path.abspath(case_dir))
    if not directory.is_dir():
        return []

    if logs:
        paths = [directory / name for name in logs]
    else:
        paths = sorted(directory.glob("log.*"))
        error_file = directory / "Allrun.err"
        if error_file.is_file():
            paths.append(error_file)

    results: List[Diagnosis] = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        results.extend(classify_text(text, log_name=path.name))
    return results


def diagnosis_report(case_dir: str, logs: Optional[List[str]] = None) -> Dict:
    findings = classify_case(case_dir, logs=logs)
    return {
        "count": len(findings),
        "categories": sorted({f.category for f in findings}),
        "findings": [f.to_dict() for f in findings],
    }


__all__ = ["Diagnosis", "PATTERNS", "classify_case", "classify_text", "diagnosis_report"]
