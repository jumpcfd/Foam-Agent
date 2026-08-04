"""Unit tests for foamagent.settings: where a setting comes from, and which one wins.

Acceptance conditions A1, A2, A4 and A5 of plan_docs/11a-phase7a-spec.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foamagent import settings as settings_module
from foamagent.config import Config


@pytest.fixture
def user_config(tmp_path, monkeypatch):
    """A user settings file this test owns, and nothing else in the search path."""
    path = tmp_path / "user" / "config.yaml"
    path.parent.mkdir(parents=True)
    monkeypatch.setenv("FOAMAGENT_CONFIG_FILE", str(path))
    return path


@pytest.fixture
def project_config(tmp_path, monkeypatch):
    """A project settings file, named outright so no search walks the real filesystem."""
    path = tmp_path / "project" / "foamagent.yaml"
    path.parent.mkdir(parents=True)
    monkeypatch.setenv("FOAMAGENT_PROJECT_CONFIG", str(path))
    return path


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# A1: every server setting can be written in the settings file
# ---------------------------------------------------------------------------


def test_the_openfoam_settings_come_from_the_file(user_config):
    write(user_config, """
openfoam:
  runtime: docker
  image: my-foam:v11
  bashrc: /opt/openfoam11/etc/bashrc
  fork: esi
run:
  max_time_limit: 60
