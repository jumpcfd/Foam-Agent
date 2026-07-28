"""Turn a directory of OpenFOAM tutorials into the raw corpus files.

Moved here from database/script/tutorial_parser.py, which is a repo script and therefore
absent from an installed wheel. `foamagent index build` has to work for someone who
installed the package, so the logic lives in the package and the script now calls in.

The scan is deliberately run over a copy of the tutorials, never the installation itself:
find_cases() writes a missing blockMeshDict into a case's system/ directory when the Allrun
references one from the shared resources, and doing that inside $FOAM_TUTORIALS would edit
the user's OpenFOAM.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from foamagent.logger import get_logger

logger = get_logger(__name__)

RAW_FILENAMES = {
    "allrun": "openfoam_allrun_scripts.txt",
    "structure": "openfoam_tutorials_structure.txt",
    "details": "openfoam_tutorials_details.txt",
    "stats": "openfoam_case_stats.json",
    "commands": "openfoam_commands.txt",
    "command_help": "openfoam_command_help.txt",
}

_EMPTY_STATS = {
    "directories_scanned": 0,
    "directories_with_system": 0,
    "files_total_scanned": 0,
    "files_skipped_encoding": 0,
    "files_skipped_large": 0,
    "files_read_success": 0,
    "allrun_read_success": 0,
    "allrun_read_fail": 0,
}


def _new_stats() -> Dict[str, int]:
    return dict(_EMPTY_STATS)


def read_files_into_dict(base_path, stats=None) -> Tuple[str, List[Dict[str, str]], Dict[str, int]]:
    """Read one tutorial case's files.

    OpenFOAM cases often have nested region subfolders (0/air, constant/porous, ...) which
    may repeat filenames across regions, so folder names are kept relative to the case root
    rather than flattened.
    """
    if stats is None:
        stats = _new_stats()

    entries: List[Dict[str, str]] = []

    allrun_path = os.path.join(base_path, "Allrun")
    allrun_content = "None"

    if os.path.isfile(allrun_path):
        stats["files_total_scanned"] += 1
        try:
            with open(allrun_path, "r") as file_handle:
                allrun_content = file_handle.read()
            stats["allrun_read_success"] += 1
        except UnicodeDecodeError:
            logger.debug("Skipping file due to encoding error: %s", allrun_path)
            stats["files_skipped_encoding"] += 1
            stats["allrun_read_fail"] += 1
        except Exception as exc:
            logger.debug("Error reading file %s: %s", allrun_path, exc)
            stats["allrun_read_fail"] += 1

    for root, _, files in os.walk(base_path):
        for file in files:
            if root == base_path and file == "Allrun":
                continue

            file_path = os.path.join(root, file)
            rel_folder = os.path.relpath(root, base_path)

            # Decomposed meshes and post-processing output are generated artifacts, not
            # case setup, and they are large.
            if rel_folder.startswith("processor") or rel_folder.startswith("postProcessing"):
                continue

            stats["files_total_scanned"] += 1

            try:
                with open(file_path, "r") as file_handle:
                    content = file_handle.read()
                entries.append(
                    {"folder_name": rel_folder, "file_name": file, "content": content}
                )
                stats["files_read_success"] += 1
            except UnicodeDecodeError:
                logger.debug("Skipping file due to encoding error: %s", file_path)
                stats["files_skipped_encoding"] += 1
            except Exception as exc:
                logger.debug("Error reading file %s: %s", file_path, exc)

    return allrun_content, entries, stats


def _classify_case(root: str, root_dir: str) -> Tuple[Any, Any, Any]:
    """Work out solver, category and domain from where a case sits in the tree."""
    solver = category = domain = None

    current_path = os.path.dirname(root)
    found_foam = False

    for level in range(3):
        if (not current_path) or (os.path.basename(current_path) == os.path.basename(root_dir)):
            break

        dir_name = os.path.basename(current_path)
        if dir_name.endswith("Foam"):
            solver = dir_name
            domain = os.path.basename(os.path.dirname(current_path))
            found_foam = True
            break
        elif level == 0:
            category = dir_name

        current_path = os.path.dirname(current_path)

    if not found_foam:
        category = None
        components = os.path.relpath(root, root_dir).split(os.sep)
        if len(components) == 3:
            domain, solver = components[0], components[1]
        elif len(components) == 4:
            domain, solver, category = components[0], components[1], components[2]

    return solver, category, domain


def _materialize_shared_blockmesh(root: str, allrun_content: str, entries: List[Dict[str, str]],
                                  blockmesh_resource_dir: str, case_name: str) -> None:
    """Copy in a blockMeshDict the Allrun pulls from the shared resources directory.

    Cases that say `blockMesh -dict $FOAM_TUTORIALS/resources/blockMesh/<name>` have no
    blockMeshDict of their own, so the indexed case would be missing the file that defines
    its mesh.
    """
    system_dir = os.path.join(root, "system")
    blockmeshdict_path = os.path.join(system_dir, "blockMeshDict")
    if os.path.isfile(blockmeshdict_path) or allrun_content == "None":
        return

    match = re.search(
        r"blockMesh\s+-dict\s+\$FOAM_TUTORIALS/resources/blockMesh/([\w\d_]+)", allrun_content
    )
    if not match:
        return

    source = os.path.join(blockmesh_resource_dir, match.group(1))
    if not os.path.isfile(source):
        logger.debug("Referenced blockMeshDict %s not found for case %s", source, case_name)
        return

    try:
        with open(source, "r") as handle:
            content = handle.read()
        os.makedirs(system_dir, exist_ok=True)
        with open(blockmeshdict_path, "w") as handle:
            handle.write(content)
        entries.append(
            {"folder_name": "system", "file_name": "blockMeshDict", "content": content}
        )
        logger.debug("Copied %s into case %s", source, case_name)
    except Exception as exc:
        logger.warning("Failed to copy %s to %s: %s", source, blockmeshdict_path, exc)


def find_cases(root_dir) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Find every tutorial case under ``root_dir`` and read its files.

    A directory is a case when it contains a `system` folder.
    """
    root_dir = str(root_dir)
    cases: List[Dict[str, Any]] = []
    stats = _new_stats()

    # The shared blockMesh dictionaries live under the tutorials root being scanned. This
    # used to read $FOAM_TUTORIALS, which points at the installation rather than at the
    # copy, so a scan of a copy looked for them in the wrong tree.
    blockmesh_resource_dir = os.path.join(root_dir, "resources", "blockMesh")

    for root, dirs, _files in os.walk(root_dir):
        stats["directories_scanned"] += 1

        if "system" not in dirs:
            continue

        stats["directories_with_system"] += 1

        allrun_content, entries, file_stats = read_files_into_dict(root, stats=_new_stats())
        for key in _EMPTY_STATS:
            if key in file_stats:
                stats[key] += file_stats[key]

        case_name = os.path.basename(root)
        solver, category, domain = _classify_case(root, root_dir)
        _materialize_shared_blockmesh(
            root, allrun_content, entries, blockmesh_resource_dir, case_name
        )

        cases.append(
            {
                "case_name": case_name,
                "solver": solver,
                "category": category,
                "domain": domain,
                "entries": entries,
                "allrun": allrun_content,
            }
        )

    return cases, stats


