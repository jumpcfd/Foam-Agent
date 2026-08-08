"""Unit tests for supplemental skills: plan_docs/19a-phase9-spec.md, R-5.

Everything here runs against tmp_path; no real harness is exercised.
"""

from __future__ import annotations

import pytest

from foamagent.config import CONFIG_KEYS, describe, skills_dir_setting
from foamagent.harness import SKILL_NAME, install


@pytest.fixture
def project_config(tmp_path, monkeypatch):
    """A project settings file, named outright so no search walks the real filesystem."""
    path = tmp_path / "project" / "foamagent.yaml"
    path.parent.mkdir(parents=True)
    monkeypatch.setenv("FOAMAGENT_PROJECT_CONFIG", str(path))
    return path


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def _skill(directory, name, body="---\nname: dummy\n---\ndummy\n"):
    skill_dir = directory / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    return skill_dir


# ---------------------------------------------------------------------------
# R-5.1: resolution
# ---------------------------------------------------------------------------


def test_skills_dir_is_unset_by_default():
    assert skills_dir_setting().value is None


def test_skills_dir_env_beats_project_file(project_config, monkeypatch, tmp_path):
    write(project_config, f"skills:\n  dir: {tmp_path / 'from-project'}\n")
    monkeypatch.setenv("FOAMAGENT_SKILLS_DIR", str(tmp_path / "from-env"))

    assert skills_dir_setting().value == tmp_path / "from-env"


# ---------------------------------------------------------------------------
# R-5.6: config show gains exactly one row
# ---------------------------------------------------------------------------


def test_describe_has_one_row_per_config_key_including_skills_dir():
    assert "skills.dir" in CONFIG_KEYS
    rows = describe()

    assert len(rows) == len(CONFIG_KEYS)
    assert any(row.key == "skills.dir" for row in rows)


def test_describe_shows_none_when_unset():
    rows = {row.key: row for row in describe()}

    assert rows["skills.dir"].value == "(none)"


# ---------------------------------------------------------------------------
# R-5.2: install copies supplemental skills
# ---------------------------------------------------------------------------


def test_install_copies_supplemental_skills(tmp_path, monkeypatch):
    supplemental = tmp_path / "supplemental"
    _skill(supplemental, "turbulence-tips", "# turbulence\n")
    _skill(supplemental, "heat-transfer", "# heat\n")
    monkeypatch.setenv("FOAMAGENT_SKILLS_DIR", str(supplemental))

    root = tmp_path / "work"
    result = install("claude-code", root)

    assert (root / ".claude" / "skills" / "turbulence-tips" / "SKILL.md").is_file()
    assert (root / ".claude" / "skills" / "heat-transfer" / "SKILL.md").is_file()
    notes = " ".join(result.notes)
    assert "turbulence-tips" in notes
    assert "heat-transfer" in notes


# ---------------------------------------------------------------------------
# R-5.3: a supplemental skill named like the bundled one replaces it
# ---------------------------------------------------------------------------


def test_a_supplemental_openfoam_cfd_replaces_the_bundled_skill(tmp_path, monkeypatch):
    supplemental = tmp_path / "supplemental"
    _skill(supplemental, SKILL_NAME, "# replacement skill\n")
    monkeypatch.setenv("FOAMAGENT_SKILLS_DIR", str(supplemental))

    root = tmp_path / "work"
    install("claude-code", root)

    text = (root / ".claude" / "skills" / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8")
    assert text == "# replacement skill\n"


# ---------------------------------------------------------------------------
# R-5.4: a nonexistent skills.dir fails install loudly
# ---------------------------------------------------------------------------


def test_a_missing_skills_dir_fails_install(tmp_path, monkeypatch):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("FOAMAGENT_SKILLS_DIR", str(missing))

    with pytest.raises(ValueError) as excinfo:
        install("claude-code", tmp_path / "work")

    assert str(missing) in str(excinfo.value)


# ---------------------------------------------------------------------------
# R-5.5: an existing but empty skills.dir is a note, not an error
# ---------------------------------------------------------------------------


def test_an_empty_skills_dir_is_a_note_not_an_error(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("FOAMAGENT_SKILLS_DIR", str(empty))

    result = install("claude-code", tmp_path / "work")

    assert any("No skills found" in note for note in result.notes)
