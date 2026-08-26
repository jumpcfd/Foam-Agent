"""Unit tests for `foamagent update`.

update refreshes the foamagent tool itself from its own source checkout -- distinct from
`foamagent sync`, which refreshes what a project already has. Everything here runs against
a real, local git checkout (with its own bare "origin") rather than mocked git calls, since
git's own exit codes and porcelain output are exactly what the command reads.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from foamagent.cli import main

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def checkout(tmp_path, monkeypatch) -> Path:
    """A clean foamagent source checkout, on main, tracking a bare "origin"."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)

    repo = tmp_path / "checkout"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "pyproject.toml").write_text('[project]\nname = "foamagent"\nversion = "0.0.0"\n', encoding="utf-8")
    git(repo, "add", "pyproject.toml")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def test_update_rejects_a_directory_that_is_not_the_foamagent_checkout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert main(["update"]) == 1
    assert "foamagent" in capsys.readouterr().out


def test_update_rejects_a_dirty_working_tree(checkout, monkeypatch, capsys):
    (checkout / "scratch.txt").write_text("wip\n", encoding="utf-8")
    monkeypatch.chdir(checkout)

    assert main(["update"]) == 1
    assert "not clean" in capsys.readouterr().out


def test_update_rejects_a_branch_other_than_main(checkout, monkeypatch, capsys):
    git(checkout, "switch", "-q", "-c", "work/other")
    monkeypatch.chdir(checkout)

    assert main(["update"]) == 1
    out = capsys.readouterr().out
    assert "work/other" in out
    assert "git switch main" in out


def test_update_notes_the_venv_case_without_reinstalling(checkout, monkeypatch, capsys):
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(
        "foamagent.cli.shutil.which", lambda name: str(checkout / ".venv" / "bin" / "foamagent")
    )

    assert main(["update"]) == 0

    out = capsys.readouterr().out
    assert "pull alone updated it" in out
    assert "uv tool install" not in out
    assert "foamagent sync" in out


def test_update_reinstalls_the_tool_when_not_running_from_the_checkouts_venv(checkout, monkeypatch, capsys):
    monkeypatch.chdir(checkout)
    monkeypatch.setattr("foamagent.cli.shutil.which", lambda name: "/home/user/.local/bin/foamagent")

    calls = []
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["uv", "tool"]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("foamagent.cli.subprocess.run", fake_run)

    assert main(["update"]) == 0

    assert calls == [["uv", "tool", "install", "--force", "--from", ".", "foamagent"]]
    out = capsys.readouterr().out
    assert "foamagent sync" in out


def test_update_reports_a_failed_reinstall(checkout, monkeypatch, capsys):
    monkeypatch.chdir(checkout)
    monkeypatch.setattr("foamagent.cli.shutil.which", lambda name: "/home/user/.local/bin/foamagent")

    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd[:2] == ["uv", "tool"]:
            return subprocess.CompletedProcess(cmd, 1)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("foamagent.cli.subprocess.run", fake_run)

    assert main(["update"]) == 1
    assert "was not updated" in capsys.readouterr().out
