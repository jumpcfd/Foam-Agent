"""Unit tests for the cross-process case-directory lock.

These exercise the primitive directly rather than through run_async/validation/bench, which
each have their own integration tests -- see test_run_async.py's
test_a_second_start_on_the_same_case_dir_while_one_is_running_is_refused for the case that
actually caused real data loss.
"""

from __future__ import annotations

import os

import pytest

from foamagent.locking import CaseDirectoryBusy, CaseLock, LOCK_DIR, case_lock, _lock_path


@pytest.fixture(autouse=True)
def _isolate_lock_dir(tmp_path, monkeypatch):
    """Never touch the real ~/.cache/foamagent/locks/ from a test run."""
    monkeypatch.setattr("foamagent.locking.LOCK_DIR", tmp_path / "locks")


def test_two_locks_on_different_directories_never_contend(tmp_path):
    with case_lock(tmp_path / "a"), case_lock(tmp_path / "b"):
        pass  # both acquired without either raising


def test_a_second_lock_on_the_same_directory_is_refused(tmp_path):
    case_dir = tmp_path / "case"
    with case_lock(case_dir):
        with pytest.raises(CaseDirectoryBusy):
            with case_lock(case_dir):
                pass


def test_the_busy_error_names_the_holder(tmp_path):
    case_dir = tmp_path / "case"
    with case_lock(case_dir):
        with pytest.raises(CaseDirectoryBusy, match=str(os.getpid())):
            with case_lock(case_dir):
                pass


def test_the_lock_is_free_again_after_release(tmp_path):
    case_dir = tmp_path / "case"
    with case_lock(case_dir):
        pass
    with case_lock(case_dir):
        pass  # does not raise: the first lock's release actually freed it


def test_a_relative_and_a_resolved_path_to_the_same_directory_share_one_lock(tmp_path):
    (tmp_path / "case").mkdir()
    absolute = tmp_path / "case"
    relative = tmp_path / "sub" / ".." / "case"

    assert _lock_path(absolute) == _lock_path(relative)


def test_the_lock_survives_the_case_directory_being_deleted_from_under_it(tmp_path):
    """The exact scenario that caused the real incident: one session's rmtree racing a
    second session's use of the same path. The lock must stop the second session before
    either rmtree runs, not merely survive one happening.
    """
    import shutil

    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "marker").write_text("built by the first session", encoding="utf-8")

    with case_lock(case_dir):
        shutil.rmtree(case_dir)  # the first session's own legitimate rebuild step
        with pytest.raises(CaseDirectoryBusy):
            with case_lock(case_dir):
                pass  # a second session must still be refused, even though nothing is left on disk


def test_an_abruptly_closed_lock_releases_like_a_killed_process_would(tmp_path):
    """flock() is tied to the open file description, not to graceful cleanup code running --
    a process that dies via SIGKILL never runs `finally: lock.release()`, but the kernel
    drops the lock the moment its file descriptors close anyway. Simulate that by closing
    the raw fd directly instead of calling release().
    """
    case_dir = tmp_path / "case"
    lock = CaseLock(case_dir)
    lock.acquire()
    os.close(lock._fd)  # what SIGKILL does to every fd; not lock.release()

    with case_lock(case_dir):
        pass  # does not raise: the OS already freed it


def test_blocking_mode_waits_instead_of_raising(tmp_path):
    import threading
    import time

    case_dir = tmp_path / "case"
    first = CaseLock(case_dir)
    first.acquire()

    acquired_second = threading.Event()

    def wait_for_it():
        with case_lock(case_dir, blocking=True):
            acquired_second.set()

    t = threading.Thread(target=wait_for_it, daemon=True)
    t.start()
    time.sleep(0.2)
    assert not acquired_second.is_set()  # still blocked behind the first lock

    first.release()
    assert acquired_second.wait(timeout=5.0)
    t.join(timeout=5.0)
