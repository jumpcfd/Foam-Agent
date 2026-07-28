import os
import sys
import subprocess
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from foamagent.utils import save_file
from foamagent.services import get_llm_service

from foamagent.logger import get_logger

logger = get_logger(__name__)

# Every path through this module writes its screenshot here, relative to the case directory.
# run_pyvista_script() then checks for exactly this file to decide whether the attempt
# worked, so the generating prompts have to name it too -- see generate_pyvista_script().
DEFAULT_OUTPUT_PNG = "visualization.png"


def _strip_code_fences(text: str) -> str:
    """Remove Markdown code fences from an LLM response.

    The prompts ask for bare Python, but several models still wrap the answer in
    ```python ... ```. Saving that verbatim makes the script fail with a SyntaxError
    on its first line, so strip the fences before the script is written to disk.
    """
    if not isinstance(text, str):
        return text

    stripped = text.strip()
    if not stripped.startswith("```"):
        return text

    lines = stripped.splitlines()
    # Drop the opening fence (``` or ```python) and everything after the closing fence.
    lines = lines[1:]
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            lines = lines[:i]
            break

    return "\n".join(lines).strip() + "\n"


def ensure_foam_file(case_dir: str) -> str:
    """
    Ensure a .foam file exists in the case directory for OpenFOAM visualization.
    
    This function creates or updates a .foam file in the specified case directory.
    The .foam file is required for OpenFOAM visualization tools to recognize
    the directory as a valid OpenFOAM case.
    
    Args:
        case_dir (str): Directory path containing the OpenFOAM case
    
    Returns:
        str: Name of the .foam file (typically "{case_name}.foam")
    
    Raises:
        OSError: If directory cannot be accessed or file cannot be created
    
    Example:
        >>> foam_name = ensure_foam_file("/path/to/case")
        >>> logger.info(f"Foam file: {foam_name}")  # "case.foam"
    """
    case_dir = os.path.abspath(case_dir)
    foam = f"{os.path.basename(case_dir)}.foam"
    foam_path = os.path.join(case_dir, foam)
    
    # Create or update the .foam file
    if not os.path.exists(foam_path):
        with open(foam_path, 'w') as f:
            pass
    else:
        # Update timestamp if file exists
        os.utime(foam_path, None)
    
    return foam


def generate_pyvista_script(
    case_dir: str,
    foam_file: str,
    user_requirement: str,
    previous_errors: List[str],
    output_png: str = DEFAULT_OUTPUT_PNG,
) -> str:
    """
    Generate PyVista visualization script for OpenFOAM case using LLM.

    This function uses LLM to generate a Python script that uses PyVista
    to visualize OpenFOAM simulation results. The script loads the .foam file,
    renders geometry with appropriate coloring, and saves visualization images.

    The output file name is part of the contract: the caller decides whether an attempt
    succeeded by looking for exactly `output_png`, so the prompt states that name instead of
    leaving the model to invent one. Without this the model picks a descriptive name of its
    own, the file check misses it, and a perfectly good screenshot is reported as a failure.

    Args:
        case_dir (str): Directory path containing the OpenFOAM case
        foam_file (str): Name of the .foam file for the case
        user_requirement (str): User requirements for visualization context
        previous_errors (List[str]): List of previous visualization errors for context
        output_png (str): File name the script must write, relative to the case directory

    Returns:
        str: Generated Python script code for PyVista visualization

    Raises:
        RuntimeError: If LLM service fails to generate script

    Example:
        >>> script = generate_pyvista_script(
        ...     case_dir="/path/to/case",
        ...     foam_file="case.foam",
        ...     user_requirement="Visualize velocity field",
        ...     previous_errors=[]
        ... )
        >>> print("Generated PyVista script")
    """
    system_prompt = (
        "You are an expert in OpenFOAM post-processing and PyVista Python scripting. "
        "Generate a PyVista script that loads the .foam file, renders geometry colored by requested field, uses coolwarm colormap, and saves a PNG. "
        "Read the case with pyvista.OpenFOAMReader, which is the only OpenFOAM reader PyVista "
        "has; names such as FoamReader do not exist and fail on import. "
        "Render off-screen: the script runs headless, with no display attached. "
        "Save the image to exactly the file name given in <output_png>, resolved relative to "
        "the case directory, and write no other image. Do not choose a different name. "
        "Return ONLY Python code, no markdown."
    )
    prompt = (
        f"<case_directory>{case_dir}</case_directory>\n"
        f"<foam_file>{foam_file}</foam_file>\n"
        f"<output_png>{output_png}</output_png>\n"
        f"<visualization_requirements>{user_requirement}</visualization_requirements>\n"
        f"<previous_errors>{previous_errors}</previous_errors>\n"
    )
    return _strip_code_fences(get_llm_service().invoke(prompt, system_prompt))


