#!/usr/bin/env python3
"""Run a FoamBench reference case, so there is something to compare against.

The dataset ships each reference case as its input files only -- `0/`, `constant/`,
`system/` and `Allrun` -- with no results in it. The evaluator's NMSE reads the reference
with PyVista and takes its *last* time, so on an unrun reference that last time is 0 and
every submission is scored against the initial condition. Running the references is a step
the benchmark's own instructions do not mention and cannot be skipped.

This runs `Allrun` through Foam-Agent's execution backend, so the reference is produced by
the same OpenFOAM the submissions are produced by.

    python scripts/bench/foambench_reference.py ~/foambench/Dataset/Advanced --case Cavity_SA
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

GROUND_TRUTH = "GT_Files"
# A reference case of this size is a couple of minutes at most; anything longer means the
# case is not the one the split describes, or the container is not doing what we think.
DEFAULT_TIMEOUT = 1800


def time_directories(case: Path) -> list[str]:
    """The time directories a run left behind, excluding the initial one."""
    found = []
    for entry in case.iterdir():
        if not entry.is_dir():
            continue
        try:
            value = float(entry.name)
        except ValueError:
            continue
        if value > 0:
            found.append(entry.name)
    return sorted(found, key=float)


def run_reference(case_dir: Path, *, timeout: int, force: bool) -> bool:
    from foamagent.config import Config
    from foamagent.execution import backend_for_config

    ground_truth = case_dir / GROUND_TRUTH
    if not (ground_truth / "Allrun").is_file():
        print(f"  {case_dir.name}: no {GROUND_TRUTH}/Allrun; skipped")
        return False

    existing = time_directories(ground_truth)
    if existing and not force:
        print(f"  {case_dir.name}: already run ({len(existing)} time directories); skipped")
        return True
    if existing and force:
        for name in existing:
            shutil.rmtree(ground_truth / name)

    backend = backend_for_config(Config())
    started = time.monotonic()
    result = backend.run(["./Allrun"], str(ground_truth), timeout=timeout)
    elapsed = time.monotonic() - started

    produced = time_directories(ground_truth)
    logs = sorted(p.name for p in ground_truth.glob("log.*"))
    status = "ok" if produced else "no results"
    print(
        f"  {case_dir.name}: {status} in {elapsed:.0f}s, "
        f"{len(produced)} time directories, logs: {', '.join(logs) or 'none'}"
    )
    if not result.ok:
        print(f"    exit {result.returncode}: {(result.stderr or '').strip()[:300]}")
    return bool(produced)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("split_dir", type=Path, help="Dataset/Advanced, for example.")
    parser.add_argument("--case", action="append", default=None, help="Only this case (repeatable).")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--force", action="store_true", help="Re-run a reference already run.")
    args = parser.parse_args(argv)

    if not args.split_dir.is_dir():
        print(f"No such directory: {args.split_dir}", file=sys.stderr)
        return 1

    cases = sorted(p for p in args.split_dir.iterdir() if p.is_dir())
    if args.case:
        wanted = set(args.case)
        cases = [p for p in cases if p.name in wanted]
        missing = wanted - {p.name for p in cases}
        if missing:
            print(f"Not in {args.split_dir}: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1

    print(f"Running {len(cases)} reference case(s) from {args.split_dir}")
    done = sum(run_reference(case, timeout=args.timeout, force=args.force) for case in cases)
    print(f"{done}/{len(cases)} reference cases have results.")
    return 0 if done == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
