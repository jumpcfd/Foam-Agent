"""Unit tests for supplemental skills: plan_docs/19a-phase9-spec.md, R-5.

Everything here runs against tmp_path; no real harness is exercised.
"""

from __future__ import annotations

import pytest

from foamagent.config import CONFIG_KEYS, describe, skills_dir_setting


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
