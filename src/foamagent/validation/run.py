#!/usr/bin/env python3
"""Produce the validation cases: one harness session per case, with the reviews on.

This is not the benchmark runner. The benchmark switches the reviews off because no metric
reads them; here they are the point. Each session writes a spec, has it reviewed before
building anything, builds and runs the case, has the result reviewed, answers both, and
writes a report -- which is the way the fork is meant to be used.

The session builds in `~/foamagent-validation/<case>/`, outside this repository, because
the published answer the case will be checked against lives in the repository. Afterwards
the case's inputs and the documents the session produced are copied into
`examples/validation/<case>/result/`; the mesh and the fields are not, since `Allrun`
regenerates them. The comparison against the published answer (`foamagent.validation.check`)
runs against the workspace before the mesh is out of reach, and its output
(`comparison.json`, and `profile.csv` where there is one) is written straight into
`result/` -- checking after the mesh is gone is what `python -m foamagent.validation.check
<case>` alone cannot do.

    python -m foamagent.validation.run                     # all of them, under examples/validation
    python -m foamagent.validation.run --case cavity_re100
    python -m foamagent.validation.run --cases-dir /path/to/private/cases
    python -m foamagent.validation.run --case naca0012_re6e6 --timeout 7200  # bound it

A case whose comparison is not one of `foamagent.validation.check`'s three kinds can supply
its own `check.py` beside `request.md` and `reference.json`. It is run the same way the
built-in checker is: positional argument the built case directory, `--reference` the
`reference.json` to check against, `--out` the directory to write into; it must write
`comparison.json` there with an `agrees` boolean and exit 0 if `agrees` else 1. See
`foamagent.validation.check`'s module docstring for the functions such a script may import.

`comparison.json` may also carry an optional `caveats: [str]` list -- plain-English things
worth checking before trusting (or dismissing) the `agrees` verdict, e.g. a condition that
failed on the specific quantity a checker hardcodes while a better-behaved quantity the
session justified instead would have passed. Nothing programmatic reads this list; it exists
because a bare boolean loses exactly the nuance a human deciding what to do with a result
needs. `run.py` prints each one after the summary line so it doesn't require opening the JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from foamagent.locking import OWNED_DIRS_ENV, case_lock, owned_dirs_env

# This file lives at src/foamagent/validation/run.py; parents[3] is the repository root.
# A caller outside this repository (a private problem set, for instance) passes --cases-dir
# instead of relying on this default.
DEFAULT_CASES_DIR = Path(__file__).resolve().parents[3] / "examples" / "validation"
REQUEST = "request.md"
RESULT = "result"
RECORD = "session.json"
REFERENCE = "reference.json"

DEFAULT_WORKSPACE = Path.home() / "foamagent-validation"
DEFAULT_MODEL = "claude-sonnet-5"
# No timeout by default (see effective_timeout below: <=0 means "no timeout"). A real case
# hit a 2-hour default mid-fix (reviews done, no report.md, session cut off while addressing
# a real finding) and had to be re-run; a case cut off partway through a review is worse than
# no case. Pass --timeout explicitly for a bound; a genuinely hung/looping session is not
# caught automatically and must be killed by hand.
DEFAULT_TIMEOUT = -1

ALLOWED_TOOLS = "Read,Write,Edit,Glob,Grep,Bash,mcp__foamagent"

# What is copied back. The mesh and the time directories are left behind: they are large,
# they are reproducible from these files, and a repository is not a results archive.
KEEP_DIRS = ("0", "0.orig", "constant", "system")
KEEP_GLOBS = ("*.md", "Allrun", "Allclean", "*.json", "log.*")
SKIP_UNDER_KEPT = ("polyMesh",)
# A solver log for ten thousand timesteps is megabytes of residuals. The tail is the part
# anyone reads -- the last times, the ExecutionTime, whether it ended in End -- so a long
# log is committed from the end, with a line saying what was dropped.
LOG_LINE_LIMIT = 2000

INSTRUCTIONS = (
    "\n\nBuild the OpenFOAM case in {case_dir} (create it; do not make a subdirectory "
    "inside it for the case).\n"
    "Nobody is available to answer questions: assume what you must, record every "
    "assumption in spec.md, and finish the run. Do not end your turn while the solver is "
    "still running -- run_status takes a wait_seconds."
)

PROJECT_SETTINGS = """\
# Written by foamagent.validation.run.
#
# The reviews are on, unlike the benchmark runs: these cases are meant to show the fork
# working the way it is meant to be used, and the reviews are part of that.
review:
  mode: full
  model: {model}
