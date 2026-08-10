"""Unit tests for foamagent.config.Config and foamagent.paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from foamagent import paths
from foamagent.config import Config

# All FOAMAGENT_* env vars that Config()/paths read. Cleared before every test so
# ambient shell state (or leakage from a previous test) can't affect the assertions.
_ENV_KEYS = [
    "FOAMAGENT_OPENFOAM_RUNTIME",
    "FOAMAGENT_OPENFOAM_IMAGE",
    "FOAMAGENT_OPENFOAM_BASHRC",
    "FOAMAGENT_OPENFOAM_FORK",
    "FOAMAGENT_ROOT",
    "FOAMAGENT_RUN_DIRECTORY",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Ensure no FOAMAGENT_* env var leaks in from the ambient shell or a prior test."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# 1. Defaults
# ---------------------------------------------------------------------------


def test_defaults_no_env():
    cfg = Config()
    assert cfg.openfoam_runtime == "native"
    # Empty means "whichever fork is installed"; detection fills it in.
    assert cfg.openfoam_fork == ""


def test_config_holds_no_model_settings():
    """This process runs no model, so no provider, key or model name belongs here."""
    cfg = Config()

    for attribute in ("model_provider", "model_version", "embedding_model", "openai_base_url"):
        assert not hasattr(cfg, attribute)


# ---------------------------------------------------------------------------
# 2. Each override actually applies
# ---------------------------------------------------------------------------


def test_override_openfoam_runtime(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", "docker")
    assert Config().openfoam_runtime == "docker"


def test_override_openfoam_image(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_IMAGE", "custom-foam:v1")
    assert Config().openfoam_image == "custom-foam:v1"


def test_override_openfoam_bashrc(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_BASHRC", "/opt/openfoam11/etc/bashrc")
    assert Config().openfoam_bashrc == "/opt/openfoam11/etc/bashrc"


def test_override_openfoam_fork(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_FORK", "esi")
    assert Config().openfoam_fork == "esi"


# ---------------------------------------------------------------------------
# 3. Invalid values fall back to default instead of raising
# ---------------------------------------------------------------------------


def test_invalid_openfoam_runtime_falls_back(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", "kubernetes")
    cfg = Config()
    assert cfg.openfoam_runtime == "native"


def test_invalid_openfoam_fork_falls_back(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_FORK", "extend")
    cfg = Config()
    assert cfg.openfoam_fork == ""


# ---------------------------------------------------------------------------
# 4. Empty-string / whitespace-only env values treated as unset
# ---------------------------------------------------------------------------


def test_empty_string_env_treated_as_unset(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", "")
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_FORK", "")
    cfg = Config()
    assert cfg.openfoam_runtime == "native"
    assert cfg.openfoam_fork == ""


def test_whitespace_only_env_treated_as_unset(monkeypatch):
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", "   ")
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_FORK", "\t")
    cfg = Config()
    assert cfg.openfoam_runtime == "native"
    assert cfg.openfoam_fork == ""


def test_whitespace_padded_valid_value_is_stripped(monkeypatch):
    # _env_nonempty() strips before comparing/assigning, so padded-but-valid values apply.
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_FORK", "  esi  ")
    cfg = Config()
    assert cfg.openfoam_fork == "esi"


# ---------------------------------------------------------------------------
# 5. Config() must never write to stdout (stdout is the MCP stdio protocol channel)
# ---------------------------------------------------------------------------


def test_config_writes_nothing_to_stdout(capsys):
    Config()
    captured = capsys.readouterr()
    assert captured.out == ""


def test_config_writes_nothing_to_stdout_with_overrides(monkeypatch, capsys):
    # Exercise every branch (valid override, invalid override, unset) to make sure none
    # of them leak a print() to stdout.
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_FORK", "bogus")
    monkeypatch.setenv("FOAMAGENT_OPENFOAM_RUNTIME", "docker")
    Config()
    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# 6. foamagent.paths
# ---------------------------------------------------------------------------


def test_repo_root_default():
    # <root>/src/foamagent/paths.py -> repo_root() is two levels above src/
    expected = Path(paths.__file__).resolve().parent.parent.parent
    assert paths.repo_root() == expected


def test_repo_root_honours_foamagent_root(monkeypatch, tmp_path):
    monkeypatch.setenv("FOAMAGENT_ROOT", str(tmp_path))
    assert paths.repo_root() == tmp_path.resolve()


def test_runs_dir_default_is_repo_root_slash_runs():
    assert paths.runs_dir() == paths.repo_root() / "runs"


def test_runs_dir_honours_foamagent_run_directory(monkeypatch, tmp_path):
    custom = tmp_path / "custom_runs"
    monkeypatch.setenv("FOAMAGENT_RUN_DIRECTORY", str(custom))
    assert paths.runs_dir() == custom.resolve()


def test_config_picks_up_foamagent_root_for_the_run_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("FOAMAGENT_ROOT", str(tmp_path))
    cfg = Config()

    assert Path(cfg.run_directory) == tmp_path.resolve() / "runs"
