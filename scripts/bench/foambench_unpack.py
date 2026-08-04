#!/usr/bin/env python3
"""Unpack a FoamBench dataset into the layout its evaluator expects.

The benchmark ships one JSON per split, and the official `read_json_advanced.py` writes,
alongside the case, a YAML holding a MetaGPT path, an OpenAI key and a model name. None of
that applies here -- this fork runs no model of its own -- so this writes only the two
things the evaluation actually needs:

    Dataset/<Split>/<case>/usr_requirement.txt   the request, verbatim
    Dataset/<Split>/<case>/GT_Files/...          the reference case, including Allrun

The generated case goes next to those, in a directory of its own. The evaluator takes the
first directory that is not GT_Files as the submission, so there must be exactly one.

    python scripts/bench/foambench_unpack.py ~/foambench/Dataset/FoamBench_advanced.json
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

REQUIREMENT_KEY = "usr_requirement"
REQUIREMENT_FILE = "usr_requirement.txt"
GROUND_TRUTH = "GT_Files"


def unpack_case(name: str, payload: dict, destination: Path) -> int:
    """Write one case. Returns how many reference files it had."""
    case_dir = destination / name
    ground_truth = case_dir / GROUND_TRUTH
    ground_truth.mkdir(parents=True, exist_ok=True)

    written = 0
    for key, content in payload.items():
        if key == REQUIREMENT_KEY:
            (case_dir / REQUIREMENT_FILE).write_text(content, encoding="utf-8")
            continue

        target = ground_truth / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written += 1

        # Allrun is executed by the reference run, so it has to be executable. The JSON
        # carries no file mode.
        if target.name == "Allrun":
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("json_file", type=Path, help="FoamBench_advanced.json or _basic.json")
    parser.add_argument(
        "--destination",
        type=Path,
        default=None,
        help="Where Dataset/<Split> goes (default: <json's directory>/<Split>).",
    )
    parser.add_argument(
        "--split",
        default=None,
        help="Advanced or Basic (default: taken from the file name).",
    )
    args = parser.parse_args(argv)

    if not args.json_file.is_file():
        print(f"No such file: {args.json_file}", file=sys.stderr)
        return 1

    split = args.split or ("Advanced" if "advanced" in args.json_file.name.lower() else "Basic")
    destination = args.destination or (args.json_file.parent / split)

    cases = json.loads(args.json_file.read_text(encoding="utf-8"))
    if not isinstance(cases, dict):
        print(f"{args.json_file} does not hold a mapping of case name to files.", file=sys.stderr)
        return 1

    destination.mkdir(parents=True, exist_ok=True)
    for name, payload in cases.items():
        count = unpack_case(name, payload, destination)
        print(f"  {name}: {count} reference files")

    print(f"{len(cases)} cases into {destination}")
    print(f"Each has {REQUIREMENT_FILE} and {GROUND_TRUTH}{os.sep}; nothing else is written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
