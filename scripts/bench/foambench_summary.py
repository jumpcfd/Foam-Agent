#!/usr/bin/env python3
"""Put the per-case run records and the evaluator's four reports side by side.

The evaluator writes one CSV per metric and a final row of averages; the runner writes one
JSON per case. Neither can answer "which case cost the time, and did the time buy anything",
which is the question a run of sixteen is asked afterwards. This joins them on the case name
and prints a Markdown table.

Reads only. Nothing here changes a score.

    python scripts/bench/foambench_summary.py ~/foambench --split Advanced
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bench import case_name, find_cases, report_key  # noqa: E402

RECORD = "foamagent-run.json"
SUBMISSION = "foamagent"
# The evaluator names its reports after the split, in lower case.
REPORTS = {
    "success": "{split}_success_report.csv",
    "nmse": "{split}_nmse_report.csv",
    "similarity": "similarity_report_{split}.csv",
}
# 9999 is what nmse_report.py writes when it could not read a case at all, and averaging it
# with real values would be arithmetic on a sentinel.
NMSE_FAILED = 9999.0
NMSE_THRESHOLD = 0.1


def read_report(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """A report, keyed the way the evaluator writes it: scenario and directory number."""
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            (row["Dataset"], row.get("Directory", "1")): row for row in csv.DictReader(handle)
        }


def solver_finished(submission: Path) -> bool | None:
    """Whether a solver log ends in `End`, read from the logs rather than from the record.

    The record is the runner's claim, written when the session exited; the log is the
    evidence, and the two can disagree when a session ends while its own solver is still
    running. Returns None when there is no solver log to read.
    """
    logs = sorted(submission.glob("log.*Foam"))
    if not logs:
        return None
    for log in logs:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) >= 2 and lines[-2].strip() == "End":
            return True
    return False


def number(value: str | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def collect(root: Path, split: str) -> list[dict]:
    lowered = split.lower()
    reports = {
        name: read_report(root / pattern.format(split=lowered))
        for name, pattern in REPORTS.items()
    }

    split_dir = root / "Dataset" / split
    rows = []
    for case_dir in find_cases(split_dir):
        record_file = case_dir / RECORD
        if not record_file.is_file():
            continue
        record = json.loads(record_file.read_text(encoding="utf-8"))
        name = case_name(split_dir, case_dir)
        key = report_key(name)
        nmse = number(reports["nmse"].get(key, {}).get("NMSE"))
        ran = solver_finished(case_dir / SUBMISSION)
        if ran is None:
            ran = record.get("ends_with_End", False)
        rows.append(
            {
                "case": name,
                "model": record.get("model", ""),
                "seconds": record.get("elapsed_seconds"),
                "timed_out": record.get("timed_out", False),
                "ran": ran,
                "times": len(record.get("time_directories", [])),
                "files": len(record.get("files", [])),
                "execution": number(reports["success"].get(key, {}).get("Success")),
                "tree": number(reports["similarity"].get(key, {}).get("TreeScore")),
                "codebleu": number(reports["similarity"].get(key, {}).get("CodeBLEU")),
                "nmse": nmse,
            }
        )
    return rows


def mean(values) -> float | None:
    """The average of what is there, or None when nothing is."""
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def cell(value, digits: int = 4) -> str:
    if value is None:
        return "--"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if value == NMSE_FAILED:
            return "unreadable"
        return f"{value:.{digits}f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def report(rows: list[dict]) -> str:
    lines = [
        "| Case | Minutes | Ran | Times | Files | Execution | Tree | CodeBLEU | NMSE |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        minutes = "--" if row["seconds"] is None else f"{row['seconds'] / 60:.1f}"
        if row["timed_out"]:
            minutes += " (cut)"
        lines.append(
            f"| {row['case']} | {minutes} | {cell(row['ran'])} | {row['times']} | "
            f"{row['files']} | {cell(row['execution'], 0)} | {cell(row['tree'])} | "
            f"{cell(row['codebleu'])} | {cell(row['nmse'])} |"
        )

    seconds = [r["seconds"] for r in rows if r["seconds"] is not None]
    ran = [r for r in rows if r["ran"]]
    usable = [r["nmse"] for r in rows if r["nmse"] is not None and r["nmse"] != NMSE_FAILED]
    close = [value for value in usable if value < NMSE_THRESHOLD]

    lines += [
        "",
        f"- Cases: {len(rows)}; a solver log ended in `End` in {len(ran)}.",
        f"- Harness time: {sum(seconds) / 60:.0f} min total, "
        f"{sum(seconds) / len(seconds) / 60:.1f} min mean, "
        f"{min(seconds) / 60:.1f}--{max(seconds) / 60:.1f} min range."
        if seconds
        else "- Harness time: no records.",
        f"- NMSE readable for {len(usable)}/{len(rows)}; below {NMSE_THRESHOLD} in {len(close)}.",
    ]

    # `Ran` reads the log OpenFOAM wrote; `Execution` reads the copy taken when the session
    # ended. They part company when a solver outlived the session that started it, and that
    # gap is worth naming rather than leaving for a reader to spot in two columns.
    late = [r["case"] for r in rows if r["ran"] and r["execution"] == 0]
    if late:
        lines.append(
            f"- Finished after their session ended, so the evaluator scored them 0: "
            f"{', '.join(late)}."
        )
    models = sorted({r["model"] for r in rows if r["model"]})
    lines.append(f"- Model: {', '.join(models) or 'not recorded'}.")

    # Basic is eleven scenarios perturbed ten ways each, so a hundred and ten rows are only
    # eleven things being measured. Which scenario a failure belongs to is the question the
    # per-case table cannot answer at a glance.
    if any("/" in row["case"] for row in rows):
        lines += ["", "| Scenario | Cases | Ran | Execution | Tree | CodeBLEU | NMSE < 0.1 |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for scenario in sorted({row["case"].split("/")[0] for row in rows}):
            group = [r for r in rows if r["case"].split("/")[0] == scenario]
            lines.append(
                f"| {scenario} | {len(group)} | {sum(1 for r in group if r['ran'])} | "
                f"{cell(mean(r['execution'] for r in group), 2)} | "
                f"{cell(mean(r['tree'] for r in group), 3)} | "
                f"{cell(mean(r['codebleu'] for r in group), 3)} | "
                f"{sum(1 for r in group if r['nmse'] is not None and r['nmse'] < NMSE_THRESHOLD)} |"
            )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path, help="The directory holding Dataset/ and the reports.")
    parser.add_argument("--split", default="Advanced")
    args = parser.parse_args(argv)

    rows = collect(args.root.resolve(), args.split)
    if not rows:
        print(f"No {RECORD} under {args.root}/Dataset/{args.split}", file=sys.stderr)
        return 1
    print(report(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
