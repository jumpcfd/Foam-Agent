"""The `foamagent` command.

Currently the index commands. The simulation pipeline keeps its own entry points
(`foamagent.main` and `foamagent-mcp`); folding those in is a separate change.

Output goes to stdout because this is a terminal program talking to a person, unlike the
library, which must leave stdout free for the MCP stdio channel.
"""

from __future__ import annotations

import argparse
import sys
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
            with_faiss=not args.no_faiss,
            config=config,
            keep_tutorials=args.keep_tutorials,
        )
    except Exception as exc:
        _emit(f"Index build failed: {exc}")
        return 1

    _emit("")
    _emit(f"Built {result.describe()}")
    if not result.faiss_built:
        _emit(
            "No FAISS index was built, so set FOAMAGENT_RETRIEVAL_BACKEND=grep to use this "
            "corpus."
        )
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
        "--no-faiss",
        action="store_true",
        help="Write the text corpus but skip the embeddings (no rag-local extra needed).",
    )
    build.add_argument(
        "--keep-tutorials",
        action="store_true",
        help="Keep the copied tutorials next to the index instead of deleting them.",
    )
    build.set_defaults(func=_cmd_index_build)

    listing = index_commands.add_parser("list", help="Show the indexes already built.")
    listing.set_defaults(func=_cmd_index_list)

    return parser


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