def _folder_file_map(case: Dict[str, Any]) -> Dict[str, List[str]]:
    folder_file_dict: Dict[str, List[str]] = {}
    for entry in case.get("entries", []):
        folder_name = entry.get("folder_name", "")
        file_name = entry.get("file_name", "")
        if not folder_name or not file_name:
            continue
        folder_file_dict.setdefault(folder_name, []).append(file_name)

    # Deterministic ordering for stable diffs between rebuilds.
    return {key: sorted(set(value)) for key, value in folder_file_dict.items()}


def save_cases_to_file(cases: List[Dict[str, Any]], output_dir) -> Dict[str, List[str]]:
    """Write the three corpus files and the case statistics. Returns the statistics."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    allrun_text = ""
    tutorials_summary_text = ""
    tutorials_text = ""

    case_stats: Dict[str, set] = {"case_domain": set(), "case_category": set(), "case_solver": set()}

    for case in cases:
        case_name = case["case_name"]
        case_domain = case["domain"]
        case_category = case["category"]
        case_solver = case["solver"]

        if case_domain:
            case_stats["case_domain"].add(case_domain)
        if case_category:
            case_stats["case_category"].add(case_category)
        if case_solver:
            case_stats["case_solver"].add(case_solver)

        case_index_text = (
            "<index>\n"
            f"case name: {case_name}\n"
            f"case domain: {case_domain}\n"
            f"case category: {case_category}\n"
            f"case solver: {case_solver}\n"
            "</index>\n\n"
        )

        folder_file_dict = _folder_file_map(case)

        dir_structure_text = "<directory_structure>\n"
        for folder_name, file_names in folder_file_dict.items():
            dir_structure_text += f"<dir>directory name: {folder_name}. "
            dir_structure_text += f"File names in this directory: [{', '.join(file_names)}]</dir>\n"
        dir_structure_text += "</directory_structure>\n\n"

        if case["allrun"] != "None":
            allrun_text += f'''
<case_begin>
{case_index_text}
{dir_structure_text}
<allrun_script>
{case["allrun"]}
</allrun_script>
</case_end>\n\n\n
'''

        tutorials_summary_text += (
            f"<case_begin>\n{case_index_text}\n{dir_structure_text}\n</case_end>\n\n"
        )

        tutorials_text += f"<case_begin>\n{case_index_text}\n{dir_structure_text}\n<tutorials>\n"
        for folder_name, file_names in folder_file_dict.items():
            tutorials_text += f"<directory_begin>directory name: {folder_name}\n"
            for file_name in file_names:
                tutorials_text += f"<file_begin>file name: {file_name}\n"

                content = ""
                for entry in case.get("entries", []):
                    if entry.get("folder_name") == folder_name and entry.get("file_name") == file_name:
                        content = entry.get("content", "")
                        break

                # Drop comments: the licence header repeats in every single file.
                cleaned_text = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
                cleaned_text = re.sub(r'//.*', '', cleaned_text)

                tutorials_text += f"<file_content>{cleaned_text}</file_content>\n"
                tutorials_text += "</file_end>\n\n"

            tutorials_text += "</directory_end>\n\n"

        tutorials_text += "</tutorials>\n</case_end>\n\n\n"

    (output_dir / RAW_FILENAMES["allrun"]).write_text(allrun_text, encoding="utf-8")
    (output_dir / RAW_FILENAMES["structure"]).write_text(tutorials_summary_text, encoding="utf-8")
    (output_dir / RAW_FILENAMES["details"]).write_text(tutorials_text, encoding="utf-8")

    case_stats["case_category"].add("None")
    stats_json = {key: sorted(value) for key, value in case_stats.items()}
    (output_dir / RAW_FILENAMES["stats"]).write_text(
        json.dumps(stats_json, ensure_ascii=False, indent=4), encoding="utf-8"
    )

    return stats_json
