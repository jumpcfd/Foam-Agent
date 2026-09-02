"""Unit tests for the FoamBench helper scripts.

They are scripts rather than package code, but two of the things they do encode a quirk of
somebody else's evaluator -- where a log has to be for the run to count, and what the
official unpacker writes that this one must not -- and a quirk nobody can see from the code
is one that gets tidied away.

Nothing here runs a harness, a solver or a container.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

# FoamBench is deliberately not installed into the foamagent package. Make the repository
# root importable so these tests can exercise the checkout-local scripts package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.bench import _bench as bench_module
from scripts.bench import foambench_reference as reference_module
from scripts.bench import foambench_run as run_module
from scripts.bench import foambench_summary as summary_module
from scripts.bench import foambench_unpack as unpack_module


@pytest.fixture(scope="module")
def unpack():
    return unpack_module


@pytest.fixture(scope="module")
def runner():
    return run_module


@pytest.fixture(scope="module")
def reference():
    return reference_module


@pytest.fixture(scope="module")
def summary():
    return summary_module


# ---------------------------------------------------------------------------
# Unpacking
# ---------------------------------------------------------------------------


def test_a_case_becomes_a_request_and_a_reference(unpack, tmp_path):
    payload = {
        "usr_requirement": "Simulate a lid-driven cavity.",
        "Allrun": "#!/bin/sh\nrunApplication blockMesh\n",
        "system/controlDict": "application pisoFoam;\n",
        "0/U": "internalField uniform (0 0 0);\n",
    }

    written = unpack.unpack_case("Cavity_SA", payload, tmp_path)

    case = tmp_path / "Cavity_SA"
    assert written == 3
    assert (case / "usr_requirement.txt").read_text() == "Simulate a lid-driven cavity."
    assert (case / "GT_Files" / "system" / "controlDict").is_file()
    assert (case / "GT_Files" / "0" / "U").is_file()


def test_the_reference_allrun_is_executable(unpack, tmp_path):
    """It is run as ./Allrun, and the JSON carries no file mode."""
    unpack.unpack_case("x", {"Allrun": "#!/bin/sh\n"}, tmp_path)

    import os

    assert os.access(tmp_path / "x" / "GT_Files" / "Allrun", os.X_OK)


def test_no_credentials_file_is_written(unpack, tmp_path):
    """The official unpacker writes an OpenAI key into a YAML beside the case. This must not."""
    unpack.unpack_case("x", {"usr_requirement": "r", "Allrun": "#!/bin/sh\n"}, tmp_path)

    written = {p.name for p in (tmp_path / "x").rglob("*") if p.is_file()}

    assert written == {"usr_requirement.txt", "Allrun"}
    assert not any(name.endswith((".yaml", ".yml")) for name in written)


# ---------------------------------------------------------------------------
# The layout the evaluator needs
# ---------------------------------------------------------------------------


def test_the_logs_are_copied_where_the_evaluator_looks(runner, tmp_path):
    """`execution_report.py` only walks the submission's subdirectories.

    A case laid out the ordinary way -- log.pisoFoam next to system/ -- scores zero for
    execution however well it ran. Measured, not inferred: a byte-for-byte copy of a run
    reference case scored 0 until this copy existed.
    """
    submission = tmp_path / "foamagent"
    (submission / "system").mkdir(parents=True)
    (submission / "log.pisoFoam").write_text("Time = 10\nEnd\n")
    (submission / "log.blockMesh").write_text("End\n")

    copied = runner.copy_logs_for_the_evaluator(submission)

    assert sorted(copied) == ["log.blockMesh", "log.pisoFoam"]
    assert (submission / "logs" / "log.pisoFoam").read_text() == "Time = 10\nEnd\n"
    # The originals stay where OpenFOAM put them.
    assert (submission / "log.pisoFoam").is_file()


def test_copying_logs_is_harmless_when_there_are_none(runner, tmp_path):
    submission = tmp_path / "foamagent"
    submission.mkdir()

    assert runner.copy_logs_for_the_evaluator(submission) == []
    assert not (submission / "logs").exists()


@pytest.mark.parametrize("module_name", ["foambench_run", "foambench_reference"])
def test_the_initial_time_is_not_counted_as_a_result(module_name, tmp_path):
    module = importlib.import_module(f"scripts.bench.{module_name}")
    case = tmp_path / "case"
    for name in ("0", "0.5", "10", "constant", "system"):
        (case / name).mkdir(parents=True)

    assert module.time_directories(case) == ["0.5", "10"]


def test_the_benchmark_settings_switch_the_reviews_off(runner):
    """A benchmark run is scored against reference files; nothing reads a review."""
    import yaml

    settings = yaml.safe_load(
        runner.PROJECT_SETTINGS.format(
            runtime="docker", image="i", bashrc="/b", model=runner.DEFAULT_MODEL
        )
    )

    assert settings["review"]["mode"] == "off"
    assert settings["openfoam"]["runtime"] == "docker"


def test_one_model_is_named_for_the_whole_run(runner):
    """A score without a model beside it says nothing, so the model is never left implicit."""
    import yaml

    settings = yaml.safe_load(
        runner.PROJECT_SETTINGS.format(
            runtime="docker", image="i", bashrc="/b", model="claude-sonnet-5"
        )
    )

    # The session that writes the case and the review that would read it are the same model.
    assert settings["review"]["model"] == "claude-sonnet-5"
    assert runner.DEFAULT_MODEL == "claude-sonnet-5"


def test_the_session_builds_where_no_reference_can_be_stumbled_on(runner, tmp_path):
    """The reference must not be on any path out of the directory the session works in.

    Measured, not feared: with the submission at `Dataset/Advanced/<case>/foamagent`, the
    answer sat at `../GT_Files` and two sessions in sixteen read it and said so in their own
    notes. A directory a session can list is a directory it will list.
    """
    split = tmp_path / "foambench" / "Dataset" / "Advanced"
    split.mkdir(parents=True)

    work = runner.work_root_beside(split)

    assert work == tmp_path / "foambench-work"
    # No ancestor of a workspace is an ancestor of the dataset, bar the two of them.
    assert split.parent.parent not in work.parents and work not in split.parents


def test_the_finished_case_is_copied_back_for_the_evaluator(runner, tmp_path, monkeypatch):
    """Built away from the dataset, scored inside it: the copy is what joins the two."""
    case_dir = tmp_path / "Dataset" / "Advanced" / "Cavity_SA"
    case_dir.mkdir(parents=True)
    (case_dir / "GT_Files" / "system").mkdir(parents=True)
    (case_dir / runner.REQUIREMENT_FILE).write_text("Simulate a cavity.")
    work_root = tmp_path / "work"

    workspace = work_root / "Cavity_SA" / runner.SUBMISSION

    def session(argv, **kwargs):
        # What the harness would have written, in the directory the prompt named.
        assert str(workspace) in argv[-1]
        (workspace / "system").mkdir(parents=True)
        (workspace / "log.icoFoam").write_text("ExecutionTime = 1 s\n\nEnd\n\n")
        return subprocess.CompletedProcess(argv, 0, "done", "")

    monkeypatch.setattr(runner.subprocess, "run", session)

    record = runner.run_case(case_dir, harness_dir=tmp_path, work_root=work_root,
                             harness="claude", model="m", timeout=10, force=False)

    assert workspace.is_dir(), "the session builds in the workspace"
    assert str(workspace) in record["prompt"], "and is told that path and no other"
    assert "GT_Files" not in record["prompt"]
    # The evaluator reads the copy, logs and all.
    assert (case_dir / runner.SUBMISSION / "logs" / "log.icoFoam").is_file()
    assert record["ends_with_End"] is True


def test_a_broken_subprocess_fails_the_case_not_the_batch(runner, tmp_path, monkeypatch):
    """Regression: only subprocess.TimeoutExpired was caught -- any other exception (the
    harness binary disappearing mid-run, a FileNotFoundError) propagated out of run_case,
    and under --jobs 1 (`records = [one(case) for case in cases]`) took every case after
    this one down with it."""
    case_dir = tmp_path / "Dataset" / "Basic" / "Cavity"
    case_dir.mkdir(parents=True)
    (case_dir / runner.REQUIREMENT_FILE).write_text("Simulate a cavity.")
    work_root = tmp_path / "work"

    def broken(argv, **kwargs):
        raise FileNotFoundError("claude: command not found")

    monkeypatch.setattr(runner.subprocess, "run", broken)

    record = runner.run_case(case_dir, harness_dir=tmp_path, work_root=work_root,
                             harness="claude", model="m", timeout=10, force=False)

    assert "error" in record
    assert "FileNotFoundError" in record["error"]
    # Shaped enough for main()'s summary (sums elapsed_seconds, counts ends_with_End) to
    # not itself raise on this record.
    assert record["elapsed_seconds"] == 0
    assert record["ends_with_End"] is False


def test_the_request_is_passed_word_for_word(runner):
    """Only where the case goes, and that nobody is there to answer, may be added."""
    added = runner.INSTRUCTIONS.format(case_dir="/somewhere")

    assert "/somewhere" in added
    for word in ("solver", "mesh", "boundary", "turbulence", "viscosity"):
        assert word not in added.lower()


# ---------------------------------------------------------------------------
# Finding the cases in a split
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bench():
    return bench_module


def test_both_splits_are_walked_however_deep_they_nest(bench, tmp_path):
    """Advanced is `<split>/<case>`; Basic is `<split>/<scenario>/<1..10>`.

    Listing a split's subdirectories therefore finds sixteen cases in one and eleven
    scenarios in the other, which would have run a tenth of the basic split and reported it
    as all of it.
    """
    advanced, basic = tmp_path / "Advanced", tmp_path / "Basic"
    for case in ("Cavity_SA", "wedge_SA"):
        (advanced / case).mkdir(parents=True)
        (advanced / case / "usr_requirement.txt").write_text("r")
    for index in (1, 7):
        (basic / "obliqueShock" / str(index)).mkdir(parents=True)
        (basic / "obliqueShock" / str(index) / "usr_requirement.txt").write_text("r")

    assert [bench.case_name(advanced, c) for c in bench.find_cases(advanced)] == [
        "Cavity_SA", "wedge_SA"]
    assert [bench.case_name(basic, c) for c in bench.find_cases(basic)] == [
        "obliqueShock/1", "obliqueShock/7"]


def test_naming_a_scenario_selects_its_whole_family(bench, tmp_path):
    """`--case obliqueShock` is the useful request; naming ten directories is not."""
    split = tmp_path / "Basic"
    for index in (1, 2):
        (split / "obliqueShock" / str(index)).mkdir(parents=True)
        (split / "obliqueShock" / str(index) / "usr_requirement.txt").write_text("r")
    (split / "wedge" / "1").mkdir(parents=True)
    (split / "wedge" / "1" / "usr_requirement.txt").write_text("r")
    cases = bench.find_cases(split)

    chosen, missing = bench.select(split, cases, ["obliqueShock"])
    assert [bench.case_name(split, c) for c in chosen] == ["obliqueShock/1", "obliqueShock/2"]
    assert missing == set()

    _, missing = bench.select(split, cases, ["oblique_shock"])
    assert missing == {"oblique_shock"}, "a misspelling must be complained about, not ignored"


def test_the_report_key_matches_what_the_evaluator_writes(bench):
    """It writes `Cavity_SA,1` for an advanced case and `obliqueShock,7` for a basic one."""
    assert bench.report_key("Cavity_SA") == ("Cavity_SA", "1")
    assert bench.report_key("obliqueShock/7") == ("obliqueShock", "7")


# ---------------------------------------------------------------------------
# Reading the run back
# ---------------------------------------------------------------------------


def build_run(root: Path, split: str = "Advanced") -> Path:
    """A minimal finished run: two cases, one scored, one the evaluator could not read."""
    for name in ("Good", "Bad"):
        (root / "Dataset" / split / name).mkdir(parents=True)
        (root / "Dataset" / split / name / "usr_requirement.txt").write_text("r")

    import json

    (root / "Dataset" / split / "Good" / "foamagent-run.json").write_text(json.dumps({
        "case": "Good", "model": "claude-sonnet-5", "elapsed_seconds": 300.0,
        "timed_out": False, "ends_with_End": True,
        "time_directories": ["0.5", "1"], "files": ["system/controlDict"],
    }))
    (root / "Dataset" / split / "Bad" / "foamagent-run.json").write_text(json.dumps({
        "case": "Bad", "model": "claude-sonnet-5", "elapsed_seconds": 900.0,
        "timed_out": True, "ends_with_End": False,
        "time_directories": [], "files": [],
    }))

    (root / "advanced_success_report.csv").write_text(
        "Dataset,Directory,Success\nGood,1,1\nBad,1,0\n")
    (root / "advanced_nmse_report.csv").write_text(
        "Dataset,Directory,NMSE\nGood,1,0.07\nBad,1,9999.0\n")
    (root / "similarity_report_advanced.csv").write_text(
        "Dataset,Directory,CodeBLEU,TreeScore\nGood,1,0.9377,1.0\nBad,1,0.0,0.0\n")
    return root


def test_the_time_and_the_score_are_joined_per_case(summary, tmp_path):
    rows = {row["case"]: row for row in summary.collect(build_run(tmp_path), "Advanced")}

    assert rows["Good"]["seconds"] == 300.0
    assert rows["Good"]["execution"] == 1.0
    assert rows["Good"]["codebleu"] == 0.9377
    assert rows["Bad"]["timed_out"] is True


def test_the_unreadable_sentinel_is_never_averaged(summary, tmp_path):
    """nmse_report.py writes 9999 for a case it could not open; a mean over that is fiction."""
    text = summary.report(summary.collect(build_run(tmp_path), "Advanced"))

    assert "unreadable" in text
    assert "9999" not in text
    assert "NMSE readable for 1/2" in text


def test_a_run_with_no_reports_still_reports_the_time(summary, tmp_path):
    """The timings exist as soon as the harness has run; the scoring comes later."""
    build_run(tmp_path)
    for report in tmp_path.glob("*.csv"):
        report.unlink()

    text = summary.report(summary.collect(tmp_path, "Advanced"))

    assert "20 min total" in text
    assert "NMSE readable for 0/2" in text


def test_a_basic_case_joins_on_its_scenario_and_number(summary, tmp_path):
    """`obliqueShock/7` is one row of the CSV, written as `obliqueShock,7`."""
    import json

    case = tmp_path / "Dataset" / "Basic" / "obliqueShock" / "7"
    case.mkdir(parents=True)
    (case / "usr_requirement.txt").write_text("r")
    (case / "foamagent-run.json").write_text(json.dumps({
        "case": "obliqueShock/7", "model": "claude-sonnet-5", "elapsed_seconds": 120.0,
        "timed_out": False, "ends_with_End": True, "time_directories": ["1"], "files": [],
    }))
    (tmp_path / "basic_success_report.csv").write_text(
        "Dataset,Directory,Success\nobliqueShock,6,0\nobliqueShock,7,1\n")

    rows = summary.collect(tmp_path, "Basic")

    assert [r["case"] for r in rows] == ["obliqueShock/7"]
    # Row 6 of the same scenario scored 0; picking it would have been the easy mistake.
    assert rows[0]["execution"] == 1.0
    assert "| obliqueShock | 1 |" in summary.report(rows)


def test_a_mesh_log_is_not_a_finished_solver(runner, tmp_path):
    """blockMesh writes `End` too, so "any log says End" answers the wrong question.

    Measured: a session that started pimpleFoam and then ended its turn left a truncated
    solver log beside a complete log.blockMesh, and the old check called it finished.
    """
    submission = tmp_path / "foamagent"
    submission.mkdir()
    # OpenFOAM ends a log with "End\n\n", which is why the evaluator reads the
    # second-to-last line rather than the last. This check reads the same one.
    (submission / "log.blockMesh").write_text("Finalising\n\nEnd\n\n")
    (submission / "log.pimpleFoam").write_text("Time = 0.5\nGAMG: Solving for p\n")

    assert runner.solver_finished(submission) is False

    (submission / "log.pimpleFoam").write_text("ExecutionTime = 5 s\n\nEnd\n\n")
    assert runner.solver_finished(submission) is True


def test_the_summary_reads_the_log_not_the_claim(summary, tmp_path):
    """The record is what the runner said; the log is what happened. They can disagree."""
    build_run(tmp_path)
    submission = tmp_path / "Dataset" / "Advanced" / "Good" / "foamagent"
    submission.mkdir()
    (submission / "log.pisoFoam").write_text("Time = 1\nstill going\n")

    rows = {row["case"]: row for row in summary.collect(tmp_path, "Advanced")}

    # The record for Good says ends_with_End; the log says otherwise, and the log wins.
    assert rows["Good"]["ran"] is False
    # Bad has no submission at all, so its record is all there is to go on.
    assert rows["Bad"]["ran"] is False


def test_cases_run_one_at_a_time_unless_asked_otherwise(runner, tmp_path, monkeypatch, capsys):
    """Serial by default: a per-case elapsed time is only a cost when nothing else is running."""
    split = tmp_path / "Dataset" / "Advanced"
    for name in ("a", "b", "c"):
        (split / name).mkdir(parents=True)
        (split / name / "usr_requirement.txt").write_text("r")

    seen = []
    monkeypatch.setattr(runner, "prepare_harness_dir", lambda directory, model=None: None)
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(runner, "run_case", lambda case, **kw: (
        seen.append((case.name, kw["model"])) or
        {"case": case.name, "elapsed_seconds": 1.0, "ends_with_End": True}
    ))

    assert runner.main([str(split)]) == 0

    assert [name for name, _ in seen] == ["a", "b", "c"]
    assert {model for _, model in seen} == {runner.DEFAULT_MODEL}
    assert "Wall clock" not in capsys.readouterr().out


def test_parallel_runs_every_case_and_says_so(runner, tmp_path, monkeypatch, capsys):
    split = tmp_path / "Dataset" / "Advanced"
    for name in ("a", "b", "c"):
        (split / name).mkdir(parents=True)
        (split / name / "usr_requirement.txt").write_text("r")

    monkeypatch.setattr(runner, "prepare_harness_dir", lambda directory, model=None: None)
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(runner, "run_case", lambda case, **kw: {
        "case": case.name, "elapsed_seconds": 60.0, "ends_with_End": True
    })

    assert runner.main([str(split), "--jobs", "3"]) == 0

    out = capsys.readouterr().out
    assert "3/3 case(s)" in out
    # The two numbers part company as soon as cases overlap, so both are printed.
    assert "Total harness time: 3 min" in out
    assert "Wall clock" in out and "3 at a time" in out
