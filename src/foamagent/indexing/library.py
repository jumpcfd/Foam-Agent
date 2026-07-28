"""The reference library: tutorials as files an agent reads, plus an index into them.

Retrieval used to be Foam-Agent's job. It embedded each case's name and directory listing,
picked the nearest one, and pasted that whole case into the prompt. That made sense when the
model was reached through an API and could not open a file. A harness can open files, so the
better shape is the one a person would use: a catalogue you scan, and a directory you read
the interesting parts of.

Three things are written here:

- ``cases/`` -- the tutorials themselves, cleaned, laid out as they are in the installation.
- ``catalog.md`` -- one line per case: what it is, where it is, what was left out of it.
- ``by-solver.md`` -- the same cases grouped by solver, for "what can icoFoam do" questions.

The catalogue is around 20 kB for a full OpenFOAM installation, so an agent can hold all of
it and still choose to read only the case it needs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from foamagent.logger import get_logger

logger = get_logger(__name__)

CASES_SUBDIR = "cases"
COMMANDS_SUBDIR = "commands"
CATALOG_FILE = "catalog.md"
BY_SOLVER_FILE = "by-solver.md"


@dataclass
class LibraryResult:
    case_count: int
    file_count: int
    excluded_count: int
    excluded_bytes: int
    command_count: int
    bytes_written: int

    def describe(self) -> str:
        return (
            f"{self.case_count} cases, {self.file_count} files, "
            f"{self.bytes_written / 1e6:.1f} MB, {self.command_count} command help pages "
            f"({self.excluded_count} files left out, {self.excluded_bytes / 1e6:.1f} MB)"
        )


def _unknown(value: Optional[str]) -> str:
    return value or "unknown"


def _write_case(case: Dict[str, Any], cases_root: Path) -> Tuple[int, int]:
    """Write one case's files. Returns (files written, bytes written)."""
    case_dir = cases_root / case["rel_path"]
    files = written = 0

    allrun = case.get("allrun")
    if allrun and allrun != "None":
        case_dir.mkdir(parents=True, exist_ok=True)
        path = case_dir / "Allrun"
        path.write_text(allrun, encoding="utf-8")
        files += 1
        written += len(allrun.encode("utf-8"))

    for entry in case.get("entries", []):
        folder = entry.get("folder_name") or "."
        target = case_dir if folder in (".", "") else case_dir / folder
        target.mkdir(parents=True, exist_ok=True)
        content = entry.get("content", "")
        (target / entry["file_name"]).write_text(content, encoding="utf-8")
        files += 1
        written += len(content.encode("utf-8"))

    return files, written


