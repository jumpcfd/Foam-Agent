import pytest

from foamagent.validation.check import open_case


def test_open_case_reports_missing_polymesh_instead_of_crashing(tmp_path):
    (tmp_path / "constant").mkdir()
    (tmp_path / "0").mkdir()

    with pytest.raises(SystemExit, match="blockMesh was never run"):
        open_case(tmp_path)
