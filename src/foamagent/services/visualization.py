"""Rendering a screenshot of a finished case with PyVista.

One deterministic template, no model. The LLM script-generation fallback went with the
in-process pipeline: an agent that wants a different view writes its own PyVista script
and runs it with its own tools.
"""

import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from foamagent.logger import get_logger
from foamagent.utils import save_file

logger = get_logger(__name__)

# Every path through this module writes its screenshot here, relative to the case directory.
# run_pyvista_script() then checks for exactly this file to decide whether the attempt
# worked.
DEFAULT_OUTPUT_PNG = "visualization.png"


def ensure_foam_file(case_dir: str) -> str:
    """Ensure a .foam file exists in the case directory for OpenFOAM visualization.

    PyVista's OpenFOAMReader recognises a case by this marker file, so it is created (or
    its timestamp refreshed) before any rendering attempt.

    Args:
        case_dir (str): Directory path containing the OpenFOAM case

    Returns:
        str: Name of the .foam file (typically "{case_name}.foam")
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


def run_pyvista_script(
    case_dir: str,
    script: str,
    *,
    filename: str = "visualization.py",
    expected_png: Optional[str] = None,
    timeout_s: int = 180,
) -> Tuple[bool, str, List[str]]:
    """Run a visualization script deterministically.

    Key behaviors (to avoid flaky bugs):
      - If expected_png is provided, we only consider success if that file exists after execution.
      - Apply a timeout so headless/VTK hangs don't block forever.
    """
    case_dir = os.path.abspath(case_dir)
    script_path = os.path.join(case_dir, filename)
    save_file(script_path, script)

    expected_png_abs = os.path.abspath(os.path.join(case_dir, expected_png)) if expected_png else None

    try:
        subprocess.run(
            [sys.executable, script_path],
            cwd=case_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # See channel.py: a child that inherits this server's stdin reads the pipe the
            # harness is talking to it on.
            stdin=subprocess.DEVNULL,
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
    output_png: str = DEFAULT_OUTPUT_PNG,
    timeout_s: int = 180,
) -> VisualizationResult:
    """Produce one screenshot of a finished case with the fixed template.

    The attempt is checked against `output_png`, so a run either yields that file or
    reports why it did not.
    """
    case_dir = os.path.abspath(case_dir)
    foam_file = ensure_foam_file(case_dir)
    field_name = guess_primary_field(user_requirement)

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

    return VisualizationResult(
        success=False,
        field_name=field_name,
        script=script,
        error_logs=errs,
    )
