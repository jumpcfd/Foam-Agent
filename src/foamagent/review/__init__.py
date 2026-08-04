"""Independent review of a case, run in a context of its own.

A case built by one agent and checked by the same agent is checked by whoever decided it
was right. This package runs the check somewhere else: a separate, non-interactive model
session that reads the case files and the specification, and returns its findings as a
document. It never sees how the case was arrived at, and it cannot change anything.

The pieces:

- ``settings``  -- what command to run, with which tools, for how long (YAML)
- ``templates`` -- the tasks it is given, as editable Markdown
- ``channel``   -- starting it, and what to say when it cannot be started
- ``documents`` -- the specification, findings, answers and report a case carries
- ``sandbox``   -- where its arithmetic runs: a container with the case mounted read-only
"""

from foamagent.review.channel import (
    ChannelResult,
    ChannelUnavailable,
    resolve_command,
    run_audit,
    unavailable_document,
)
from foamagent.review.documents import (
    RESULT_STAGE,
    ROUND_LIMIT,
    SPEC_STAGE,
    STAGES,
    RoundState,
    existing_reviews,
    next_review_number,
    record_round,
    report_path,
    review_path,
    rounds,
    spec_path,
    unanswered_reviews,
    write_document,
)
from foamagent.review.sandbox import (
    REPORT_WORK,
    WORK_DIRNAME,
    ScriptResult,
    docker_argv,
    run_script,
    work_dir,
)
from foamagent.review.settings import (
    JUDGE_ROLE,
    REVIEW_KEYS,
    REVIEWER_ROLE,
    ROLES,
    SANDBOX_TOOL_NAME,
    ChannelSettings,
    SandboxSettings,
    config_file,
    load_settings,
    templates_dir,
)
from foamagent.review.templates import REPORT, RESULT_REVIEW, SPEC_REVIEW, build_prompt, load_template

__all__ = [
    "ChannelResult",
    "JUDGE_ROLE",
    "REVIEWER_ROLE",
    "REVIEW_KEYS",
    "ROLES",
    "ChannelSettings",
    "ChannelUnavailable",
    "REPORT",
    "REPORT_WORK",
    "SANDBOX_TOOL_NAME",
    "SandboxSettings",
    "ScriptResult",
    "WORK_DIRNAME",
    "docker_argv",
    "run_script",
    "work_dir",
    "RESULT_REVIEW",
    "RESULT_STAGE",
    "ROUND_LIMIT",
    "SPEC_REVIEW",
    "SPEC_STAGE",
    "STAGES",
    "RoundState",
    "build_prompt",
    "config_file",
    "existing_reviews",
    "load_settings",
    "load_template",
    "next_review_number",
    "record_round",
    "report_path",
    "resolve_command",
    "review_path",
    "rounds",
    "run_audit",
    "spec_path",
    "templates_dir",
    "unanswered_reviews",
    "unavailable_document",
    "write_document",
]