""")

    config = Config()

    assert config.openfoam_runtime == "docker"
    assert config.openfoam_image == "my-foam:v11"
    assert config.openfoam_bashrc == "/opt/openfoam11/etc/bashrc"
    assert config.openfoam_fork == "esi"
    assert config.max_time_limit == 60


def test_the_index_directory_comes_from_the_file(user_config, tmp_path):
    elsewhere = tmp_path / "indexes"
    write(user_config, f"index:\n  dir: {elsewhere}\n")

    from foamagent.indexing import index_root

    assert index_root() == elsewhere.resolve()


def test_the_index_file_size_limit_comes_from_the_file(user_config):
    write(user_config, "index:\n  max_file_kb: 7\n")

    from foamagent.indexing.tutorials import max_file_bytes

    assert max_file_bytes() == 7 * 1024


def test_a_setting_nobody_wrote_keeps_its_default(user_config):
    write(user_config, "openfoam:\n  runtime: docker\n")

    config = Config()

    assert config.openfoam_runtime == "docker"
    assert config.openfoam_image == "openfoam/openfoam10-paraview56"


# ---------------------------------------------------------------------------
# A2: environment > project file > user file > default
# ---------------------------------------------------------------------------


def test_the_project_file_beats_the_user_file(user_config, project_config):
    write(user_config, "openfoam:\n  image: from-user\n")
    write(project_config, "openfoam:\n  image: from-project\n")

    assert Config().openfoam_image == "from-project"


def test_the_environment_beats_both_files(user_config, project_config, monkeypatch):
    write(user_config, "openfoam:\n  image: from-user\n")
    write(project_config, "openfoam:\n  image: from-project\n")
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_IMAGE", "from-env")

    assert Config().openfoam_image == "from-env"


def test_the_user_file_still_supplies_what_the_project_file_leaves_out(user_config, project_config):
    write(user_config, "openfoam:\n  image: from-user\n  bashrc: /from/user\n")
    write(project_config, "openfoam:\n  image: from-project\n")

    config = Config()

    assert config.openfoam_image == "from-project"
    assert config.openfoam_bashrc == "/from/user"


def test_every_value_says_where_it_came_from(user_config, monkeypatch):
    write(user_config, "openfoam:\n  image: from-user\n")
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", "docker")

    config = Config()

    assert config.sources["openfoam.runtime"] == "env FOAMAGENT_OPENFOAM_RUNTIME"
    assert config.sources["openfoam.image"].startswith("user settings")
    assert config.sources["openfoam.bashrc"] == "default"


# ---------------------------------------------------------------------------
# A4: finding the project file
# ---------------------------------------------------------------------------


def test_the_project_file_is_found_in_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("FOAMAGENT_PROJECT_CONFIG", raising=False)
    write(tmp_path / "foamagent.yaml", "openfoam:\n  image: here\n")

    assert settings_module.project_config_file(tmp_path) == tmp_path / "foamagent.yaml"


def test_the_project_file_is_found_in_a_parent_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("FOAMAGENT_PROJECT_CONFIG", raising=False)
    write(tmp_path / "foamagent.yaml", "openfoam:\n  image: here\n")
    deep = tmp_path / "cases" / "cavity"
    deep.mkdir(parents=True)

    assert settings_module.project_config_file(deep) == tmp_path / "foamagent.yaml"


def test_the_dot_foamagent_directory_is_searched_too(tmp_path, monkeypatch):
    monkeypatch.delenv("FOAMAGENT_PROJECT_CONFIG", raising=False)
    nested = tmp_path / ".foamagent"
    nested.mkdir()
    write(nested / "config.yaml", "openfoam:\n  image: here\n")

    assert settings_module.project_config_file(tmp_path) == nested / "config.yaml"


def test_the_search_stops_at_a_repository_boundary(tmp_path, monkeypatch):
    """A settings file above a checkout belongs to something else, not to this project."""
    monkeypatch.delenv("FOAMAGENT_PROJECT_CONFIG", raising=False)
    write(tmp_path / "foamagent.yaml", "openfoam:\n  image: outside\n")

    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    work = repository / "cases"
    work.mkdir()

    assert settings_module.project_config_file(work) is None


def test_a_file_inside_the_repository_is_still_found(tmp_path, monkeypatch):
    monkeypatch.delenv("FOAMAGENT_PROJECT_CONFIG", raising=False)
    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    write(repository / "foamagent.yaml", "openfoam:\n  image: inside\n")
    work = repository / "cases"
    work.mkdir()

    assert settings_module.project_config_file(work) == repository / "foamagent.yaml"


def test_naming_a_file_that_does_not_exist_means_there_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("FOAMAGENT_PROJECT_CONFIG", str(tmp_path / "absent.yaml"))

    assert settings_module.project_config_file() is None


# ---------------------------------------------------------------------------
# A5: a broken file is reported, not raised
# ---------------------------------------------------------------------------


def test_a_settings_file_that_is_not_yaml_falls_back_to_the_defaults(user_config):
    write(user_config, "openfoam:\n  image: [unclosed\n")

    config = Config()

    assert config.openfoam_image == "openfoam/openfoam10-paraview56"


def test_a_settings_file_that_is_not_a_mapping_is_ignored(user_config):
    write(user_config, "- one\n- two\n")

    assert Config().openfoam_runtime == "native"


def test_a_section_that_is_not_a_mapping_is_ignored(user_config):
    write(user_config, "openfoam: just-a-string\n")

    assert Config().openfoam_runtime == "native"


def test_a_value_outside_the_allowed_set_falls_back(user_config):
    write(user_config, "openfoam:\n  runtime: kubernetes\n")

    assert Config().openfoam_runtime == "native"


def test_a_number_that_is_not_a_number_falls_back(user_config):
    write(user_config, "run:\n  max_time_limit: soon\n")

    assert Config().max_time_limit == 3600


# ---------------------------------------------------------------------------
# A6 / A18: no stdout, no import-time reading
# ---------------------------------------------------------------------------


def test_resolving_settings_writes_nothing_to_stdout(user_config, capsys):
    write(user_config, "openfoam:\n  runtime: kubernetes\n")  # provokes a warning

    Config()

    assert capsys.readouterr().out == ""


def test_importing_the_package_reads_no_settings_file(monkeypatch, tmp_path):
    """Import must not touch the disk: the file is read when a caller asks for a value."""
    opened = []
    original = settings_module.read_yaml

    def spy(path):
        opened.append(path)
        return original(path)

    monkeypatch.setattr(settings_module, "read_yaml", spy)

    import importlib

    importlib.reload(__import__("foamagent"))

    assert opened == []


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_setting_one_value_keeps_the_rest_of_the_file(tmp_path):
    path = write(tmp_path / "config.yaml", "openfoam:\n  image: keep-me\nreview:\n  model: old\n")

    settings_module.set_value(path, "review.model", "new")

    data = settings_module.read_yaml(path)
    assert data["review"]["model"] == "new"
    assert data["openfoam"]["image"] == "keep-me"


def test_setting_a_value_creates_the_file_and_its_sections(tmp_path):
    path = tmp_path / "absent" / "config.yaml"

    settings_module.set_value(path, "review.judge.model", "claude-opus-5")

    assert settings_module.read_yaml(path) == {"review": {"judge": {"model": "claude-opus-5"}}}


def test_unsetting_a_value_reports_whether_it_was_there(tmp_path):
    path = write(tmp_path / "config.yaml", "review:\n  model: sonnet\n")

    assert settings_module.unset_value(path, "review.model") is True
    assert settings_module.unset_value(path, "review.model") is False
    assert settings_module.read_yaml(path) == {"review": {}}