openfoam:
  runtime: {runtime}
  image: {image}
  bashrc: {bashrc}
"""


def prepare_harness_dir(directory: Path, *, model: str) -> None:
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


def copy_log_tail(source: Path, destination: Path) -> None:
    """The whole log if it is short, otherwise its last LOG_LINE_LIMIT lines."""
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if len(lines) <= LOG_LINE_LIMIT:
        destination.write_text("".join(lines), encoding="utf-8")
        return
    dropped = len(lines) - LOG_LINE_LIMIT
    destination.write_text(
        f"[{dropped} earlier lines of this log are not committed; rerun Allrun for them]\n"
        + "".join(lines[-LOG_LINE_LIMIT:]),
        encoding="utf-8",
    )


# Subdirectories `collect()` never treats as a nested case's own contents even though it
# descends through them looking for one -- the session's own bookkeeping, not a case.
NON_CASE_DIRS = (".foamagent", "postProcessing", "review-work")


def _collect_case_files(case: Path, destination: Path) -> list[str]:
    """Copy one case directory's inputs and outputs (no recursion into sub-cases)."""
    destination.mkdir(parents=True, exist_ok=True)

    copied = []
    for name in KEEP_DIRS:
        source = case / name
        if not source.is_dir():
            continue
        shutil.copytree(
            source, destination / name,
            ignore=shutil.ignore_patterns(*SKIP_UNDER_KEPT),
        )
        copied += [str(p.relative_to(destination)) for p in (destination / name).rglob("*")
                   if p.is_file()]

    for pattern in KEEP_GLOBS:
        for source in sorted(case.glob(pattern)):
            if not source.is_file():
                continue
            if source.name.startswith("log."):
                copy_log_tail(source, destination / source.name)
            else:
                shutil.copy2(source, destination / source.name)
            copied.append(source.name)

    forces = case / "postProcessing"
    if forces.is_dir():
        shutil.copytree(forces, destination / "postProcessing")
        copied.append("postProcessing/")
    return sorted(copied)


def _find_nested_cases(root: Path) -> list[Path]:
    """Subdirectories of `root` that are themselves an OpenFOAM case (a `system/controlDict`
    is the marker), found by walking down through directories that are not cases themselves.

    A grid-convergence study or a parameter sweep keeps its sub-cases as subdirectories under
    a plain grouping name (`grid_study/level1`, `alpha_sweep/alpha_0`) that is not a case in
    its own right, so it has to be walked into rather than matched directly. Stops descending
    the moment a case root is found -- nothing inside one case (its own `constant/`, `system/`)
    is itself another nested case.
    """
    found = []
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if child.name in NON_CASE_DIRS:
            continue
        if (child / "system" / "controlDict").is_file():
            found.append(child)
        else:
            found.extend(_find_nested_cases(child))
    return found


def collect(case: Path, destination: Path) -> list[str]:
    """Copy the inputs and the session's documents out of the workspace.

    Includes every nested case (a grid-convergence study's `grid_study/level1`, a sweep's
    `alpha_sweep/alpha_0`, or any other subdirectory the session built as a complete case in
    its own right) -- not just the case built directly in `case` itself. Losing a nested
    case's fields and force history here is not recoverable: `Allrun` regenerates them from
    what a session's *own* copy of the workspace still has, but that workspace is deleted the
    next time this case is run.
    """
    if destination.exists():
        shutil.rmtree(destination)
    copied = _collect_case_files(case, destination)
    for nested in _find_nested_cases(case):
        relative = nested.relative_to(case)
        copied += [str(relative / c) for c in _collect_case_files(nested, destination / relative)]
    return sorted(copied)


