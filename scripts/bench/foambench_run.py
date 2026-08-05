#!/usr/bin/env python3
"""Produce FoamBench submissions with this fork, one non-interactive harness session each.

The benchmark's own runner drives MetaOpenFOAM's seven scripts in order. This fork has no
such pipeline: the harness reads the request and uses the MCP tools, so a run here is one
session started in a directory that `foamagent install` has configured.

A session builds its case in a working directory well away from the dataset, and the
finished case is copied into place for scoring afterwards. This is not tidiness. When the
session built its case at `Dataset/<Split>/<case>/foamagent`, the reference solution sat
next to it as `../GT_Files`, and two sessions out of sixteen read it and said so in their
own notes. Nothing was hidden and nothing was cheated: a directory the session can list is
a directory it will list. The measurement was mine to get wrong, and this is where it is
got right.

What it writes, per case:

    ../<root>-work/<case>/foamagent/           where the session builds, no reference in sight
    Dataset/<Split>/<case>/foamagent/          the same case, copied in for the evaluator
    Dataset/<Split>/<case>/foamagent/logs/     a copy of the solver logs (see below)
    Dataset/<Split>/<case>/foamagent-run.json  what was asked, how long it took, what came out

The log copy exists because the evaluator asks two incompatible things of the submission
directory: `execution_report.py` looks for `log.*Foam` in its *subdirectories* only, while
`similarity_report.py` and `nmse_report.py` need `0/`, `constant/` and `system/` at its
root. A case laid out the ordinary way scores zero for execution however well it ran. The
copy satisfies the first without disturbing the second, and the originals stay where
OpenFOAM wrote them.

Reviews are switched off for a benchmark run (review.mode), because two reviews and a
report per case is hours of model time that the score does not read.

    python scripts/bench/foambench_run.py ~/foambench/Dataset/Advanced --case Cavity_SA
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SUBMISSION = "foamagent"
RECORD = "foamagent-run.json"
REQUIREMENT_FILE = "usr_requirement.txt"
LOG_SUBDIR = "logs"
# Beside the benchmark root rather than inside it: `~/foambench` -> `~/foambench-work`. The
# property worth having is that no directory between / and the workspace holds a reference
# case, so listing the way out of your own case never lands on one.
WORK_SUFFIX = "-work"

# Wide on purpose: this session is the agent under test, so it writes files and calls every
# Foam-Agent tool. The review sessions are the ones with a read-only list.
ALLOWED_TOOLS = "Read,Write,Edit,Glob,Grep,Bash,mcp__foamagent"
DEFAULT_TIMEOUT = 3600

# Fixed rather than left to whatever the harness defaults to that week. A benchmark number
# without a model beside it says nothing, so the model is named here, passed on the command
# line, and written into every per-case record.
DEFAULT_MODEL = "claude-sonnet-5"

# Appended to the request, which is otherwise passed word for word. Both sentences are about
# where the work goes and that nobody is there to answer, not about the physics.
INSTRUCTIONS = (
    "\n\nPut the OpenFOAM case in {case_dir} (create it; do not create a subdirectory "
    "inside it for the case).\n"
    "Nobody is available to answer questions: assume what you must, record every assumption "
    "in spec.md, and finish the run."
)

PROJECT_SETTINGS = """\
# Written by scripts/bench/foambench_run.py for a benchmark run.
#
# The reviews are off here: the benchmark scores a submission against reference files, and
# two reviews and a report per case cost hours of model time that no metric reads. This is
# not the default, and a case run this way has had no independent check of any kind.
review:
  mode: 'off'
  # Unread while the mode is off, and here so that a run switched back on uses the model the
  # submissions were produced by rather than a second, unrecorded one.
  model: {model}
# The OpenFOAM the submissions are produced by, written down rather than left in whichever
# shell started the run. `foamagent install` also bakes what it finds in the environment
# into .mcp.json; the two have to say the same thing, or `foamagent doctor` reports them as
# disagreeing and the file silently wins.
openfoam:
  runtime: {runtime}
  image: {image}
  bashrc: {bashrc}
