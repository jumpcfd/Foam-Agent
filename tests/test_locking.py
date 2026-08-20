"""Unit tests for the cross-process case-directory lock.

These exercise the primitive directly rather than through validation/bench, which have
their own integration tests -- two sessions racing on the same case directory is what
actually caused real data loss, on a real validation run, before this existed.
"""

from __future__ import annotations

import os

import pytest

from foamagent.locking import (
    OWNED_DIRS_ENV,
    CaseDirectoryBusy,
    CaseLock,
    LOCK_DIR,
    case_lock,
    owned_dirs_env,
    _lock_path,
)


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


def test_a_process_told_it_already_owns_the_directory_does_not_deadlock_against_itself(
    tmp_path, monkeypatch
):
    """The exact deadlock this exists to prevent: `validation/run.py` holds this lock around
    the whole build-run-collect cycle of a `claude -p` subprocess it spawns, and that
    subprocess's own locking into the same directory (a different OS process, via its own
    MCP server -- e.g. `request_review` taking this same lock) would otherwise try to
    acquire this same lock and block against its own parent forever. The parent sets
    OWNED_DIRS_ENV before spawning the child; a lock attempt on a directory listed there must
    succeed instead of blocking, even while the outer lock is still held.
    """
    case_dir = tmp_path / "case"
    monkeypatch.setenv(OWNED_DIRS_ENV, owned_dirs_env("", case_dir))

    with case_lock(case_dir):  # the parent's lock, held for the whole cycle
        with case_lock(case_dir):  # the child's own locking into the same directory
            pass  # does not raise CaseDirectoryBusy


def test_a_directory_not_listed_as_owned_still_deadlocks_normally(tmp_path, monkeypatch):
    """The bypass above must not become a blanket pass -- only the exact directory named in
    OWNED_DIRS_ENV is exempt; a genuinely different, unrelated invocation on some other
    directory is refused exactly as before."""
    owned = tmp_path / "owned"
    other = tmp_path / "other"
    monkeypatch.setenv(OWNED_DIRS_ENV, owned_dirs_env("", owned))

    with case_lock(other):
        with pytest.raises(CaseDirectoryBusy):
            with case_lock(other):
                pass


def test_a_second_unrelated_invocation_on_the_same_directory_is_still_refused(tmp_path):
    """Without the ownership env var (the normal case for two independent invocations, e.g.
    two harness CLIs both defaulting to the same workspace name), the original protection is
    unchanged."""
    case_dir = tmp_path / "case"

    with case_lock(case_dir):
        with pytest.raises(CaseDirectoryBusy):
            with case_lock(case_dir):
                pass


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
