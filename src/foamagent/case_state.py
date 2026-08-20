"""Per-case state shared by the LangGraph and MCP entry points.

The LangGraph pipeline carries the facts about a case -- its solver, domain, category and
subtask list -- in the GraphState dict that each node hands to the next. The MCP tools have
no such carrier: every tool call arrives independently and knows only its own arguments. So
the `review` tool used to fill those fields with the constants simpleFoam/fluid/tutorial,
which are wrong for every case that is not an incompressible steady-state tutorial.

Writing the facts to `<case_dir>/.foamagent/state.json` gives both entry points one place to
read them from. The file sits inside the case directory so that it travels with the case and
is removed with it; the leading dot keeps it out of the way of OpenFOAM's own tooling.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from foamagent.locking import case_lock
from foamagent.logger import get_logger

logger = get_logger(__name__)

# Bumped when a change to CaseState cannot be absorbed by the tolerant reader below --
# that is, when an existing field changes meaning or type. Adding a field does not need a
# bump, because a missing key already falls back to that field's default.
STATE_VERSION = 1

STATE_DIRNAME = ".foamagent"
STATE_FILENAME = "state.json"

PathLike = Union[str, os.PathLike]


@dataclass
class CaseState:
    """The facts about a case that outlive a single tool call."""

    case_name: str = ""
    case_solver: str = ""
    case_domain: str = ""
    case_category: str = ""
    user_requirement: str = ""
    subtasks: List[Dict[str, str]] = field(default_factory=list)
    loop_count: int = 0
    # Review rounds spent, per stage. Kept here rather than counted from the documents on
    # disk so that deleting a review file cannot buy another round.
    spec_review_rounds: int = 0
    result_review_rounds: int = 0

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"version": STATE_VERSION}
        payload.update(asdict(self))
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaseState":
        """Build a CaseState from a parsed state file.

        Reads tolerantly: unknown keys are dropped and missing keys keep their default, so a
        file written by a newer or older Foam-Agent still yields a usable state instead of an
        exception in the middle of a run.
        """
        if not isinstance(data, dict):
            raise ValueError(f"Case state must be a JSON object, got {type(data).__name__}")

        version = data.get("version")
        if isinstance(version, int) and version > STATE_VERSION:
            logger.warning(
                "Case state was written by a newer Foam-Agent (version %s > %s); "
                "reading the fields this version understands and ignoring the rest.",
                version,
                STATE_VERSION,
            )

        known = {f.name for f in fields(cls)}
        accepted = {key: value for key, value in data.items() if key in known}

        unknown = set(data) - known - {"version"}
        if unknown:
            logger.debug("Ignoring unknown case state keys: %s", sorted(unknown))

        return cls(**accepted)


def state_dir(case_dir: PathLike) -> Path:
    """Return the directory holding Foam-Agent's own files for a case."""
    return Path(case_dir).resolve() / STATE_DIRNAME


def state_path(case_dir: PathLike) -> Path:
    """Return the path of the state file for a case."""
    return state_dir(case_dir) / STATE_FILENAME


def save_case_state(case_dir: PathLike, state: CaseState) -> Path:
    """Write the state for a case, creating the state directory if needed."""
    path = state_path(case_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
    logger.debug("Wrote case state to %s", path)
    return path


def load_case_state(case_dir: PathLike) -> Optional[CaseState]:
    """Read the state for a case.

    Returns None when no state file exists, which is the normal situation for a case created
    before this module existed or by a caller that never wrote one. An unreadable or
    malformed file is also reported as None, with a warning, so that a corrupt file degrades
    the caller to its fallback instead of ending the run.
    """
    path = state_path(case_dir)
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read case state at %s: %s", path, exc)
        return None

    try:
        return CaseState.from_dict(data)
    except (TypeError, ValueError) as exc:
        logger.warning("Case state at %s is not usable: %s", path, exc)
        return None


def update_case_state(case_dir: PathLike, **updates: Any) -> CaseState:
    """Apply field updates to a case's state and write the result.

    The state is read first, so a caller that knows only some of the fields does not erase
    the ones written earlier by another entry point. Read-then-write is held under
    `case_lock` (`blocking=True`: this is a few filesystem operations, not a run, so waiting
    a turn out is cheap), which keeps two concurrent calls from interleaving their writes --
    but not a caller that itself reads the current state, computes a new absolute value
    (`current + 1`, say) and only then calls this: by the time the lock here is taken, that
    read already happened outside it, so two such callers can still both compute the same
    "current + 1". `increment_case_state_field` below is for that case; use it instead of
    this read-outside/write-with-`update_case_state` pattern for a counter.
    """
    known = {f.name for f in fields(CaseState)}
    unknown = set(updates) - known
    if unknown:
        raise TypeError(f"Unknown case state field(s): {', '.join(sorted(unknown))}")

    with case_lock(case_dir, blocking=True):
        state = load_case_state(case_dir) or CaseState()
        for key, value in updates.items():
            setattr(state, key, value)
        save_case_state(case_dir, state)

    return state


def increment_case_state_field(case_dir: PathLike, field: str) -> CaseState:
    """Read one integer field and write it back plus one, as a single atomic step.

    `update_case_state` alone cannot do this safely for a caller that needs the new value to
    depend on the old one: `review/documents.py`'s `record_round`, called independently for
    the `spec` and `result` stages, is exactly such a caller -- two concurrent calls must not
    both read the same starting count and each write back the same `current + 1`, silently
    losing one of the two rounds against `ROUND_LIMIT`. Reading and writing both happen
    inside one `case_lock`, so nothing about the "old value" can change out from under this
    between the read and the write.
    """
    known = {f.name for f in fields(CaseState)}
    if field not in known:
        raise TypeError(f"Unknown case state field: {field}")

    with case_lock(case_dir, blocking=True):
        state = load_case_state(case_dir) or CaseState()
        setattr(state, field, getattr(state, field) + 1)
        save_case_state(case_dir, state)

    return state