"""


def prepare_harness_dir(directory: Path, *, model: str = DEFAULT_MODEL) -> None:
    """A directory the harness can be started in: MCP configuration, skill, settings.

    The OpenFOAM settings are written into the project file as well, because the benchmark
    should record which OpenFOAM produced its submissions, and because a setting that lives
    only in the environment is one nobody can read back afterwards.
    """
    from foamagent.config import Config
    from foamagent.harness import install

    directory.mkdir(parents=True, exist_ok=True)
    install("claude-code", directory)

    config = Config()
    (directory / "foamagent.yaml").write_text(
        PROJECT_SETTINGS.format(
            runtime=config.openfoam_runtime,
            image=config.openfoam_image,
            bashrc=config.openfoam_bashrc,
            model=model,
        ),
        encoding="utf-8",
    )


def work_root_beside(split_dir: Path) -> Path:
    """Where the sessions build, given `<root>/Dataset/<Split>`: `<root>-work`.

    Not `<root>/work`, which would leave the dataset two directories up from every
    workspace. This way the reference cases are on no path a session has any reason to
    walk. It is not isolation -- an absolute path still reaches them -- but the accident
    that produced the last run's two contaminated cases cannot happen twice.
    """
    root = split_dir.parent.parent
    return root.parent / (root.name + WORK_SUFFIX)


def time_directories(case: Path) -> list[str]:
    found = []
    for entry in case.iterdir():
        if entry.is_dir():
            try:
                if float(entry.name) > 0:
                    found.append(entry.name)
            except ValueError:
                continue
    return sorted(found, key=float)


def solver_finished(submission: Path) -> bool:
    """Did a *solver* run to completion, by the test the evaluator applies?

    `execution_report.py` reads the second-to-last line of each `log.*Foam` and wants `End`.
    Asking instead whether any log at all contains `End` is not the same question and does
    not give the same answer: `log.blockMesh` ends in `End` after a mesh and nothing else, so
    a case whose solver was still running when the session ended still looked finished. That
    is not hypothetical -- it happened, and this is the check that missed it.
    """
    for log in sorted(submission.glob("log.*Foam")):
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) >= 2 and lines[-2].strip() == "End":
            return True
    return False


def copy_logs_for_the_evaluator(submission: Path) -> list[str]:
    """Put a copy of each solver log where `execution_report.py` looks for it."""
    logs = sorted(submission.glob("log.*"))
    if not logs:
        return []

    destination = submission / LOG_SUBDIR
    destination.mkdir(exist_ok=True)
    for log in logs:
        shutil.copy2(log, destination / log.name)
    return [log.name for log in logs]


def run_case(case_dir: Path, *, harness_dir: Path, work_root: Path, harness: str, model: str,
             timeout: int, force: bool) -> dict:
    requirement = (case_dir / REQUIREMENT_FILE).read_text(encoding="utf-8").strip()
    submission = case_dir / SUBMISSION
    workspace = work_root / case_dir.name / SUBMISSION

    if submission.exists():
        if not force:
            print(f"  {case_dir.name}: {SUBMISSION}/ exists; skipped")
            return {"case": case_dir.name, "skipped": True}
        shutil.rmtree(submission)
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.parent.mkdir(parents=True, exist_ok=True)

    prompt = requirement + INSTRUCTIONS.format(case_dir=workspace)
    argv = [harness, "-p", "--model", model, "--allowed-tools", ALLOWED_TOOLS, "--", prompt]

    print(f"  {case_dir.name}: starting {harness} {model} (timeout {timeout}s)")
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(harness_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            # For the reason given in review/channel.py: nothing started here may hold the
            # descriptor another process is talking on.
            stdin=subprocess.DEVNULL,
        )
        returncode, output, timed_out = completed.returncode, completed.stdout, False
    except subprocess.TimeoutExpired as expired:
        returncode, timed_out = -1, True
        output = (expired.stdout or b"").decode("utf-8", "replace") if isinstance(expired.stdout, bytes) else (expired.stdout or "")
    elapsed = time.monotonic() - started

    record = {
        "case": case_dir.name,
        "harness": harness,
        "model": model,
        "prompt": prompt,
        "requirement_verbatim": requirement,
        "workspace": str(workspace),
        "elapsed_seconds": round(elapsed, 1),
        "returncode": returncode,
        "timed_out": timed_out,
        "review_mode": "off",
    }

    # Only now does the case meet the reference, and by then nothing is reading it but the
    # evaluator. The workspace is left where it is: it is the evidence of what was built.
    if workspace.is_dir():
        shutil.copytree(workspace, submission, dirs_exist_ok=True)

    if submission.is_dir():
        record["logs"] = copy_logs_for_the_evaluator(submission)
        record["time_directories"] = time_directories(submission)
        record["files"] = sorted(
            str(p.relative_to(submission)) for p in submission.rglob("*") if p.is_file()
        )
        record["ends_with_End"] = solver_finished(submission)
    else:
        record["logs"] = []
        record["time_directories"] = []
        record["files"] = []
        record["ends_with_End"] = False

    (case_dir / RECORD).write_text(json.dumps(record, indent=2), encoding="utf-8")
    (case_dir / "foamagent-session.log").write_text(output or "", encoding="utf-8")

    print(
        f"  {case_dir.name}: {'timed out' if timed_out else f'exit {returncode}'} "
        f"in {elapsed:.0f}s, {len(record['time_directories'])} time directories, "
        f"logs: {', '.join(record['logs']) or 'none'}"
    )
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("split_dir", type=Path)
    parser.add_argument("--case", action="append", default=None, help="Only this case (repeatable).")
    parser.add_argument("--harness", default="claude")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"The model the harness session runs on (default: {DEFAULT_MODEL}).")
    parser.add_argument("--harness-dir", type=Path, default=None,
                        help="Where the harness is started (default: <split>/../harness).")
    parser.add_argument("--work-dir", type=Path, default=None,
                        help="Where the sessions build their cases, away from the reference "
                             "solutions (default: the benchmark root with '-work' appended).")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--jobs", type=int, default=1, metavar="N",
                        help="Run N cases at a time (default 1). Faster, but a per-case "
                             "elapsed time then includes waiting for its neighbours.")
    parser.add_argument("--force", action="store_true", help="Replace an existing submission.")
    args = parser.parse_args(argv)

    # Absolute from here on: the prompt names the submission directory, and the harness
    # session resolves what it is given against its own working directory, not this one. A
    # relative path here put a whole finished case under the harness directory.
    args.split_dir = args.split_dir.resolve()

    if not args.split_dir.is_dir():
        print(f"No such directory: {args.split_dir}", file=sys.stderr)
        return 1
    if shutil.which(args.harness) is None:
        print(f"The harness {args.harness!r} is not on PATH.", file=sys.stderr)
        return 2

    cases = sorted(p for p in args.split_dir.iterdir() if p.is_dir())
    if args.case:
        wanted = set(args.case)
        cases = [p for p in cases if p.name in wanted]
        missing = wanted - {p.name for p in cases}
        if missing:
            print(f"Not in {args.split_dir}: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1

    harness_dir = args.harness_dir or (args.split_dir.parent.parent / "harness")
    work_root = (args.work_dir or work_root_beside(args.split_dir)).resolve()
    prepare_harness_dir(harness_dir, model=args.model)
    print(f"Harness directory: {harness_dir} (model {args.model}, reviews off)")
    print(f"Work directory: {work_root} (no reference case within reach of it)")

    def one(case: Path) -> dict:
        return run_case(case, harness_dir=harness_dir, work_root=work_root,
                        harness=args.harness, model=args.model,
                        timeout=args.timeout, force=args.force)

    started = time.monotonic()
    if args.jobs > 1:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            records = list(pool.map(one, cases))
    else:
        records = [one(case) for case in cases]
    wall_clock = time.monotonic() - started

    ran = [r for r in records if not r.get("skipped")]
    finished = [r for r in ran if r.get("ends_with_End")]
    total = sum(r["elapsed_seconds"] for r in ran)
    print(f"{len(finished)}/{len(ran)} case(s) produced a solver log ending in End.")
    print(f"Total harness time: {total / 60:.0f} min for {len(ran)} case(s) on {args.model}.")
    if args.jobs > 1:
        # Said separately because the two are no longer the same number, and because a
        # per-case time measured against fifteen neighbours is not the cost of that case.
        print(f"Wall clock: {wall_clock / 60:.0f} min at {args.jobs} at a time.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
