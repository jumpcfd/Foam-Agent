"""Common command-line adapter for case-local validation checkers.

A case-specific checker owns the CFD judgment. This module only provides the stable command
contract used by ``foamagent.validation.run``: load a reference, call one function, write
``comparison.json``, and return an exit code based on ``agrees``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable, Optional, Sequence

Checker = Callable[[Path, dict], dict]


def _metadata(reference: dict) -> dict:
    """Copy optional human-facing metadata from a reference document."""
    metadata = {}
    for key in ("case", "title"):
        if key in reference:
            metadata[key] = reference[key]
    source = reference.get("source")
    if isinstance(source, dict) and "citation" in source:
        metadata["source"] = source["citation"]
    return metadata


def run_checker(checker: Checker, argv: Optional[Sequence[str]] = None) -> int:
    """Run ``checker`` using the standard case-local checker command contract.

    ``checker`` receives the resolved built-case directory and the parsed reference document.
    It must return a mapping containing a boolean ``agrees`` value; all other values are case
    specific and are written unchanged to ``comparison.json``.
    """
    parser = argparse.ArgumentParser(description="Run a case-local CFD validation checker")
    parser.add_argument("case_dir", type=Path, help="The built case to inspect")
    parser.add_argument("--reference", type=Path, required=True, help="Reference JSON document")
    parser.add_argument("--out", type=Path, default=None, help="Directory for comparison.json")
    args = parser.parse_args(argv)

    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    result = checker(args.case_dir.resolve(), reference)
    if not isinstance(result, dict):
        raise ValueError("The checker must return a JSON object")
    agrees = result.get("agrees")
    if not isinstance(agrees, bool):
        raise ValueError("The checker result must contain a boolean 'agrees'")

    comparison = _metadata(reference)
    comparison.update(result)
    destination = args.out or args.case_dir
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "comparison.json").write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"case": comparison.get("case", ""), "agrees": agrees}, ensure_ascii=False))
    return 0 if agrees else 1


__all__ = ["Checker", "run_checker"]