def run_pyvista_script(
    case_dir: str,
    script: str,
    *,
    filename: str = "visualization.py",
    expected_png: Optional[str] = None,
    timeout_s: int = 180,
) -> Tuple[bool, str, List[str]]:
    """Run a generated visualization script deterministically.

    Key behaviors (to avoid flaky bugs):
      - If expected_png is provided, we only consider success if that file exists after execution.
      - Apply a timeout so headless/VTK hangs don't block forever.
    """
    case_dir = os.path.abspath(case_dir)
    script_path = os.path.join(case_dir, filename)
    save_file(script_path, script)

    expected_png_abs = os.path.abspath(os.path.join(case_dir, expected_png)) if expected_png else None

    try:
        completed = subprocess.run(
            [sys.executable, script_path],
            cwd=case_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
        )

        if expected_png_abs:
            if os.path.exists(expected_png_abs) and os.path.getsize(expected_png_abs) > 0:
                return True, expected_png_abs, []
            return False, "", [
                "Visualization script executed but expected PNG was not created",
                f"expected_png={expected_png_abs}",
            ]

        # Backward-compatible behavior (non-deterministic): no expected output specified.
        return False, "", [
            "Visualization script executed but no expected_png was specified; please pass expected_png for deterministic artifact detection"
        ]

    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else str(e.stdout)
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        return False, "", [
            f"PyVista script timed out after {timeout_s}s",
            f"STDOUT:\n{out}",
            f"STDERR:\n{err}",
        ]

    except subprocess.CalledProcessError as e:
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else str(e.stdout)
        error_msg = (
            f"PyVista script execution failed (exit code {e.returncode})\n"
            f"STDOUT:\n{out}\n"
            f"STDERR:\n{err}"
        )
        return False, "", [error_msg]

    except FileNotFoundError:
        return False, "", [f"Python interpreter not found: {sys.executable}"]

    except Exception as e:
        return False, "", [f"Unexpected error running visualization script: {str(e)}"]


def fix_pyvista_script(
    foam_file: str,
    original_script: str,
    error_logs: List[str],
    output_png: str = DEFAULT_OUTPUT_PNG,
) -> str:
    """Ask the model to repair a script that failed.

    Carries the same output file name as the generating prompt: one common reason a script
    reaches this function is that it wrote its image somewhere else, and a fix prompt that
    stays silent about the name cannot correct that.
    """
    system_prompt = (
        "You are an expert in PyVista visualization. Fix the provided script to load the .foam file, render geometry, and save a PNG with colorbar. "
        "Read the case with pyvista.OpenFOAMReader; no other OpenFOAM reader exists in PyVista. "
        "Render off-screen: the script runs headless, with no display attached. "
        "Save the image to exactly the file name given in <output_png>, resolved relative to "
        "the case directory, and write no other image. "
        "Return ONLY Python code."
    )
    prompt = (
        f"<error_logs>{error_logs}</error_logs>\n"
        f"<foam_file>{foam_file}</foam_file>\n"
        f"<output_png>{output_png}</output_png>\n"
        f"<original_script>{original_script}</original_script>\n"
    )
    return _strip_code_fences(get_llm_service().invoke(prompt, system_prompt))


def generate_deterministic_pyvista_script(
    *,
    foam_file: str,
    output_png: str,
    field_preference: str = "U",
) -> str:
    """Generate a minimal, deterministic PyVista script.

    Goals:
      - Works in headless environments (off-screen)
      - Always writes to output_png (relative to case_dir)
      - Tries to color by field_preference, but falls back to any available scalar
    """
    # The body below is source code for a separate process, not for this one. It has no
    # access to this module's imports, so every name it uses must be defined inside the
    # string itself -- in particular it must use print(), never this module's logger.
    return f"""import os
import sys

# Force headless rendering early
os.environ.setdefault('PYVISTA_OFF_SCREEN', 'true')

import pyvista as pv

try:
    pv.OFF_SCREEN = True
except Exception:
    pass

try:
    pv.start_xvfb()
except Exception:
    # start_xvfb is optional and may be unavailable
    pass

foam_path = os.path.abspath({foam_file!r})
out_png = os.path.abspath({output_png!r})

reader = pv.OpenFOAMReader(foam_path)
# Many OpenFOAM readers expose available times; use the last one when present
try:
    reader.set_active_time_value(reader.time_values[-1])
except Exception:
    pass

data = reader.read()

# data can be a MultiBlock; merge to a single mesh for robust plotting
mesh = data
try:
    if hasattr(data, 'combine'):
        mesh = data.combine()
except Exception:
    # fallback: try first block
    try:
        mesh = data[0]
    except Exception:
        mesh = data

# Determine a scalar to plot
scalar_name = None
preferred = {field_preference!r}

# Try point data first then cell data
try:
    if preferred in getattr(mesh, 'point_data', {{}}):
        scalar_name = preferred
    elif preferred in getattr(mesh, 'cell_data', {{}}):
        scalar_name = preferred
except Exception:
    pass

if scalar_name is None:
    # pick any available scalar
    try:
        keys = list(getattr(mesh, 'point_data', {{}}).keys())
        scalar_name = keys[0] if keys else None
    except Exception:
        scalar_name = None

if scalar_name is None:
    try:
        keys = list(getattr(mesh, 'cell_data', {{}}).keys())
        scalar_name = keys[0] if keys else None
    except Exception:
        scalar_name = None

plotter = pv.Plotter(off_screen=True)
plotter.set_background('white')

if scalar_name is not None:
    plotter.add_mesh(mesh, scalars=scalar_name, cmap='coolwarm', show_scalar_bar=True)
else:
    plotter.add_mesh(mesh, color='lightgray')

plotter.view_isometric()
plotter.show(auto_close=False)
plotter.screenshot(out_png)
plotter.close()

print('Wrote', out_png)
"""


