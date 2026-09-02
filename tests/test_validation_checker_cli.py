from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_checker_cli_writes_metadata_and_returns_zero(tmp_path):
    from foamagent.validation.checker_cli import run_checker

    case_dir = tmp_path / "built"
    case_dir.mkdir()
    reference = {
        "case": "demo",
        "title": "Demo case",
        "source": {"citation": "demo source"},
        "comparison": {"kind": "channel_statistics"},
    }
    reference_path = tmp_path / "reference.json"
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    output_dir = tmp_path / "output"

    seen = {}

    def checker(received_case: Path, received_reference: dict) -> dict:
        seen["case"] = received_case
        seen["reference"] = received_reference
        return {"metrics": {"value": 3}, "agrees": True}

    exit_code = run_checker(
        checker,
        [str(case_dir), "--reference", str(reference_path), "--out", str(output_dir)],
    )

    assert exit_code == 0
    assert seen["case"] == case_dir.resolve()
    assert seen["reference"] == reference
    assert json.loads((output_dir / "comparison.json").read_text(encoding="utf-8")) == {
        "case": "demo",
        "title": "Demo case",
        "source": "demo source",
        "metrics": {"value": 3},
        "agrees": True,
    }


def test_checker_cli_returns_one_for_a_rejected_case(tmp_path):
    from foamagent.validation.checker_cli import run_checker

    case_dir = tmp_path / "built"
    case_dir.mkdir()
    reference_path = tmp_path / "reference.json"
    reference_path.write_text(json.dumps({"comparison": {"kind": "custom"}}), encoding="utf-8")

    exit_code = run_checker(
        lambda received_case, reference: {"agrees": False, "reason": "outside tolerance"},
        [str(case_dir), "--reference", str(reference_path)],
    )

    assert exit_code == 1
    assert json.loads((case_dir / "comparison.json").read_text(encoding="utf-8"))["agrees"] is False


def test_checker_cli_rejects_a_result_without_boolean_agrees(tmp_path):
    from foamagent.validation.checker_cli import run_checker

    case_dir = tmp_path / "built"
    case_dir.mkdir()
    reference_path = tmp_path / "reference.json"
    reference_path.write_text(json.dumps({"comparison": {"kind": "custom"}}), encoding="utf-8")

    with pytest.raises(ValueError, match="boolean 'agrees'"):
        run_checker(
            lambda received_case, reference: {"agrees": 1},
            [str(case_dir), "--reference", str(reference_path)],
        )

    assert not (case_dir / "comparison.json").exists()
