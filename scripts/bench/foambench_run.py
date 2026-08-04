#!/usr/bin/env python3
"""Produce FoamBench submissions with this fork, one non-interactive harness session each.

The benchmark's own runner drives MetaOpenFOAM's seven scripts in order. This fork has no
such pipeline: the harness reads the request and uses the MCP tools, so a run here is one
session started in a directory that `foamagent install` has configured.

What it writes, per case:

    Dataset/<Split>/<case>/foamagent/          the submission, an ordinary OpenFOAM case
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
from pathlib import Path

SUBMISSION = "foamagent"
RECORD = "foamagent-run.json"
REQUIREMENT_FILE = "usr_requirement.txt"
LOG_SUBDIR = "logs"

# Wide on purpose: this session is the agent under test, so it writes files and calls every
# Foam-Agent tool. The review sessions are the ones with a read-only list.
ALLOWED_TOOLS = "Read,Write,Edit,Glob,Grep,Bash,mcp__foamagent"
DEFAULT_TIMEOUT = 3600

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
# The OpenFOAM the submissions are produced by, written down rather than left in whichever
# shell started the run. `foamagent install` also bakes what it finds in the environment
# into .mcp.json; the two have to say the same thing, or `foamagent doctor` reports them as
# disagreeing and the file silently wins.
openfoam:
  runtime: {runtime}
  image: {image}
  bashrc: {bashrc}
"""


def prepare_harness_dir(directory: Path) -> None:
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
        ),
        encoding="utf-8",
    )


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


def run_case(case_dir: Path, *, harness_dir: Path, harness: str, timeout: int, force: bool) -> dict:
    requirement = (case_dir / REQUIREMENT_FILE).read_text(encoding="utf-8").strip()
    submission = case_dir / SUBMISSION

    if submission.exists():
        if not force:
            print(f"  {case_dir.name}: {SUBMISSION}/ exists; skipped")
            return {"case": case_dir.name, "skipped": True}
        shutil.rmtree(submission)

    prompt = requirement + INSTRUCTIONS.format(case_dir=submission)
    argv = [harness, "-p", "--allowed-tools", ALLOWED_TOOLS, "--", prompt]

    print(f"  {case_dir.name}: starting {harness} (timeout {timeout}s)")
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
        "prompt": prompt,
        "requirement_verbatim": requirement,
        "elapsed_seconds": round(elapsed, 1),
        "returncode": returncode,
        "timed_out": timed_out,
        "review_mode": "off",
    }

    if submission.is_dir():
        record["logs"] = copy_logs_for_the_evaluator(submission)
        record["time_directories"] = time_directories(submission)
        record["files"] = sorted(
            str(p.relative_to(submission)) for p in submission.rglob("*") if p.is_file()
        )
        record["ends_with_End"] = any(
            "\nEnd\n" in (submission / name).read_text(encoding="utf-8", errors="replace")
            for name in record["logs"]
        )
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
    parser.add_argument("--harness-dir", type=Path, default=None,
                        help="Where the harness is started (default: <split>/../harness).")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
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
    prepare_harness_dir(harness_dir)
    print(f"Harness directory: {harness_dir} (reviews off)")

    records = [
        run_case(case, harness_dir=harness_dir, harness=args.harness,
                 timeout=args.timeout, force=args.force)
        for case in cases
    ]

    ran = [r for r in records if not r.get("skipped")]
    finished = [r for r in ran if r.get("ends_with_End")]
    print(f"{len(finished)}/{len(ran)} case(s) produced a solver log ending in End.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
