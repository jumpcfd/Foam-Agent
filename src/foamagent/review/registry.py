"""Starting a review and asking about it later.

`request_review`/`request_report` used to block the calling MCP tool for as long as the
review subprocess took -- up to `review.timeout_seconds` (1800s by default). No client's
timeout survives that; `run_start` solved the identical problem for solver runs
(`services/run_async.py`) by returning an id at once and letting the caller poll instead of
waiting inline. This is the same shape for a review: the work runs on a background thread,
and a caller checks on it with `review_status`/`report_status`.

State lives in this process, since the server outlives any single review, and is mirrored to
`<case_dir>/.foamagent/reviews/<id>.json` so a review that outlived a server restart can
still be identified -- the same trick `RunRegistry` plays for solver runs.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from foamagent.logger import get_logger

logger = get_logger(__name__)

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"

REVIEWS_SUBDIR = os.path.join(".foamagent", "reviews")


@dataclass
class ReviewRecord:
    """One `request_review`/`request_report` call.

    `text`, `document`, `round`, `rounds_left`, `respond_to` and `warnings` are unused until
    the work finishes -- what `review_status`/`report_status` fill in from a running record's
    ``detail`` is a "still going" message, not these.
    """

    review_id: str
    case_dir: str
    task: str
    state: str = RUNNING
    started_at: float = 0.0
    finished_at: Optional[float] = None
    detail: str = ""
    text: str = ""
    document: str = ""
    round: int = 0
    rounds_left: int = 0
    respond_to: str = ""
    warnings: List[str] = field(default_factory=list)
    available: bool = True

    @property
    def seconds(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    @property
    def done(self) -> bool:
        return self.state != RUNNING

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["seconds"] = round(self.seconds, 1)
        return data


class ReviewRegistry:
    """The reviews this process knows about."""

    def __init__(self) -> None:
        self._records: Dict[str, ReviewRecord] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(self, case_dir: str, task: str, work: Callable[[], dict]) -> ReviewRecord:
        """Run ``work`` in the background and return at once.

        ``work`` takes no arguments, runs on a daemon thread, and returns a dict of the
        `ReviewRecord` fields to fill in once it finishes (at least ``state``; typically
        ``text``, ``document`` and whatever else the task produced). It must not raise for
        an ordinary failure -- catch what needs reporting and return ``state=FAILED`` with a
        ``detail``, the same as `run_audit` returns a failed `ChannelResult` rather than
        raising; a raised exception is still handled (logged, recorded as failed), but reads
        as this registry's own bug, not the review's.

        A second call for the same ``(case_dir, task)`` while one is still running returns
        the record already in flight instead of starting a duplicate subprocess.
        """
        case_dir = os.path.abspath(case_dir)

        existing = self.latest(case_dir, task)
        if existing is not None and not existing.done:
            return existing

        review_id = uuid.uuid4().hex[:12]
        record = ReviewRecord(
            review_id=review_id, case_dir=case_dir, task=task, started_at=time.time()
        )

        with self._lock:
            self._records[review_id] = record
        self._persist(record)

        thread = threading.Thread(
            target=self._execute,
            args=(record, work),
            name=f"foamagent-review-{review_id}",
            daemon=True,
        )
        with self._lock:
            self._threads[review_id] = thread
        thread.start()

        logger.info("Started %s review %s for %s", task, review_id, case_dir)
        return record

    def _execute(self, record: ReviewRecord, work: Callable[[], dict]) -> None:
        try:
            fields = dict(work())
        except Exception as exc:  # a review must never take the server down with it
            logger.exception("Review %s failed to execute", record.review_id)
            fields = {"state": FAILED, "detail": f"{type(exc).__name__}: {exc}"}

        state = fields.pop("state", SUCCEEDED)
        with self._lock:
            for key, value in fields.items():
                setattr(record, key, value)
            record.state = state
            record.finished_at = time.time()
        self._persist(record)
        logger.info("Review %s %s after %.0fs", record.review_id, record.state, record.seconds)

    # -- asking --------------------------------------------------------------------

    def get(self, review_id: str) -> Optional[ReviewRecord]:
        with self._lock:
            return self._records.get(review_id)

    def latest(self, case_dir: str, task: str) -> Optional[ReviewRecord]:
        """The most recent review of this task for a case, for a caller that lost the id."""
        case_dir = os.path.abspath(case_dir)
        with self._lock:
            candidates = [
                r for r in self._records.values() if r.case_dir == case_dir and r.task == task
            ]
        if candidates:
            return max(candidates, key=lambda r: r.started_at)

        directory = Path(case_dir) / REVIEWS_SUBDIR
        if not directory.is_dir():
            return None
        records = [self._read(path) for path in directory.glob("*.json")]
        records = [r for r in records if r is not None and r.task == task]
        return max(records, key=lambda r: r.started_at) if records else None

    # -- persistence ---------------------------------------------------------------

    def _path(self, record: ReviewRecord) -> Path:
        return Path(record.case_dir) / REVIEWS_SUBDIR / f"{record.review_id}.json"

    def _persist(self, record: ReviewRecord) -> None:
        try:
            path = self._path(record)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
        except OSError as exc:
            logger.debug("Could not record review %s: %s", record.review_id, exc)

    @staticmethod
    def _read(path: Path) -> Optional[ReviewRecord]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        known = {f for f in ReviewRecord.__dataclass_fields__}
        # ponytail: task/case_dir come straight from the JSON file, not re-derived from
        # where the file actually sits on disk. These records are only ever written by
        # this process (see start()), so nothing untrusted authors them today -- but if a
        # record file is ever copied or hand-edited, its case_dir would no longer match
        # the directory it was found in.
        record = ReviewRecord(**{k: v for k, v in data.items() if k in known})
        # A record left running by a server that exited says nothing about the review.
        if record.state == RUNNING and record.finished_at is None:
            record.state = FAILED
            record.detail = "The server that started this review is no longer running it."
        return record


_registry = ReviewRegistry()


def get_review_registry() -> ReviewRegistry:
    return _registry


def set_review_registry(registry: ReviewRegistry) -> None:
    """Replace the registry. For tests."""
    global _registry
    _registry = registry


__all__ = [
    "FAILED",
    "RUNNING",
    "SUCCEEDED",
    "ReviewRecord",
    "ReviewRegistry",
    "get_review_registry",
    "set_review_registry",
]