def run_comparison(built: Path, case_dir: Path, destination: Path) -> dict | None:
    """Check the case against its published answer while the mesh still exists to read.

    `foamagent.validation.check` needs pyvista and numpy for two of the three comparison
    kinds, and those are the evaluator's dependencies, not this project's -- `uv run --with`
    pulls them in for just this one process rather than adding them here. Run against
    `built`, not `destination`: `collect()` above has already stripped the mesh out of
    `destination` (`Allrun` regenerates it, a repository is not a results archive), so a
    comparison that reads `destination` sees no field data for any case that needs one.

    Invoked by module name, not by file path, so this works the same way whether this
    process is running from a checkout of this repository or from an environment that added
    `foamagent` as a dependency and has no checkout at all.

    A `check.py` beside the case overrides the built-in comparison, called the same way:
    `foamagent.validation.check` covers `profile`, `boundary_layer` and `range`, but a case
    needing a different verdict -- one that recomputes a flow-specific budget, or checks
    convergence across a grid study `built` still holds -- can supply its own script rather
    than growing another kind into the shared one. Its stable API to build on is the
    functions `check.py`'s own module docstring names.
    """
    reference = case_dir / REFERENCE
    if not reference.is_file():
        return None
    checker = case_dir / "check.py"
    command = (
        ["uv", "run", "--with", "numpy", "--with", "pyvista", "python", str(checker)]
        if checker.is_file() else
        ["uv", "run", "--with", "numpy", "--with", "pyvista", "python", "-m",
         "foamagent.validation.check"]
    )
    completed = subprocess.run(
        command + [str(built), "--reference", str(reference), "--out", str(destination)],
        capture_output=True, text=True,
    )
    comparison_file = destination / "comparison.json"
    if not comparison_file.is_file():
        return {"agrees": None, "error": (completed.stdout + completed.stderr)[-2000:]}
    return json.loads(comparison_file.read_text(encoding="utf-8"))