def _excluded_summary(case: Dict[str, Any]) -> str:
    """A catalogue cell naming what was left out, so its absence is not a mystery."""
    excluded = case.get("excluded") or []
    if not excluded:
        return "-"

    parts = []
    for item in sorted(excluded, key=lambda e: -e.get("bytes", 0))[:3]:
        size = item.get("bytes", 0)
        size_text = f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{max(1, size // 1024)} kB"
        parts.append(f"{item['file_name']} ({size_text}, {item['reason']})")

    if len(excluded) > 3:
        parts.append(f"+{len(excluded) - 3} more")
    return "; ".join(parts)


def _catalog_text(cases: List[Dict[str, Any]], environment_description: str) -> str:
    rows = []
    for case in sorted(cases, key=lambda c: c["rel_path"]):
        rows.append(
            "| {name} | {solver} | {domain} | {category} | `{path}` | {files} | {excluded} |".format(
                name=case["case_name"],
                solver=_unknown(case.get("solver")),
                domain=_unknown(case.get("domain")),
                category=_unknown(case.get("category")),
                path=f"{CASES_SUBDIR}/{case['rel_path']}",
                files=len(case.get("entries", [])),
                excluded=_excluded_summary(case),
            )
        )

    header = f"""# OpenFOAM tutorial catalogue

Built from {environment_description}. Every case below is a directory under `{CASES_SUBDIR}/`
holding the files of that tutorial, minus geometry, mesh payloads and anything over the size
limit; the "left out" column names what was dropped from each.

Read this table, choose the case closest to what you are building, then open only that
directory. `by-solver.md` groups the same cases by solver.

| case | solver | domain | category | path | files | left out |
|---|---|---|---|---|---:|---|
"""
    return header + "\n".join(rows) + "\n"


def _by_solver_text(cases: List[Dict[str, Any]]) -> str:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for case in cases:
        grouped.setdefault(_unknown(case.get("solver")), []).append(case)

    lines = [
        "# Tutorials by solver",
        "",
        "Which tutorials exist for a given solver. Use this when the solver is already "
        "decided and the question is what a working case for it looks like.",
        "",
    ]
    for solver in sorted(grouped):
        entries = sorted(grouped[solver], key=lambda c: c["rel_path"])
        lines.append(f"## {solver} ({len(entries)})")
        lines.append("")
        for case in entries:
            lines.append(
                f"- {case['case_name']} — {_unknown(case.get('domain'))}"
                f"/{_unknown(case.get('category'))} — `{CASES_SUBDIR}/{case['rel_path']}`"
            )
        lines.append("")
    return "\n".join(lines)


def _split_command_help(command_help: str) -> Iterable[Tuple[str, str]]:
    """Yield (command, help text) from the corpus-format help dump."""
    import re

    pattern = re.compile(
        r"<command_begin><command>(.*?)</command><help_text>(.*?)</help_text></command_end>",
        re.DOTALL,
    )
    for match in pattern.finditer(command_help):
        yield match.group(1).strip(), match.group(2).strip()


def write_library(
    cases: List[Dict[str, Any]],
    destination: Path,
    *,
    environment_description: str,
    command_help: str = "",
) -> LibraryResult:
    """Write the reference library under ``destination``."""
    destination = Path(destination)
    cases_root = destination / CASES_SUBDIR
    cases_root.mkdir(parents=True, exist_ok=True)

    file_count = bytes_written = 0
    for case in cases:
        files, written = _write_case(case, cases_root)
        file_count += files
        bytes_written += written

    catalog = _catalog_text(cases, environment_description)
    (destination / CATALOG_FILE).write_text(catalog, encoding="utf-8")
    (destination / BY_SOLVER_FILE).write_text(_by_solver_text(cases), encoding="utf-8")
    bytes_written += len(catalog.encode("utf-8"))

    command_count = 0
    if command_help:
        commands_root = destination / COMMANDS_SUBDIR
        commands_root.mkdir(parents=True, exist_ok=True)
        for command, help_text in _split_command_help(command_help):
            # A command name comes from a directory listing, so it cannot contain a
            # separator; guard anyway rather than trust the environment with a path.
            safe = command.replace(os.sep, "_").replace("/", "_")
            (commands_root / f"{safe}.txt").write_text(help_text + "\n", encoding="utf-8")
            command_count += 1
            bytes_written += len(help_text) + 1

    excluded = [item for case in cases for item in (case.get("excluded") or [])]
    result = LibraryResult(
        case_count=len(cases),
        file_count=file_count,
        excluded_count=len(excluded),
        excluded_bytes=sum(item.get("bytes", 0) for item in excluded),
        command_count=command_count,
        bytes_written=bytes_written,
    )
    logger.info("Wrote reference library: %s", result.describe())
    return result


def catalog_search(catalog: Path, query: str, *, topk: int = 5) -> List[Dict[str, str]]:
    """Rank catalogue rows by how many of the query's words they contain.

    Deliberately crude. The catalogue is a table a reader can scan in full; this exists for
    clients that cannot open the file, and it should not pretend to judgement it has not
    got.
    """
    import re

    def words(text: str) -> List[str]:
        text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text.replace("_", " ").replace("/", " "))
        return [w for w in re.split(r"[^\w.]+", text.lower()) if w]

    wanted = set(words(query))
    if not wanted or not Path(catalog).is_file():
        return []

    scored = []
    for line in Path(catalog).read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| case ") or set(line) <= set("|- "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        name, solver, domain, category, path = cells[:5]
        score = len(wanted & set(words(" ".join([name, solver, domain, category, path]))))
        if score:
            scored.append(
                (score, {"case": name, "solver": solver, "domain": domain,
                         "category": category, "path": path.strip("`")})
            )

    scored.sort(key=lambda item: -item[0])
    return [row for _, row in scored[:topk]]


def library_paths(index_dir: Path) -> Dict[str, Path]:
    """Where the library lives under a built index."""
    index_dir = Path(index_dir)
    return {
        "catalog": index_dir / CATALOG_FILE,
        "by_solver": index_dir / BY_SOLVER_FILE,
        "cases": index_dir / CASES_SUBDIR,
        "commands": index_dir / COMMANDS_SUBDIR,
    }


__all__ = [
    "BY_SOLVER_FILE",
    "CASES_SUBDIR",
    "CATALOG_FILE",
    "COMMANDS_SUBDIR",
    "LibraryResult",
    "catalog_search",
    "library_paths",
    "write_library",
]
