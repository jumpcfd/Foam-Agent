"""Hermes Agent plugin for the `foamhermes` profile: task ledger integration.

Runs inside Hermes's own Python process (its own venv, not foamagent's), so this talks to
`foamagent tasks` as a subprocess rather than importing `foamagent.tasks` directly -- the
two packages are never on the same sys.path.

Registers three things via PluginContext, all confirmed against a live Hermes install
(v0.20.6) before this was written:

- a system-prompt section showing the task ledger (`foamagent tasks status`). Frozen at
  session start, but that is not the handicap it is for Claude Code's SessionStart hook:
  a system-prompt section is not part of the conversation history a compaction summarises,
  so it survives a compaction that would otherwise erase it.
- a `pre_verify` hook that reuses `foamagent tasks stop-check` verbatim -- Hermes documents
  `pre_verify` as accepting the same `{"decision": "block", "reason": ...}` shape Claude
  Code's Stop hook uses, and that is exactly what `stop-check` already prints.
- a `pre_tool_call` hook with two jobs: it blocks `write_file`/`patch` (the `file` toolset's
  write tools -- confirmed against `tools/file_tools.py` in the Hermes source, which is
  Claude Code's Write/Edit/NotebookEdit here) while `foamagent tasks write-check` says no
  task is open, reusing its `hookSpecificOutput.permissionDecisionReason` as the block
  message; and it blocks a `git commit` run through the terminal tool, mirroring Claude
  Code's `permissions.deny` (and, since it tokenises the command instead of matching a
  fixed prefix, also catching `git -C x commit`, which the Claude-side deny does not).
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Mapping, Optional

_SUBPROCESS_TIMEOUT_SECONDS = 20


def _foamagent_command() -> List[str]:
    """Same fallback `server_command()` in harness/__init__.py uses: console script, else -m."""
    executable = shutil.which("foamagent")
    if executable:
        return [executable]
    return [sys.executable, "-m", "foamagent.cli"]


def _run_tasks(*args: str) -> str:
    try:
        result = subprocess.run(
            [*_foamagent_command(), "tasks", *args],
            stdin=subprocess.DEVNULL,  # `stop-check` reads stdin when it's not a tty; never
            # give it Hermes's own stdin to read from, or an interactive session's open (but
            # silent) stdin hangs this call until _SUBPROCESS_TIMEOUT_SECONDS -- confirmed
            # against a live `hermes -p foamhermes` session before this was added.
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _ledger_section(_session_info: Mapping[str, Any]) -> str:
    return _run_tasks("status")


def _pre_verify(**_: Any) -> Optional[Dict[str, Any]]:
    output = _run_tasks("stop-check")
    if not output:
        return None
    try:
        directive = json.loads(output)
    except ValueError:
        return None
    return directive if isinstance(directive, dict) else None


_FILE_WRITE_TOOLS = frozenset({"write_file", "patch"})


def _pre_tool_call(
    tool_name: str = "", args: Optional[Dict[str, Any]] = None, **_: Any
) -> Optional[Dict[str, str]]:
    args = args or {}
    if tool_name in _FILE_WRITE_TOOLS:
        output = _run_tasks("write-check")
        if not output:
            return None
        try:
            directive = json.loads(output)
        except ValueError:
            return None
        if not isinstance(directive, dict):
            return None
        hook_output = directive.get("hookSpecificOutput")
        reason = hook_output.get("permissionDecisionReason") if isinstance(hook_output, dict) else None
        return {"action": "block", "message": reason} if isinstance(reason, str) and reason else None
    command = args.get("command")
    if tool_name != "terminal" or not isinstance(command, str):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if "git" in tokens and "commit" in tokens:
        return {
            "action": "block",
            "message": (
                "git commit is denied here -- close the task with task_done (paths + "
                "message) instead; that is the only way work becomes committed."
            ),
        }
    return None


def register(ctx) -> None:
    ctx.register_system_prompt_section("foamagent-tasks", _ledger_section)
    ctx.register_hook("pre_verify", _pre_verify)
    ctx.register_hook("pre_tool_call", _pre_tool_call)
