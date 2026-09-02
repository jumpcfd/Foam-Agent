"""What the three FoamBench scripts both need: finding the cases in a split.

The two splits are not laid out the same way. Advanced puts each case directly under the
split (`Advanced/Cavity_SA`); Basic groups ten perturbations of eleven scenarios into a
directory each (`Basic/obliqueShock/7`), which is what its own JSON keys say and what
`execution_report.py` walks. A script that lists the split's subdirectories therefore finds
sixteen cases in one split and eleven scenarios in the other.

A case is a directory holding `usr_requirement.txt`. That is true of both layouts and of
neither's parents, so it is the test used here.
"""

from __future__ import annotations

from pathlib import Path

REQUIREMENT_FILE = "usr_requirement.txt"
# The submission directory a run leaves in place, and the record beside it -- named once
# here so the runner and the summariser can't drift apart on what to call either.
SUBMISSION = "foamagent"
RECORD = "foamagent-run.json"


def find_cases(split_dir: Path) -> list[Path]:
    """Every case under a split, however deeply the split nests them."""
    return sorted(path.parent for path in split_dir.rglob(REQUIREMENT_FILE))


def time_directories(case: Path) -> list[str]:
    """The time directories a run left behind, excluding the initial one."""
    found = []
    for entry in case.iterdir():
        if entry.is_dir():
            try:
                if float(entry.name) > 0:
                    found.append(entry.name)
            except ValueError:
                continue
    return sorted(found, key=float)


def solver_finished(submission: Path) -> bool | None:
    """Whether a solver log ends in `End`, by the test `execution_report.py` applies.

    It reads the second-to-last line of each `log.*Foam` and wants `End`. Asking instead
    whether any log at all contains `End` is not the same question and does not give the
    same answer: `log.blockMesh` ends in `End` after a mesh and nothing else, so a case
    whose solver was still running when the session ended still looked finished. That is
    not hypothetical -- it happened, and this is the check that missed it.

    Returns None when there is no solver log to read, distinct from False (a log exists but
    does not end in `End`) -- the record is the runner's own claim, written when the session
    exited, and the two can disagree when a session ends while its solver is still running.
    """
    logs = sorted(submission.glob("log.*Foam"))
    if not logs:
        return None
    for log in logs:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) >= 2 and lines[-2].strip() == "End":
            return True
    return False


def case_name(split_dir: Path, case_dir: Path) -> str:
    """What to call a case: `Cavity_SA`, or `obliqueShock/7`.

    The last component alone would name ten cases `7`, which is no name at all in a report
    covering the whole split.
    """
    return case_dir.relative_to(split_dir).as_posix()


def select(split_dir: Path, cases: list[Path], wanted: list[str]) -> tuple[list[Path], set[str]]:
    """Narrow to the named cases. A scenario name selects all ten of its perturbations.

    Returns the cases and whatever was asked for and not found, so the caller can complain
    about a misspelling rather than quietly running nothing.
    """
    chosen, matched = [], set()
    for case in cases:
        name = case_name(split_dir, case)
        for want in wanted:
            if name == want or name.startswith(want + "/"):
                chosen.append(case)
                matched.add(want)
                break
    return chosen, set(wanted) - matched


def report_key(name: str) -> tuple[str, str]:
    """The (Dataset, Directory) pair the evaluator's CSVs are keyed on.

    It writes `Cavity_SA,1` for an advanced case and `obliqueShock,7` for a basic one, so
    the name has to be taken apart the same way to join against it.
    """
    scenario, _, index = name.partition("/")
    return scenario, index or "1"
