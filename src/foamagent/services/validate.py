"""Checking a case before it is run, without a model and without OpenFOAM.

Every check here is one an experienced user makes by eye: are the dictionaries the solver
needs present, does the application exist in this installation, do the patch names in the
field files match the ones the mesh defines. They are the mistakes that cost a full run to
discover, and none of them needs inference to find.

This is not a substitute for `checkMesh` or for the solver's own parsing. It is the pass
that turns "it failed after four minutes" into "0/U names a patch the mesh does not have".
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from foamagent.logger import get_logger

logger = get_logger(__name__)

ERROR = "error"
WARNING = "warning"

REQUIRED_SYSTEM_FILES = ("controlDict", "fvSchemes", "fvSolution")
CONTROLDICT_KEYS = ("application", "endTime", "deltaT", "writeInterval")


@dataclass
class Finding:
    severity: str
    where: str
    message: str

    def describe(self) -> str:
        return f"[{self.severity}] {self.where}: {self.message}"


@dataclass
class ValidationResult:
    findings: List[Finding] = field(default_factory=list)
    patches: List[str] = field(default_factory=list)
    fields: List[str] = field(default_factory=list)
    application: str = ""

    @property
    def ok(self) -> bool:
        return not any(f.severity == ERROR for f in self.findings)

    def describe(self) -> str:
        if not self.findings:
            return "No problems found."
        return "\n".join(f.describe() for f in self.findings)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//.*", "", text)


def _read(path: Path) -> str:
    try:
        return _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return ""


def _entry(text: str, key: str) -> Optional[str]:
    match = re.search(rf"^\s*{re.escape(key)}\s+([^;]+);", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def mesh_patches(case_dir: Path) -> List[str]:
    """Patch names the mesh defines.

    Prefers constant/polyMesh/boundary, which is what the solver reads. Falls back to the
    boundary block of blockMeshDict, so a case can be checked before blockMesh has run --
    which is exactly when checking is useful.
    """
    boundary = case_dir / "constant" / "polyMesh" / "boundary"
    if boundary.is_file():
        text = _read(boundary)
        # The file is a list: a count, then `name { type ...; }` entries.
        body = text.split("(", 1)[-1]
        return [m.group(1) for m in re.finditer(r"^\s*(\w+)\s*$\s*\{", body, re.MULTILINE)]

    block_mesh = case_dir / "system" / "blockMeshDict"
    if not block_mesh.is_file():
        return []

    text = _read(block_mesh)
    match = re.search(r"\bboundary\s*\((.*)\)\s*;", text, re.DOTALL)
    if not match:
        return []
    return [m.group(1) for m in re.finditer(r"^\s*(\w+)\s*$\s*\{", match.group(1), re.MULTILINE)]


def field_patches(text: str) -> List[str]:
    """Patch names a field file assigns a condition to."""
    match = re.search(r"boundaryField\s*\{(.*)\}", text, re.DOTALL)
    if not match:
        return []

    names = []
    depth = 0
    for line in match.group(1).splitlines():
        stripped = line.strip()
        # A patch entry is either a name or a quoted regular expression ("(top|bottom)",
        # ".*"), which may hold any regex character at all.
        if depth == 0 and (re.fullmatch(r"[\w.]+", stripped) or re.fullmatch(r'".*"', stripped)):
            names.append(stripped)
        depth += line.count("{") - line.count("}")
    return names


def validate_case(case_dir: str, *, installed_solvers: Optional[Sequence[str]] = None) -> ValidationResult:
    """Check one case directory. Never raises: everything found is a finding."""
    path = Path(os.path.abspath(case_dir))
    result = ValidationResult()

    if not path.is_dir():
        result.findings.append(Finding(ERROR, str(path), "the case directory does not exist"))
        return result

    for name in REQUIRED_SYSTEM_FILES:
        if not (path / "system" / name).is_file():
            result.findings.append(
                Finding(ERROR, f"system/{name}", "required by every solver, and missing")
            )

    control_dict = _read(path / "system" / "controlDict")
    if control_dict:
        for key in CONTROLDICT_KEYS:
            if _entry(control_dict, key) is None:
                result.findings.append(Finding(ERROR, "system/controlDict", f"no {key} entry"))

        application = _entry(control_dict, "application") or ""
        result.application = application
        if application and installed_solvers and application not in installed_solvers:
            result.findings.append(
                Finding(
                    ERROR,
                    "system/controlDict",
                    f"application {application} is not installed here. "
                    f"Run describe_environment to see what is.",
                )
            )

    zero_dir = path / "0"
    if not zero_dir.is_dir():
        result.findings.append(
            Finding(ERROR, "0/", "no initial conditions directory. "
                    "Some tutorials ship 0.orig/ and copy it in Allrun; do that copy.")
        )
        return result

    patches = mesh_patches(path)
    result.patches = patches

    for entry in sorted(zero_dir.iterdir()):
        if not entry.is_file():
            continue
        result.fields.append(entry.name)
        text = _read(entry)

        if _entry(text, "dimensions") is None:
            result.findings.append(Finding(ERROR, f"0/{entry.name}", "no dimensions entry"))
        if "boundaryField" not in text:
            result.findings.append(Finding(ERROR, f"0/{entry.name}", "no boundaryField block"))
            continue

        if not patches:
            continue

        named = field_patches(text)
        catch_all = any('"' in name or "|" in name or name == ".*" for name in named)
        missing = [p for p in patches if p not in named]
        unknown = [n for n in named if n not in patches and n != "defaultFaces" and '"' not in n]

        if missing and not catch_all:
            result.findings.append(
                Finding(ERROR, f"0/{entry.name}",
                        f"no condition for mesh patch(es): {', '.join(missing)}")
            )
        for name in unknown:
            result.findings.append(
                Finding(ERROR, f"0/{entry.name}",
                        f"condition for {name}, which the mesh does not define")
            )

    return result


def validation_report(case_dir: str, installed_solvers: Optional[Sequence[str]] = None) -> Dict:
    """The result as plain data, for a tool response."""
    result = validate_case(case_dir, installed_solvers=installed_solvers)
    return {
        "ok": result.ok,
        "application": result.application,
        "mesh_patches": result.patches,
        "fields": result.fields,
        "findings": [
            {"severity": f.severity, "where": f.where, "message": f.message}
            for f in result.findings
        ],
    }


__all__ = ["ERROR", "WARNING", "Finding", "ValidationResult", "field_patches", "mesh_patches",
           "validate_case", "validation_report"]
