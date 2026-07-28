"""Build the raw corpus files from a directory of OpenFOAM tutorials.

The implementation moved to foamagent.indexing.tutorials so that `foamagent index build`
works from an installed wheel, where this script does not exist. This wrapper keeps the
command line that init_database.py uses.

For a container-based OpenFOAM, or to index whichever installation is actually configured,
prefer:

    foamagent index build
"""

import argparse
import concurrent.futures
import os
import subprocess
from pathlib import Path

from foamagent.indexing.tutorials import find_cases, save_cases_to_file


def get_commands_from_directory(directory_path):
    """Retrieves all command file names from a specified directory using os.scandir."""
    if not os.path.exists(directory_path):
        raise FileNotFoundError(f"The directory {directory_path} does not exist.")
    return [entry.name for entry in os.scandir(directory_path) if entry.is_file()]


def get_command_help(command, directory_path):
    """Retrieves the help message for a given command."""
    try:
        result = subprocess.run(
            f"{os.path.join(directory_path, command)} -help", shell=True, capture_output=True, text=True
        )
        return result.stdout if result.returncode == 0 else result.stderr
    except Exception as e:
        return str(e)


def fetch_command_helps(commands, directory_path):
    """Fetch help messages in parallel."""
    with concurrent.futures.ThreadPoolExecutor() as executor:
        return dict(zip(commands, executor.map(lambda cmd: get_command_help(cmd, directory_path), commands)))


if __name__ == "__main__":
    # python ./database/script/tutorial_parser.py --output_dir=./database/raw --wm_project_dir=$WM_PROJECT_DIR

    parser = argparse.ArgumentParser()
    parser.add_argument("--wm_project_dir", required=True, help="Path to WM_PROJECT_DIR")
    parser.add_argument("--output_dir", default='./database', help="Directory to save output files")
    args = parser.parse_args()

    print(args)

    tutorial_path = os.path.join(args.wm_project_dir, "tutorials")
    cases_info, case_stats = find_cases(tutorial_path)
    print(f"Statistics: {case_stats}")
    print(f"Found {len(cases_info)} cases in {tutorial_path}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    save_cases_to_file(cases_info, output_dir)

    commands_path = Path(args.wm_project_dir) / "platforms/linux64GccDPInt32Opt/bin"
    commands = get_commands_from_directory(commands_path)
    command_help_data = fetch_command_helps(commands, commands_path)

    with open(output_dir / "openfoam_commands.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(commands) + "\n")

    with open(output_dir / "openfoam_command_help.txt", "w", encoding="utf-8") as f:
        for cmd, help_text in command_help_data.items():
            f.write(f"<command_begin><command>{cmd}</command><help_text>{help_text}</help_text></command_end>\n\n")
