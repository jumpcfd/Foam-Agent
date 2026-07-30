# utils.py
"""File and log helpers shared by the run services.

This module once held the LangGraph state, the LLM service and the FAISS loaders. Those
went with the in-process pipeline; what remains is the small set of deterministic helpers
the run services still call.
"""
import os
import re
import shutil

from foamagent.execution import get_execution_backend
from foamagent.logger import get_logger

logger = get_logger(__name__)


def save_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    logger.info(f"Saved file at {path}")


def remove_files(directory: str, prefix: str) -> None:
    for file in os.listdir(directory):
        if file.startswith(prefix):
            os.remove(os.path.join(directory, file))
    logger.info(f"Removed files with prefix '{prefix}' in {directory}")


def remove_file(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
        logger.info(f"Removed file {path}")


def remove_numeric_folders(case_dir: str) -> None:
    """
    Remove all folders in case_dir that represent numeric values, including those with decimal points,
    except for the "0" folder.

    Args:
        case_dir (str): The directory path to process
    """
    for item in os.listdir(case_dir):
        item_path = os.path.join(case_dir, item)
        if os.path.isdir(item_path) and item != "0":
            try:
                # Try to convert to float to check if it's a numeric value
                float(item)
                # If conversion succeeds, it's a numeric folder
                try:
                    shutil.rmtree(item_path)
                    logger.info(f"Removed numeric folder: {item_path}")
                except Exception as e:
                    logger.error(f"Error removing folder {item_path}: {str(e)}")
            except ValueError:
                # Not a numeric value, so we keep this folder
                pass


def run_command(script_path: str, out_file: str, err_file: str, working_dir: str, max_time_limit: int) -> None:
    """Execute an OpenFOAM shell script, writing its output to the given files.

    Which OpenFOAM the script sees -- the one on this machine or the one in a container --
    is the execution backend's decision; see foamagent.execution.
    """
    logger.info(f"Executing script {script_path} in {working_dir}")
    os.chmod(script_path, 0o777)

    backend = get_execution_backend()
    result = backend.run(
        ["bash", os.path.abspath(script_path)],
        working_dir,
        timeout=max_time_limit,
    )

    stdout, stderr = result.stdout, result.stderr
    if result.timed_out:
        timeout_message = (
            "OpenFOAM execution took too long. "
            "This case, if set up right, does not require such large execution times.\n"
        )
        stdout = timeout_message + stdout
        stderr = timeout_message + stderr
        logger.info(f"Execution timed out: {script_path}")

    with open(out_file, 'w') as out, open(err_file, 'w') as err:
        out.write(stdout)
        err.write(stderr)

    logger.info(f"Executed script {script_path}")


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