def run_case(case_dir: Path, *, harness_dir: Path, workspace: Path, harness: str,
             model: str, timeout: int) -> dict:
    name = case_dir.name
    request = (case_dir / REQUEST).read_text(encoding="utf-8").strip()
    built = workspace / name

    # Held for the whole build-run-collect cycle, not just the rmtree instant: the hazard
    # this guards against is another session using `built` for its own run *anywhere* during
    # that window, not merely two rmtrees landing at the same moment. See locking.py. The
    # subprocess spawned below is told it already owns `built` (`OWNED_DIRS_ENV`), so its own
    # `run_start` call into this exact directory does not try to acquire this same lock again
    # and deadlock against this very `with` block.
    with case_lock(built):
        if built.exists():
            shutil.rmtree(built)
        built.parent.mkdir(parents=True, exist_ok=True)

        prompt = request + INSTRUCTIONS.format(case_dir=built)
        argv = [harness, "-p", "--model", model, "--allowed-tools", ALLOWED_TOOLS, "--", prompt]
        child_env = dict(os.environ)
        child_env[OWNED_DIRS_ENV] = owned_dirs_env(child_env.get(OWNED_DIRS_ENV, ""), built)

        # timeout <= 0 means "no timeout" -- subprocess.run's own sentinel for that is None,
        # not 0 or a negative number (either would raise or return almost instantly).
        effective_timeout = timeout if timeout > 0 else None
        print(f"  {name}: starting {harness} {model}, reviews on "
              f"(timeout {f'{effective_timeout}s' if effective_timeout else 'disabled'})")
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv, cwd=str(harness_dir), capture_output=True, text=True,
                timeout=effective_timeout, stdin=subprocess.DEVNULL, env=child_env,
            )
            returncode, output, timed_out = completed.returncode, completed.stdout, False
        except subprocess.TimeoutExpired as expired:
            returncode, timed_out = -1, True
            output = expired.stdout if isinstance(expired.stdout, str) else ""
        elapsed = time.monotonic() - started

        record = {
            "case": name,
            "harness": harness,
            "model": model,
            "request_verbatim": request,
            "prompt": prompt,
            "workspace": str(built),
            "elapsed_seconds": round(elapsed, 1),
            "returncode": returncode,
            "timed_out": timed_out,
            "review_mode": "full",
        }

        destination = case_dir / RESULT
        # collect() only creates `destination` as a side effect of copying files out of
        # `built`, and does not run at all when `built` was never created (the session's own
        # first build step never happened, or crashed before writing anything) -- every case
        # this project had run before had a `result/` directory left over from an earlier,
        # successful run, so a brand-new case with no prior run is the first thing to expose
        # this. Guarantee `destination` exists unconditionally so the writes below (which
        # must always happen, precisely because a failed build is the case most worth keeping
        # a record of) cannot themselves crash and silently drop the captured session output.
        destination.mkdir(parents=True, exist_ok=True)
        record["files"] = collect(built, destination) if built.is_dir() else []
        record["reviews"] = sorted(p.name for p in destination.glob("review-*.md"))
        record["responses"] = sorted(p.name for p in destination.glob("response-*.md"))
        record["reported"] = (destination / "report.md").is_file()
        record["comparison"] = run_comparison(built, case_dir, destination) if built.is_dir() else None

        (destination / RECORD).write_text(json.dumps(record, indent=2), encoding="utf-8")
        (destination / "session.log").write_text(output or "", encoding="utf-8")

    agrees = (record["comparison"] or {}).get("agrees")
    comparison_note = "no reference" if agrees is None and not (case_dir / REFERENCE).is_file() \
        else "agrees" if agrees else "check failed" if agrees is None else "does not agree"
    print(
        f"  {name}: {'timed out' if timed_out else f'exit {returncode}'} in {elapsed:.0f}s, "
        f"{len(record['reviews'])} review(s), report: {'yes' if record['reported'] else 'no'}, "
        f"comparison: {comparison_note}"
    )
    for caveat in (record["comparison"] or {}).get("caveats", []):
        print(f"    caveat: {caveat}")
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", action="append", default=None, help="Only this case (repeatable).")
    parser.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR,
                        help="Directory of case subdirectories, each with a "
                             f"{REQUEST} (default: examples/validation in this repository).")
    parser.add_argument("--harness", default="claude")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE,
                        help="Where the sessions build, outside this repository.")
    parser.add_argument("--harness-dir", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Seconds before a session is killed (default {DEFAULT_TIMEOUT}, "
                             "meaning no timeout). Pass a positive value to bound a session -- "
                             "a genuinely hung/looping session is not caught automatically "
                             "with no timeout and must be killed by hand.")
    args = parser.parse_args(argv)

    cases_dir = args.cases_dir
    cases = sorted(p for p in cases_dir.iterdir() if (p / REQUEST).is_file())
    if args.case:
        wanted = set(args.case)
        cases = [p for p in cases if p.name in wanted]
        missing = wanted - {p.name for p in cases}
        if missing:
            print(f"No such case: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1
    if not cases:
        print(f"No cases with a {REQUEST} under {cases_dir}", file=sys.stderr)
        return 1
    if shutil.which(args.harness) is None:
        print(f"The harness {args.harness!r} is not on PATH.", file=sys.stderr)
        return 2

    workspace = args.workspace.resolve()
    harness_dir = args.harness_dir or (workspace / "harness")
    prepare_harness_dir(harness_dir, model=args.model)
    print(f"Harness directory: {harness_dir} (model {args.model}, reviews on)")
    print(f"Workspace: {workspace} (the published answers are not under it)")

    records = [
        run_case(case, harness_dir=harness_dir, workspace=workspace, harness=args.harness,
                 model=args.model, timeout=args.timeout)
        for case in cases
    ]

    total = sum(r["elapsed_seconds"] for r in records)
    reviewed = sum(1 for r in records if r["reviews"])
    print(f"{len(records)} case(s) in {total / 60:.0f} min on {args.model}; "
          f"{reviewed} had at least one review.")
    print(f"Check them: python -m foamagent.validation.check {cases_dir}/<case>/{RESULT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
