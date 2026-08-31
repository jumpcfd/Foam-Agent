"""pre_tool_call: write_file/patch consult write-check, terminal git-commit is untouched."""

from __future__ import annotations

import json

from foamagent.harness import hermes_plugin


def test_write_and_patch_are_blocked_when_write_check_denies(monkeypatch):
    monkeypatch.setattr(hermes_plugin, "_run_tasks", lambda *a: json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "No open task in the ledger.",
        }
    }))
    for tool_name in ("write_file", "patch"):
        result = hermes_plugin._pre_tool_call(tool_name=tool_name, args={"path": "x"})
        assert result == {"action": "block", "message": "No open task in the ledger."}


def test_write_is_allowed_when_write_check_is_silent(monkeypatch):
    monkeypatch.setattr(hermes_plugin, "_run_tasks", lambda *a: "")
    assert hermes_plugin._pre_tool_call(tool_name="write_file", args={"path": "x"}) is None


def test_read_and_search_never_call_write_check(monkeypatch):
    def boom(*a):
        raise AssertionError("read_file/search_files must not consult write-check")

    monkeypatch.setattr(hermes_plugin, "_run_tasks", boom)
    assert hermes_plugin._pre_tool_call(tool_name="read_file", args={"path": "x"}) is None
    assert hermes_plugin._pre_tool_call(tool_name="search_files", args={"pattern": "x"}) is None


def test_terminal_git_commit_is_still_blocked(monkeypatch):
    def boom(*a):
        raise AssertionError("terminal commands must not consult write-check")

    monkeypatch.setattr(hermes_plugin, "_run_tasks", boom)
    result = hermes_plugin._pre_tool_call(tool_name="terminal", args={"command": "git commit -m x"})
    assert result["action"] == "block"
    assert hermes_plugin._pre_tool_call(tool_name="terminal", args={"command": "ls"}) is None
