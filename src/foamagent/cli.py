"""The `foamagent` command: the index, the harness configuration, the settings, the checks.

The simulation pipeline keeps its own entry point (`foamagent-mcp`), because that one talks
MCP rather than to a person.

Output goes to stdout because this is a terminal program talking to a person, unlike the
library, which must leave stdout free for the MCP stdio channel.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from foamagent.logger import get_logger

logger = get_logger(__name__)


def _emit(message: str = "") -> None:
    print(message)  # noqa: T201 - this is a CLI, stdout is where its output belongs


def _cmd_index_build(args: argparse.Namespace) -> int:
    from foamagent.config import Config
    from foamagent.environment import environment_from_config
    from foamagent.execution import backend_for_config
    from foamagent.indexing.build import build_index
    from foamagent.indexing.library import library_paths

    config = Config()
    backend = backend_for_config(config)
    environment = environment_from_config(config)

    if not environment.detected:
        _emit(
            "No OpenFOAM environment could be detected.\n"
            "  native runtime: source the OpenFOAM bashrc first, or\n"
            "  container: set FOAMAGENT_OPENFOAM_RUNTIME=docker and FOAMAGENT_OPENFOAM_IMAGE."
        )
        return 1

    _emit(f"Indexing {environment.describe()}")
    if environment.tutorials:
        _emit(f"  tutorials: {environment.tutorials}")

    try:
        result = build_index(
            environment,
            backend=backend,
            keep_tutorials=args.keep_tutorials,
        )
    except Exception as exc:
        _emit(f"Index build failed: {exc}")
        return 1

    _emit("")
    _emit(f"Built {result.describe()}")

    paths = library_paths(result.index_path)
    _emit("")
    _emit("Reference library for an AI harness:")
    _emit(f"  catalogue: {paths['catalog']}")
    _emit(f"  cases:     {paths['cases']}")
    _emit(f"  commands:  {paths['commands']}")
    return 0


def _cmd_index_list(args: argparse.Namespace) -> int:
    from foamagent.indexing import index_root, list_indexes

    indexes = list_indexes()
    if not indexes:
        _emit(f"No built indexes under {index_root()}.")
        _emit("Build one with: foamagent index build")
        return 0

    _emit(f"Built indexes under {index_root()}:")
    for info in indexes:
        _emit(f"  {info.describe()}")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    from foamagent.harness import HARNESSES, install

    try:
        result = install(args.harness, args.directory)
    except ValueError as exc:
        _emit(str(exc))
        return 1

    _emit(result.describe())
    _emit("")
    _emit("Then, once per OpenFOAM installation:")
    _emit("  foamagent index build     # builds the tutorial catalogue the skill reads")
    if args.harness not in HARNESSES:  # unreachable; install() would have raised
        return 1
    return 0


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _all_settings():
    """Every setting, resolved, in the order they are worth reading."""
    from foamagent import settings as settings_module
    from foamagent.config import describe as describe_server
    from foamagent.review.settings import describe as describe_review

    resolved = settings_module.load()
    return resolved, [*describe_server(resolved), *describe_review(resolved)]


def _known_keys() -> List[str]:
    from foamagent.config import CONFIG_KEYS
    from foamagent.review.settings import REVIEW_KEYS

    return [*CONFIG_KEYS, *REVIEW_KEYS]


def _target_file(project: bool) -> Path:
    """Which file a write goes to."""
    from foamagent import settings as settings_module

    if not project:
        return settings_module.config_file()

    found = settings_module.project_config_file()
    return found if found is not None else Path.cwd() / "foamagent.yaml"


def _format(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    if value == "":
        return "''"
    return str(value)


def _cmd_config_show(args: argparse.Namespace) -> int:
    resolved, rows = _all_settings()

    _emit("Settings files in effect, highest priority first:")
    for label, path, _ in resolved.documents:
        _emit(f"  {label}: {path}")
    if not resolved.documents:
        from foamagent import settings as settings_module

        _emit(f"  (none; {settings_module.config_file()} would be read if it existed)")
    _emit("")

    width = max(len(row.key) for row in rows)
    value_width = min(40, max(len(_format(row.value)) for row in rows))
    for row in rows:
        _emit(f"  {row.key:<{width}}  {_format(row.value):<{value_width}}  {row.source}")

    _emit("")
    _emit("An environment variable beats a file. `foamagent config set <key> <value>` writes one.")
    return 0


def _cmd_config_path(args: argparse.Namespace) -> int:
    from foamagent import settings as settings_module

    user = settings_module.config_file()
    project = settings_module.project_config_file()

    _emit(f"user settings:     {user}{'' if user.is_file() else '  (not written yet)'}")
    _emit(f"project settings:  {project if project else '(none found from ' + str(Path.cwd()) + ')'}")
    _emit(f"templates:         {settings_module.templates_dir()}")
    return 0


def _cmd_config_set(args: argparse.Namespace) -> int:
    from foamagent import settings as settings_module

    known = _known_keys()
    if args.key not in known:
        _emit(f"Unknown setting {args.key!r}. The settings are:")
        for key in known:
            _emit(f"  {key}")
        return 1

    import yaml

    try:
        value = yaml.safe_load(args.value)
    except yaml.YAMLError:
        value = args.value

    path = _target_file(args.project)
    settings_module.set_value(path, args.key, value)
    _emit(f"{args.key} = {_format(value)}   ({path})")
    return 0


def _cmd_config_unset(args: argparse.Namespace) -> int:
    from foamagent import settings as settings_module

    path = _target_file(args.project)
    if settings_module.unset_value(path, args.key):
        _emit(f"Removed {args.key} from {path}.")
        return 0

    _emit(f"{args.key} is not set in {path}; nothing to remove.")
    return 0


def _cmd_config_edit(args: argparse.Namespace) -> int:
    """Open the settings file in an editor, comments and all."""
    path = _target_file(args.project)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(_starter_file(), encoding="utf-8")

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        _emit(f"No $EDITOR is set. The file is {path}.")
        return 1

    try:
        return subprocess.call([*editor.split(), str(path)])
    except OSError as exc:
        _emit(f"Could not start {editor!r}: {exc}. The file is {path}.")
        return 1


def _starter_file() -> str:
    return (
        "# Foam-Agent settings. Every key here has a working default; this file is only\n"
        "# needed to change one. `foamagent config show` lists them with their origins.\n"
        "\n"
        "# openfoam:\n"
        "#   runtime: docker\n"
        "#   image: openfoam/openfoam10-paraview56\n"
        "#   bashrc: /opt/openfoam10/etc/bashrc\n"
        "\n"
        "# review:\n"
        "#   model: claude-sonnet-5\n"
        "#   judge:\n"
        "#     model: claude-opus-5\n"
    )


# ---------------------------------------------------------------------------
# The interactive setup
# ---------------------------------------------------------------------------


def _ask(question: str, default: str, choices: Optional[List[str]] = None) -> str:
    """One question, with the current value as the answer to pressing return."""
    while True:
        suffix = f" [{default}]" if default else " []"
        if choices:
            suffix = f" ({'/'.join(choices)})" + suffix
        answer = input(f"{question}{suffix}: ").strip()  # noqa: S322 - a CLI prompt
        if not answer:
            return default
        if choices and answer not in choices:
            _emit(f"  Please answer one of: {', '.join(choices)}")
            continue
        return answer


def _confirm(question: str, default: bool = True) -> bool:
    answer = _ask(question, "y" if default else "n", ["y", "n"])
    return answer == "y"


def _cmd_config_wizard(args: argparse.Namespace) -> int:
    """Ask the questions whose answers make up a working setup, then write them."""
    from foamagent import settings as settings_module
    from foamagent.config import DEFAULT_BASHRC, DEFAULT_IMAGE, Config

    if not sys.stdin.isatty():
        _emit(
            "foamagent config needs a terminal to ask questions in.\n"
            "Set one setting at a time instead:\n"
            "  foamagent config set openfoam.runtime docker\n"
            "  foamagent config show"
        )
        return 1

    current = Config()
    path = _target_file(args.project)

    _emit(f"Writing to {path}.")
    if path.is_file():
        _emit("It exists; the keys you answer are replaced and the rest is kept.")
    _emit("Press return to keep the value in brackets.")
    _emit("")

    answers = {}

    runtime = _ask(
        "How is OpenFOAM run", current.openfoam_runtime, ["native", "docker"]
    )
    answers["openfoam.runtime"] = runtime

    if runtime == "docker":
        answers["openfoam.image"] = _ask(
            "Which image", current.openfoam_image or DEFAULT_IMAGE
        )
        answers["openfoam.bashrc"] = _ask(
            "Path to the OpenFOAM bashrc inside that image",
            current.openfoam_bashrc or DEFAULT_BASHRC,
        )

    _emit("")
    _emit("A review is a separate session of your own harness. It reads the case; it cannot")
    _emit("change it. Leave the model empty to let the harness choose.")

    from foamagent.review import load_settings
    from foamagent.review.settings import JUDGE_ROLE, REVIEWER_ROLE

    review = load_settings()
    answers["review.command"] = _ask(
        "Command that starts one", " ".join(review.command)
    ).split()
    answers["review.reviewer.model"] = _ask(
        "Model for the review", load_settings(role=REVIEWER_ROLE).model
    )
    answers["review.judge.model"] = _ask(
        "Model for the report", load_settings(role=JUDGE_ROLE).model
    )
    answers["review.sandbox.runtime"] = _ask(
        "Let a review run Python in a container to check numbers",
        review.sandbox.runtime,
        ["docker", "none"],
    )

    _emit("")
    for key, value in answers.items():
        _emit(f"  {key} = {_format(value)}")
    _emit("")
    if not _confirm(f"Write these to {path}"):
        _emit("Nothing was written.")
        return 0

    for key, value in answers.items():
        settings_module.set_value(path, key, value)
    _emit(f"Written to {path}.")

    _emit("")
    _emit("Checking the setup.")
    _emit("")
    _cmd_doctor(argparse.Namespace(directory=None))
    return 0


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------


def _cmd_doctor(args: argparse.Namespace) -> int:
    from foamagent.diagnostics import run_checks

    directory = Path(args.directory) if getattr(args, "directory", None) else None
    checks = run_checks(directory)

    blocking = 0
    for check in checks:
        if check.ok:
            mark = "ok  "
        elif check.required:
            mark = "FAIL"
            blocking += 1
        else:
            mark = "warn"
        _emit(f"  [{mark}] {check.name}: {check.detail}")
        if not check.ok and check.fix:
            _emit(f"         → {check.fix}")

    _emit("")
    if blocking:
        _emit(f"{blocking} check(s) must be fixed before a case can be built.")
        return 1

    warnings = sum(1 for check in checks if not check.ok)
    if warnings:
        _emit(f"Usable, with {warnings} thing(s) reduced. See the arrows above.")
    else:
        _emit("Everything checked out.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="foamagent",
        description="Foam-Agent command line tools.",
    )
    subparsers = parser.add_subparsers(dest="command")

    index = subparsers.add_parser(
        "index",
        help="Build and inspect the OpenFOAM reference index.",
        description=(
            "Foam-Agent ships an index built from Foundation v10 tutorials. These commands "
            "build one from the OpenFOAM you actually have, which is what makes the "
            "references match your installation."
        ),
    )
    index_commands = index.add_subparsers(dest="index_command")

    build = index_commands.add_parser(
        "build", help="Build an index from the detected OpenFOAM installation."
    )
    build.add_argument(
        "--keep-tutorials",
        action="store_true",
        help="Keep the copied tutorials next to the index instead of deleting them.",
    )
    build.set_defaults(func=_cmd_index_build)

    listing = index_commands.add_parser("list", help="Show the indexes already built.")
    listing.set_defaults(func=_cmd_index_list)

    install = subparsers.add_parser(
        "install",
        help="Write the configuration your AI harness needs to use Foam-Agent.",
        description=(
            "Foam-Agent works by giving an AI harness the tools to run OpenFOAM. This "
            "writes that harness's MCP configuration and the OpenFOAM skill, so the setup "
            "is one command rather than a page of instructions."
        ),
    )
    install.add_argument(
        "harness",
        choices=sorted(_harness_names()),
        help="Which harness to configure.",
    )
    install.add_argument(
        "--directory",
        default=None,
        help="Where to write the configuration (default: the current directory).",
    )
    install.set_defaults(func=_cmd_install)

    config = subparsers.add_parser(
        "config",
        help="Show and change the settings.",
        description=(
            "Every setting has a working default, an entry in ~/.config/foamagent/config.yaml, "
            "an entry in a foamagent.yaml next to your work, and an environment variable -- in "
            "that order of increasing precedence. With no arguments this asks the questions "
            "that make up a working setup and writes the answers."
        ),
    )
    config.add_argument(
        "--project",
        action="store_true",
        help="Write to the project settings file rather than to the user's.",
    )
    config.set_defaults(func=_cmd_config_wizard)
    config_commands = config.add_subparsers(dest="config_command")

    show = config_commands.add_parser(
        "show", help="Show every setting, its value and where that value came from."
    )
    show.set_defaults(func=_cmd_config_show)

    where = config_commands.add_parser("path", help="Show which files are being read.")
    where.set_defaults(func=_cmd_config_path)

    setter = config_commands.add_parser("set", help="Write one setting.")
    setter.add_argument("key", help="Dotted key, as `config show` prints it.")
    setter.add_argument("value", help="The value. YAML, so lists and numbers work.")
    setter.add_argument(
        "--project", action="store_true", help="Write to the project settings file."
    )
    setter.set_defaults(func=_cmd_config_set)

    unsetter = config_commands.add_parser(
        "unset", help="Remove one setting, so its default applies again."
    )
    unsetter.add_argument("key")
    unsetter.add_argument(
        "--project", action="store_true", help="Remove it from the project settings file."
    )
    unsetter.set_defaults(func=_cmd_config_unset)

    editor = config_commands.add_parser(
        "edit", help="Open the settings file in $EDITOR, keeping its comments."
    )
    editor.add_argument(
        "--project", action="store_true", help="Edit the project settings file."
    )
    editor.set_defaults(func=_cmd_config_edit)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check that this machine can do the work, changing nothing.",
        description=(
            "Looks at the things that otherwise fail later, inside the harness: whether "
            "OpenFOAM can be reached, whether the tutorial catalogue has been built for it, "
            "whether the command that runs an independent review is installed, whether a "
            "review could compute, and whether the harness configuration here still agrees "
            "with the settings."
        ),
    )
    doctor.add_argument(
        "--directory",
        default=None,
        help="Where to look for .mcp.json (default: the current directory).",
    )
    doctor.set_defaults(func=_cmd_doctor)

    return parser


def _harness_names():
    from foamagent.harness import HARNESSES

    return HARNESSES.keys()


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
