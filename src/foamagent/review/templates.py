"""The prompts the audit runs, as editable Markdown.

They ship with the package and can be replaced without touching the code: a file of the
same name under ``~/.config/foamagent/templates/`` wins. Checking prompts into a Python
string would make every change to a checklist a code change, which is the wrong shape for
something CFD practice will keep refining.

These are not distributed to the harness. The harness asks for a review and gets a
document; how that document is produced is not part of its instructions.
"""

from __future__ import annotations

from pathlib import Path

from foamagent.logger import get_logger
from foamagent.review.settings import templates_dir

logger = get_logger(__name__)

SPEC_REVIEW = "reviewer-spec.md"
RESULT_REVIEW = "reviewer-result.md"
REPORT = "judge-report.md"

TEMPLATES = (SPEC_REVIEW, RESULT_REVIEW, REPORT)


def packaged_dir() -> Path:
    """Where the shipped templates live."""
    return Path(__file__).resolve().parent / "templates"


def template_path(name: str) -> Path:
    """The file that provides ``name``: the user's copy when there is one."""
    override = templates_dir() / name
    if override.is_file():
        logger.info("Using the template at %s", override)
        return override
    return packaged_dir() / name


def load_template(name: str) -> str:
    """Return the text of a prompt template."""
    path = template_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"No prompt template named {name} at {path}")
    return path.read_text(encoding="utf-8")


def build_prompt(name: str, case_dir: str) -> str:
    """Compose one audit's prompt: the task text, then the case it applies to.

    Nothing else goes in -- no conversation, no account of how the case came to be what it
    is. The reviewer reads the case for itself, which is the whole point of running it in a
    context of its own.
    """
    return f"{load_template(name).rstrip()}\n\nCase directory: {case_dir}\n"
