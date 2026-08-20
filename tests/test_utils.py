"""Unit tests for the case-directory helpers: time directories and log errors."""

from __future__ import annotations

from pathlib import Path

from foamagent.utils import check_foam_errors, remove_numeric_folders


def test_numeric_time_directories_are_removed(tmp_path):
    (tmp_path / "0").mkdir()
    (tmp_path / "10").mkdir()
    (tmp_path / "1.5").mkdir()
    (tmp_path / "constant").mkdir()

    remove_numeric_folders(str(tmp_path))

    remaining = {p.name for p in tmp_path.iterdir()}
    assert remaining == {"0", "constant"}


def test_non_finite_named_directories_are_not_time_steps(tmp_path):
    """Regression: float("nan"/"inf"/"-inf") all parse without raising, so these directory
    names read as time directories and were removed as if they were solved time steps."""
    for name in ("nan", "inf", "-inf", "+inf", "Infinity"):
        (tmp_path / name).mkdir()

    remove_numeric_folders(str(tmp_path))

    remaining = {p.name for p in tmp_path.iterdir()}
    assert remaining == {"nan", "inf", "-inf", "+inf", "Infinity"}


def test_check_foam_errors_reads_a_non_utf8_log_without_raising(tmp_path):
    """Regression: open() with no encoding uses the platform default, and a stray
    non-UTF-8 byte in a solver log raised UnicodeDecodeError -- a ValueError subclass, not
    caught by the (IOError, OSError) handler around this read."""
    log = tmp_path / "log.icoFoam"
    log.write_bytes(b"Time = 1\n\xff\xfe garbled\nEnd\n")

    errors = check_foam_errors(str(tmp_path))

    assert errors == []


def test_check_foam_errors_reports_a_missing_end_marker(tmp_path):
    (tmp_path / "log.icoFoam").write_text("Time = 1\n", encoding="utf-8")

    errors = check_foam_errors(str(tmp_path))

    assert len(errors) == 1
    assert errors[0]["file"] == "log.icoFoam"
