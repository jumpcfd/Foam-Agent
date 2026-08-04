"""Test-wide isolation from whatever the machine running the tests is configured with.

Settings now come from files as well as from the environment, which means a developer with
`~/.config/foamagent/config.yaml` on their machine, or a `foamagent.yaml` anywhere above the
checkout, would be running a different suite from CI. Every test starts with neither.

A test that wants a settings file makes one and points the environment at it, as
`tests/test_review.py` does.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path_factory, monkeypatch):
    """No user settings file, no project settings file, unless a test writes one."""
    home = tmp_path_factory.mktemp("foamagent-config")
    monkeypatch.setenv("FOAMAGENT_CONFIG_HOME", str(home))
    monkeypatch.delenv("FOAMAGENT_CONFIG_FILE", raising=False)
    monkeypatch.delenv("FOAMAGENT_TEMPLATES_DIR", raising=False)
    # An empty value means "there is no project file", which is what stops the search from
    # walking up out of the checkout and finding one belonging to somebody's home directory.
    monkeypatch.setenv("FOAMAGENT_PROJECT_CONFIG", "")
    return home
