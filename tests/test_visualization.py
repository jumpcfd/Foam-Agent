"""Tests for the visualization service.

These exercise the parts that need no PyVista, no display and no model: the generated
template's own validity, the output-file contract carried in the prompts, and the order in
which visualize_case tries its attempts.
"""

import ast
import builtins

import pytest

from foamagent.services import visualization
from foamagent.services.visualization import (
    DEFAULT_OUTPUT_PNG,
    VisualizationResult,
    generate_deterministic_pyvista_script,
    guess_primary_field,
    visualize_case,
)


# ---------------------------------------------------------------------------
# The deterministic template
# ---------------------------------------------------------------------------


def _undefined_names(source: str):
    """Return the names a module-level script reads without ever binding.

    The template is source code for a separate interpreter, so it cannot borrow anything
    from this module -- a name it does not define itself is a NameError at run time. That is
    exactly how a `print` in the template once became a call to this module's `logger`.
    """
    tree = ast.parse(source)
    bound = set(dir(builtins))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)

    used = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return used - bound


def test_deterministic_template_is_valid_python():
    script = generate_deterministic_pyvista_script(
        foam_file="cavity.foam", output_png="visualization.png"
    )

    compile(script, "<template>", "exec")


def test_deterministic_template_uses_no_name_it_does_not_define():
    script = generate_deterministic_pyvista_script(
        foam_file="cavity.foam", output_png="visualization.png"
    )

    assert _undefined_names(script) == set()


def test_deterministic_template_writes_the_requested_file():
    script = generate_deterministic_pyvista_script(
        foam_file="cavity.foam", output_png="my_output.png"
    )

    assert "'my_output.png'" in script
    assert "plotter.screenshot(out_png)" in script


def test_deterministic_template_renders_off_screen():
    script = generate_deterministic_pyvista_script(
        foam_file="cavity.foam", output_png="visualization.png"
    )

    assert "off_screen=True" in script


# ---------------------------------------------------------------------------
# The output-file contract in the LLM prompts (defect 6)
# ---------------------------------------------------------------------------


class _RecordingLLM:
    """Stands in for the LLM service and remembers what it was asked."""

    def __init__(self, reply="print('hi')"):
        self.reply = reply
        self.calls = []

    def invoke(self, prompt, system_prompt=None):
        self.calls.append((prompt, system_prompt))
        return self.reply


@pytest.fixture
def recording_llm(monkeypatch):
    llm = _RecordingLLM()
    monkeypatch.setattr(visualization, "get_llm_service", lambda: llm)
    return llm


def test_generate_prompt_names_the_expected_output_file(recording_llm):
    visualization.generate_pyvista_script(
        case_dir="/case",
        foam_file="cavity.foam",
        user_requirement="velocity",
        previous_errors=[],
        output_png="visualization.png",
    )

    prompt, system_prompt = recording_llm.calls[0]
    assert "<output_png>visualization.png</output_png>" in prompt
    assert "output_png" in system_prompt


def test_fix_prompt_names_the_expected_output_file(recording_llm):
    visualization.fix_pyvista_script(
        foam_file="cavity.foam",
        original_script="print('x')",
        error_logs=["boom"],
        output_png="visualization.png",
    )

    prompt, system_prompt = recording_llm.calls[0]
    assert "<output_png>visualization.png</output_png>" in prompt
    assert "output_png" in system_prompt


def test_generated_prompt_default_matches_the_file_the_runner_checks(recording_llm):
    """The prompt default and the success check must name the same file."""
    visualization.generate_pyvista_script(
        case_dir="/case", foam_file="cavity.foam", user_requirement="velocity", previous_errors=[]
    )

    prompt, _ = recording_llm.calls[0]
    assert f"<output_png>{DEFAULT_OUTPUT_PNG}</output_png>" in prompt


# ---------------------------------------------------------------------------
# run_pyvista_script's success check (defect 5)
# ---------------------------------------------------------------------------


def test_runner_reports_failure_without_an_expected_file(tmp_path):
    """Calling without expected_png can never succeed; callers must always pass it."""
    ok, image, errors = visualization.run_pyvista_script(str(tmp_path), "pass")

    assert ok is False
    assert image == ""
    assert any("expected_png" in e for e in errors)