def guess_primary_field(user_requirement: str) -> str:
    """Very small heuristic; keep deterministic and conservative."""
    if not user_requirement:
        return "U"
    text = user_requirement
    # Prefer explicit mentions
    if " p " in f" {text} " or "pressure" in text.lower():
        return "p"
    if "temperature" in text.lower():
        return "T"
    if "u" in text.lower() or "velocity" in text.lower():
        return "U"
    return "U"


@dataclass
class VisualizationResult:
    """Outcome of visualizing one case."""

    success: bool
    field_name: str
    output_image: str = ""
    script: str = ""
    used: str = ""
    error_logs: List[str] = field(default_factory=list)


def visualize_case(
    case_dir: str,
    user_requirement: str,
    *,
    max_loop: int = 2,
    output_png: str = DEFAULT_OUTPUT_PNG,
    timeout_s: int = 180,
    use_deterministic: bool = True,
) -> VisualizationResult:
    """Produce one screenshot of a finished case.

    Tries the fixed template first, because it needs no model call and always writes to the
    expected path, then falls back to generating and repairing a script with the LLM. Every
    attempt is checked against the same `output_png`, so a run either yields that file or
    reports why it did not.

    `use_deterministic=False` skips the template and exercises the LLM path alone. It exists
    for testing that path directly, which is otherwise unreachable whenever the template
    succeeds.
    """
    case_dir = os.path.abspath(case_dir)
    foam_file = ensure_foam_file(case_dir)
    field_name = guess_primary_field(user_requirement)
    error_logs: List[str] = []

    if use_deterministic:
        script = generate_deterministic_pyvista_script(
            foam_file=foam_file,
            output_png=output_png,
            field_preference=field_name,
        )
        success, output_image, errs = run_pyvista_script(
            case_dir,
            script,
            filename="visualization.py",
            expected_png=output_png,
            timeout_s=timeout_s,
        )
        if success and output_image:
            return VisualizationResult(
                success=True,
                field_name=field_name,
                output_image=output_image,
                script=script,
                used="deterministic_template",
            )
        error_logs.extend(errs)

    for attempt in range(1, max_loop + 1):
        logger.info(f"LLM visualization attempt {attempt} of {max_loop}")

        viz_script = generate_pyvista_script(
            case_dir, foam_file, user_requirement, error_logs[-2:], output_png=output_png
        )
        success, output_image, errs = run_pyvista_script(
            case_dir,
            viz_script,
            filename="visualization_llm.py",
            expected_png=output_png,
            timeout_s=timeout_s,
        )
        if success and output_image:
            return VisualizationResult(
                success=True,
                field_name=field_name,
                output_image=output_image,
                script=viz_script,
                used="llm_script",
            )
        error_logs.extend(errs)

        if attempt >= max_loop:
            break

        fixed_script = fix_pyvista_script(
            foam_file, viz_script, error_logs[-2:], output_png=output_png
        )
        success, output_image, errs = run_pyvista_script(
            case_dir,
            fixed_script,
            filename="visualization_fixed.py",
            expected_png=output_png,
            timeout_s=timeout_s,
        )
        if success and output_image:
            return VisualizationResult(
                success=True,
                field_name=field_name,
                output_image=output_image,
                script=fixed_script,
                used="llm_fixed_script",
            )
        error_logs.extend(errs)

    return VisualizationResult(
        success=False,
        field_name=field_name,
        error_logs=error_logs,
    )


