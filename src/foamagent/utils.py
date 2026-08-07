# utils.py
"""What a run has to know about a case directory: its time directories and its logs.

This module once held the LangGraph state, the LLM service and the FAISS loaders. Those
went with the in-process pipeline, and the file-shuffling helpers that outlived them have
gone the same way: a one-line `Path.unlink(missing_ok=True)` reads better at the call site
than a wrapper around it. What is left is the two pieces with judgement in them.
"""
import os
import re
import shutil
from pathlib import Path

from foamagent.logger import get_logger

logger = get_logger(__name__)


def remove_numeric_folders(case_dir: str) -> None:
    """Remove a case's written time directories, keeping ``0``.

    A time directory is one whose name parses as a number, decimal point and all. Anything
    else in the case -- ``constant``, ``system``, ``postProcessing`` -- is left alone, and
    so is ``0``, which holds the initial conditions rather than a result.
    """
    for item in Path(case_dir).iterdir():
        if not item.is_dir() or item.name == "0":
            continue
        try:
            float(item.name)
        except ValueError:
            continue  # not a time directory
        try:
            shutil.rmtree(item)
            logger.info("Removed time directory %s", item)
        except OSError as exc:
            logger.error("Could not remove %s: %s", item, exc)


def check_foam_errors(directory: str) -> list:
    """Check OpenFOAM log files for errors.

    Tier 1 (existing): Match explicit ``ERROR:`` lines.
    Tier 2 (safety-net): If no explicit error is found, verify that **every**
    log file contains the ``End`` marker that OpenFOAM prints on successful
    completion.  Any log missing ``End`` is reported with the last 30 lines
    as error context so the caller can diagnose the crash.
    """
    error_logs = []
    log_contents = {}  # filename -> content

    # DOTALL mode allows '.' to match newline characters
    pattern = re.compile(r"ERROR:(.*)", re.DOTALL)

    for file in os.listdir(directory):
        if file.startswith("log"):
            filepath = os.path.join(directory, file)
            try:
                with open(filepath, 'r') as f:
                    content = f.read()
            except (IOError, OSError):
                error_logs.append({"file": file, "error_content": f"Could not read log file: {filepath}"})
                continue

            log_contents[file] = content

            match = pattern.search(content)
            if match:
                error_content = match.group(0).strip()
                error_logs.append({"file": file, "error_content": error_content})
            elif "error" in content.lower():
                logger.warning(f"Warning: file {file} contains 'error' but does not match expected format.")

    # Safety-net: if no explicit ERROR was found, check for missing 'End' marker
    # Check EACH log individually – a successful blockMesh should not mask a
    # crashed solver (e.g. pimpleFoam).
    if not error_logs and log_contents:
        end_pattern = re.compile(r"^\s*End\s*$", re.MULTILINE)

        for file, content in log_contents.items():
            if not end_pattern.search(content):
                last_lines = "\n".join(content.strip().split("\n")[-30:])
                error_logs.append({
                    "file": file,
                    "error_content": (
                        f"Solver did not complete (no 'End' marker found). "
                        f"Last 30 lines:\n{last_lines}"
                    ),
                })

    return error_logs
