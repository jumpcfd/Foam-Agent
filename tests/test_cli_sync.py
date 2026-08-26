"""Unit tests for `foamagent sync`.

sync refreshes what init deployed: the skill is always overwritten (it's part of the
package's own tool contract, not something to diverge from), while knowledge is only
overwritten after confirmation, because that's the file the user is meant to edit.
"""

from __future__ import annotations

from foamagent import knowledge
from foamagent.cli import main
from foamagent.harness import skill_source


def test_sync_on_an_empty_knowledge_directory_adds_everything_without_asking(tmp_path, capsys, monkeypatch):
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(AssertionError("should not ask")))

    assert main(["sync", "claude-code", "--directory", str(tmp_path)]) == 0

    bundled_names = {p.name for p in knowledge.bundled_dir().glob("*.md")}
    user_names = {p.name for p in knowledge.user_dir().glob("*.md")}
    assert user_names == bundled_names

    out = capsys.readouterr().out
    assert "This will overwrite" not in out
    assert "matches this install" in out


def test_sync_does_not_overwrite_an_edited_knowledge_file_without_confirmation(tmp_path, capsys, monkeypatch):
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    knowledge.seed()
    edited = sorted(knowledge.user_dir().glob("*.md"))[0]
    edited.write_text("my own notes\n", encoding="utf-8")

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    assert main(["sync", "claude-code", "--directory", str(tmp_path)]) == 0

    assert edited.read_text(encoding="utf-8") == "my own notes\n"
    out = capsys.readouterr().out
    assert "This will overwrite" in out
    assert str(edited) in out
    assert "unchanged" in out


def test_sync_yes_flag_overwrites_an_edited_knowledge_file_without_asking(tmp_path, monkeypatch):
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    knowledge.seed()
    edited = sorted(knowledge.user_dir().glob("*.md"))[0]
    edited.write_text("my own notes\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(AssertionError("should not ask")))

    assert main(["sync", "claude-code", "--directory", str(tmp_path), "-y"]) == 0

    bundled = knowledge.bundled_dir() / edited.name
    assert edited.read_text(encoding="utf-8") == bundled.read_text(encoding="utf-8")


def test_sync_always_overwrites_the_deployed_skill(tmp_path, monkeypatch):
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(AssertionError("should not ask")))

    deployed = tmp_path / ".claude" / "skills" / "openfoam-cfd" / "SKILL.md"
    deployed.parent.mkdir(parents=True)
    deployed.write_text("stale\n", encoding="utf-8")

    assert main(["sync", "claude-code", "--directory", str(tmp_path)]) == 0

    assert deployed.read_text(encoding="utf-8") == (skill_source() / "SKILL.md").read_text(encoding="utf-8")


def test_sync_detects_the_harness_from_the_directory(tmp_path, monkeypatch):
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(AssertionError("should not ask")))

    assert main(["sync", "--directory", str(tmp_path)]) == 0
    assert (tmp_path / ".claude" / "skills" / "openfoam-cfd" / "SKILL.md").is_file()


def test_sync_with_neither_config_file_needs_the_harness_named(tmp_path, capsys):
    assert main(["sync", "--directory", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "foamagent sync claude-code" in out
