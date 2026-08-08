"""Unit tests for plan_docs/21a-phase10-spec.md, R-6.

scripts/validation and scripts/bench moved into the foamagent package so that a project
which adds foamagent as a dependency, rather than checking this repository out, can use
them. What matters here is that the packaging itself holds: the modules import without a
checkout-relative sys.path trick, and the data file the bench scripts need travels with the
package. The scripts' own behaviour is exercised in test_validation_scripts.py and
test_bench_scripts.py.
"""

from __future__ import annotations

from pathlib import Path


def test_validation_modules_import_as_a_package():
    import foamagent.validation.check  # noqa: F401
    import foamagent.validation.run  # noqa: F401


def test_bench_modules_import_as_a_package_with_no_sys_path_trick():
    import foamagent.bench._bench  # noqa: F401
    import foamagent.bench.foambench_reference  # noqa: F401
    import foamagent.bench.foambench_run  # noqa: F401
    import foamagent.bench.foambench_summary  # noqa: F401
    import foamagent.bench.foambench_unpack  # noqa: F401


def test_the_cases_dir_flag_defaults_to_examples_validation_in_this_repository():
    from foamagent.validation import run

    assert run.DEFAULT_CASES_DIR == Path(run.__file__).resolve().parents[3] / "examples" / "validation"
    assert (run.DEFAULT_CASES_DIR / "cavity_re100").is_dir()


def test_a_caller_outside_this_repository_can_point_at_its_own_cases(tmp_path, capsys):
    """--cases-dir is what a private problem set (not under this repository) uses.

    An empty --cases-dir makes main() report and exit before it would touch a harness, which
    is what lets this run the real argument parsing and case discovery without starting one.
    """
    from foamagent.validation import run

    exit_code = run.main(["--cases-dir", str(tmp_path)])

    assert exit_code == 1
    assert str(tmp_path) in capsys.readouterr().err


def test_score_calculation_patch_ships_with_the_package():
    import foamagent.bench

    patch_file = Path(foamagent.bench.__file__).parent / "score_calculation.patch"
    assert patch_file.is_file()
