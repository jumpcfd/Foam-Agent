"""The project ledger: done is a commit, cases mark themselves, worktrees merge cleanly."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from foamagent import tasks
from foamagent.case_state import load_case_state

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    """A repository on a work branch, with one commit so main exists to be refused later."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "README.md").write_text("project\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "switch", "-q", "-c", "work/first")
    return repo


def commits(repo: Path) -> list:
    return git(repo, "log", "--format=%s").split("\n")[:-1]


def test_done_commits_only_the_ledger_and_the_named_paths(repo):
    tasks.add_task(repo, "survey", "文献調査")
    (repo / "notes.md").write_text("findings\n")
    (repo / "scratch.txt").write_text("not this one\n")

    result = tasks.finish_task(repo, "survey", "read the papers", ["notes.md"])

    assert commits(repo)[0] == "[task survey] read the papers"
    assert sorted(result["files"]) == [".foamagent/tasks/survey.json", "notes.md"]
    assert result["uncommitted"] == ["?? scratch.txt"]
    assert tasks.load_tasks(repo)["survey"].status == "done"


def test_add_rejects_bad_ids_and_reuse(repo):
    for bad in ("Survey", "文献", "-x", "a" * 41, ""):
        with pytest.raises(ValueError, match="must match"):
            tasks.add_task(repo, bad, "t")
    tasks.add_task(repo, "survey", "t")
    with pytest.raises(ValueError, match="already exists"):
        tasks.add_task(repo, "survey", "t")
    with pytest.raises(ValueError, match="do not exist"):
        tasks.add_task(repo, "later", "t", depends_on=["nope"])


def test_done_refuses_while_a_dependency_is_open_and_leaves_nothing_behind(repo):
    tasks.add_task(repo, "survey", "文献調査")
    tasks.add_task(repo, "run", "実行", depends_on=["survey"])
    (repo / "out.md").write_text("x\n")
    before = commits(repo)

    with pytest.raises(ValueError, match="survey \\(open\\)"):
        tasks.finish_task(repo, "run", "done?", ["out.md"])

    assert commits(repo) == before
    assert tasks.load_tasks(repo)["run"].status == "open"
    assert git(repo, "diff", "--cached", "--name-only") == ""

    tasks.finish_task(repo, "survey", "ok", ["out.md"])
    assert tasks.overview(repo)["tasks"][0]["ready"] is True  # "run" sorts first


def test_failed_commit_restores_the_ledger(repo):
    tasks.add_task(repo, "survey", "t")
    with pytest.raises(ValueError, match="pathspec"):
        tasks.finish_task(repo, "survey", "m", ["does-not-exist.md"])
    assert tasks.load_tasks(repo)["survey"].status == "open"
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_done_needs_paths_and_refuses_main(repo):
    tasks.add_task(repo, "survey", "t")
    with pytest.raises(ValueError, match="needs the paths"):
        tasks.finish_task(repo, "survey", "m", [])
    git(repo, "switch", "-q", "main")
    assert "on main" in tasks.add_task(repo, "other", "t")["warnings"][0]
    with pytest.raises(ValueError, match="Refusing to commit on main"):
        tasks.finish_task(repo, "other", "m", ["README.md"])
    assert tasks.load_tasks(repo)["other"].status == "open"


def test_cancel_commits_without_checking_dependencies(repo):
    tasks.add_task(repo, "survey", "t")
    tasks.add_task(repo, "run", "t", depends_on=["survey"])
    result = tasks.cancel_task(repo, "run", "方針転換")
    assert result["status"] == "cancelled"
    assert commits(repo)[0] == "[task run] 方針転換"
    # A cancelled dependency still blocks.
    tasks.add_task(repo, "report", "t", depends_on=["run"])
    with pytest.raises(ValueError, match="run \\(cancelled\\)"):
        tasks.finish_task(repo, "report", "m", ["README.md"])


def test_worktrees_add_tasks_on_two_branches_and_merge_without_conflict(repo, tmp_path):
    other = tmp_path / "project-other"
    git(repo, "worktree", "add", "-q", str(other), "-b", "work/other")
    assert tasks.is_worktree(other) and not tasks.is_worktree(repo)
    assert tasks.repo_root(other) == other.resolve()

    tasks.add_task(repo, "alpha", "a")
    (repo / "a.md").write_text("a\n")
    tasks.finish_task(repo, "alpha", "a", ["a.md"])
    tasks.add_task(other, "beta", "b")
    (other / "b.md").write_text("b\n")
    tasks.finish_task(other, "beta", "b", ["b.md"])

    git(repo, "merge", "-q", "work/other")
    assert [t["id"] for t in tasks.overview(repo)["tasks"]] == ["alpha", "beta"]
    assert {t.status for t in tasks.load_tasks(repo).values()} == {"done"}


def make_case(case: Path) -> None:
    for d in ("0", "0.orig", "0.5", "1e-05", "100", "constant/polyMesh", "constant/triSurface",
              "system", "processor0", "postProcessing", "dynamicCode", "VTK"):
        (case / d).mkdir(parents=True)
    for f in ("0/U", "0.orig/U", "0.5/U", "1e-05/U", "100/U", "constant/polyMesh/points",
              "constant/polyMesh/blockMeshDict", "constant/triSurface/a.stl", "system/controlDict",
              "processor0/x", "postProcessing/p.dat", "dynamicCode/x", "VTK/x", "log.blockMesh",
              "Allrun.out", "case.foam", "spec.md"):
        (case / f).write_text("x\n")


