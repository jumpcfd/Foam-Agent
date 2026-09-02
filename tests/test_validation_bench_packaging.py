"""Unit tests for the validation package and checkout-local FoamBench scripts.

Validation remains importable from the installed package for downstream case checkers.
FoamBench is intentionally source-only; its behaviour is exercised from ``scripts.bench``
in test_bench_scripts.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_validation_modules_import_as_a_package():
    import foamagent.validation.check  # noqa: F401
    import foamagent.validation.run  # noqa: F401


def test_bench_modules_import_from_repository_scripts():
    import scripts.bench._bench  # noqa: F401
    import scripts.bench.foambench_reference  # noqa: F401
    import scripts.bench.foambench_run  # noqa: F401
    import scripts.bench.foambench_summary  # noqa: F401
    import scripts.bench.foambench_unpack  # noqa: F401


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
