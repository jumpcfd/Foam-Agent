import pytest

from foamagent.validation.check import open_case


def test_check_reexports_case_checker_primitives():
    from foamagent.validation import check, primitives

    for name in (
        "open_case",
        "sample_line",
        "integrate",
        "wall_patch_names",
        "find_leading_edge",
        "coefficients_from_history",
        "steady_window_mean",
    ):
        assert getattr(check, name) is getattr(primitives, name)


def test_open_case_reports_missing_polymesh_instead_of_crashing(tmp_path):
    (tmp_path / "constant").mkdir()
    (tmp_path / "0").mkdir()

    with pytest.raises(SystemExit, match="blockMesh was never run"):
        open_case(tmp_path)