def test_register_case_marks_it_and_keeps_run_data_out_of_git(repo):
    case = repo / "cases" / "duct"
    make_case(case)

    result = tasks.register_case(repo, "cases/duct", note="first try")

    assert result == {"path": "cases/duct", "note": "first try", "gitignore_written": True}
    assert load_case_state(case).case_name == "duct"
    assert (case / ".gitignore").read_text() == tasks.CASE_GITIGNORE
    git(repo, "add", "cases/duct")
    staged = set(git(repo, "diff", "--cached", "--name-only").split())
    assert staged == {
        "cases/duct/.foamagent/state.json", "cases/duct/.gitignore", "cases/duct/0/U",
        "cases/duct/0.orig/U", "cases/duct/constant/polyMesh/blockMeshDict",
        "cases/duct/constant/triSurface/a.stl", "cases/duct/system/controlDict",
        "cases/duct/postProcessing/p.dat", "cases/duct/spec.md",
    }
    # Re-registering updates the note and touches nothing else.
    (case / ".gitignore").write_text("mine\n")
    again = tasks.register_case(repo, str(case), note="superseded by duct-v2")
    assert again["note"] == "superseded by duct-v2" and again["gitignore_written"] is False
    assert (case / ".gitignore").read_text() == "mine\n"
    assert tasks.register_case(repo, "cases/duct")["note"] == "superseded by duct-v2"


def test_register_case_refuses_outside_the_repository(repo, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(ValueError, match="outside the repository"):
        tasks.register_case(repo, str(outside))
    with pytest.raises(ValueError, match="does not exist"):
        tasks.register_case(repo, "cases/nope")


def test_cases_are_found_by_their_marker_even_after_a_move(repo):
    case = repo / "cases" / "duct"
    make_case(case)
    tasks.register_case(repo, "cases/duct")
    assert [c["path"] for c in tasks.list_cases(repo)] == ["cases/duct"]  # untracked yet

    git(repo, "add", "cases/duct")
    git(repo, "commit", "-q", "-m", "case")
    git(repo, "mv", "cases/duct", "cases/duct-v1")
    listed = tasks.list_cases(repo)
    assert [c["path"] for c in listed] == ["cases/duct-v1"]
    assert listed[0]["spec"] is True and listed[0]["report"] is False


def test_overview_warns_and_tolerates_a_broken_task_file(repo):
    tasks.add_task(repo, "survey", "t")
    (repo / ".foamagent" / "tasks" / "odd.json").write_text('{"title": "no status", "extra": 1}\n')
    (repo / ".foamagent" / "tasks" / "broken.json").write_text("{not json\n")
    view = tasks.overview(repo)
    assert [t["id"] for t in view["tasks"]] == ["odd", "survey"]
    assert view["branch"] == "work/first" and view["worktree"] is False
    assert any("uncommitted" in w for w in view["warnings"])
    text = tasks.format_overview(view)
    assert "[ready    ] survey: t" in text and "uncommitted:" in text


def test_repo_root_outside_git_says_git_init(tmp_path):
    with pytest.raises(ValueError, match="git init"):
        tasks.repo_root(tmp_path)


def test_cli_hooks_are_silent_without_a_ledger_and_block_once_with_pending_work(repo, monkeypatch, capsys):
    from foamagent.cli import main

    monkeypatch.chdir(repo)
    assert main(["tasks", "status"]) == 0 and main(["tasks", "stop-check"]) == 0
    assert capsys.readouterr().out == ""

    tasks.add_task(repo, "survey", "t")
    assert main(["tasks", "status"]) == 0
    assert "survey: t" in capsys.readouterr().out

    class Stdin:
        def __init__(self, text):
            self.text = text

        def isatty(self):
            return False

        def read(self):
            return self.text

    monkeypatch.setattr("sys.stdin", Stdin(json.dumps({"stop_hook_active": False})))
    assert main(["tasks", "stop-check"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "block"
    monkeypatch.setattr("sys.stdin", Stdin(json.dumps({"stop_hook_active": True})))
    assert main(["tasks", "stop-check"]) == 0
    assert capsys.readouterr().out == ""


def test_full_profile_has_the_tools_and_sandbox_does_not():
    import asyncio

    from fastmcp import Client

    from foamagent.mcp.fastmcp_server import build_server

    def names(profile):
        async def main():
            async with Client(build_server(profile)) as client:
                return {t.name for t in await client.list_tools()}

        return asyncio.run(main())

    ours = {"task_list", "task_add", "task_done", "task_cancel", "case_register"}
    assert ours <= names("full")
    assert not (ours & names("sandbox"))


def test_install_claude_code_writes_hooks_and_keeps_existing_settings(tmp_path):
    from foamagent.harness import GIT_COMMIT_DENY, install_claude_code

    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({
        "theme": "dark",
        "permissions": {"deny": ["Bash(rm:*)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo bye"}]}]},
    }))

    install_claude_code(tmp_path)
    install_claude_code(tmp_path)  # idempotent

    written = json.loads(settings.read_text())
    assert written["theme"] == "dark"
    assert written["permissions"]["deny"] == ["Bash(rm:*)", GIT_COMMIT_DENY]
    stop = written["hooks"]["Stop"]
    assert stop[0]["hooks"][0]["command"] == "echo bye"
    assert len(stop) == 2 and stop[1]["hooks"][0]["command"].endswith("tasks stop-check")
    start = written["hooks"]["SessionStart"]
    assert len(start) == 1 and start[0]["matcher"] == "startup|resume|compact"
    assert start[0]["hooks"][0]["command"].endswith("tasks status")