def test_runner_succeeds_when_the_expected_file_appears(tmp_path):
    script = "open('visualization.png', 'wb').write(b'x' * 16)\n"

    ok, image, errors = visualization.run_pyvista_script(
        str(tmp_path), script, expected_png="visualization.png"
    )

    assert ok is True
    assert image == str((tmp_path / "visualization.png").resolve())
    assert errors == []


def test_runner_fails_when_the_script_writes_a_differently_named_file(tmp_path):
    """The failure mode defect 6 caused: a good image under the wrong name."""
    script = "open('velocity_magnitude.png', 'wb').write(b'x' * 16)\n"

    ok, image, errors = visualization.run_pyvista_script(
        str(tmp_path), script, expected_png="visualization.png"
    )

    assert ok is False
    assert any("expected PNG was not created" in e for e in errors)


# ---------------------------------------------------------------------------
# visualize_case's attempt order
# ---------------------------------------------------------------------------


@pytest.fixture
def case_dir(tmp_path):
    (tmp_path / "0").mkdir()
    return tmp_path


def test_a_working_template_needs_no_model_call(case_dir, monkeypatch):
    calls = []

    def fake_run(case, script, *, filename="visualization.py", expected_png=None, timeout_s=180):
        calls.append(filename)
        return True, str(case_dir / expected_png), []

    monkeypatch.setattr(visualization, "run_pyvista_script", fake_run)
    monkeypatch.setattr(
        visualization,
        "get_llm_service",
        lambda: pytest.fail("visualize_case called the LLM although the template worked"),
    )

    result = visualize_case(str(case_dir), "show the velocity field")

    assert result.success is True
    assert result.used == "deterministic_template"
    assert calls == ["visualization.py"]


def test_the_llm_path_runs_when_the_template_fails(case_dir, monkeypatch, recording_llm):
    attempts = []

    def fake_run(case, script, *, filename="visualization.py", expected_png=None, timeout_s=180):
        attempts.append(filename)
        if filename == "visualization.py":
            return False, "", ["template failed"]
        return True, str(case_dir / expected_png), []

    monkeypatch.setattr(visualization, "run_pyvista_script", fake_run)

    result = visualize_case(str(case_dir), "show the velocity field")

    assert result.success is True
    assert result.used == "llm_script"
    assert attempts == ["visualization.py", "visualization_llm.py"]


def test_skipping_the_template_reaches_the_llm_path_directly(case_dir, monkeypatch, recording_llm):
    attempts = []

    def fake_run(case, script, *, filename="visualization.py", expected_png=None, timeout_s=180):
        attempts.append(filename)
        return True, str(case_dir / expected_png), []

    monkeypatch.setattr(visualization, "run_pyvista_script", fake_run)

    result = visualize_case(str(case_dir), "show the velocity field", use_deterministic=False)

    assert result.success is True
    assert result.used == "llm_script"
    assert attempts == ["visualization_llm.py"]


def test_every_attempt_checks_the_same_output_file(case_dir, monkeypatch, recording_llm):
    seen = []

    def fake_run(case, script, *, filename="visualization.py", expected_png=None, timeout_s=180):
        seen.append(expected_png)
        return False, "", ["nope"]

    monkeypatch.setattr(visualization, "run_pyvista_script", fake_run)

    result = visualize_case(str(case_dir), "velocity", max_loop=2)

    assert result.success is False
    assert seen  # attempts were made
    assert set(seen) == {DEFAULT_OUTPUT_PNG}


def test_a_total_failure_reports_the_collected_errors(case_dir, monkeypatch, recording_llm):
    def fake_run(case, script, *, filename="visualization.py", expected_png=None, timeout_s=180):
        return False, "", [f"{filename} failed"]

    monkeypatch.setattr(visualization, "run_pyvista_script", fake_run)

    result = visualize_case(str(case_dir), "velocity", max_loop=1)

    assert isinstance(result, VisualizationResult)
    assert result.success is False
    assert result.output_image == ""
    assert "visualization.py failed" in result.error_logs
    assert "visualization_llm.py failed" in result.error_logs


# ---------------------------------------------------------------------------
# Field heuristic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "requirement,expected",
    [
        ("visualize the pressure field", "p"),
        ("show the temperature distribution", "T"),
        ("plot the velocity magnitude", "U"),
        ("", "U"),
    ],
)
def test_guess_primary_field(requirement, expected):
    assert guess_primary_field(requirement) == expected
