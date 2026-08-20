"""Rendering a screenshot of a finished case with PyVista.

One deterministic template, no model. The LLM script-generation fallback went with the
in-process pipeline: an agent that wants a different view writes its own PyVista script
and runs it with its own tools.
"""

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from foamagent.logger import get_logger

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
    expected_png: str,
    filename: str = "visualization.py",
    timeout_s: int = 180,
) -> Tuple[bool, str, List[str]]:
    """Run a visualization script and say whether it produced ``expected_png``.

    Naming the file is what makes the attempt checkable: a script can exit zero and write
    nothing, or write a good image under a name nobody looks for. The timeout is there
    because a headless VTK can hang rather than fail.
    """
    case_dir = os.path.abspath(case_dir)
    script_path = os.path.join(case_dir, filename)
    Path(script_path).write_text(script, encoding="utf-8")

    expected_png_abs = os.path.abspath(os.path.join(case_dir, expected_png))

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

        if os.path.exists(expected_png_abs) and os.path.getsize(expected_png_abs) > 0:
            return True, expected_png_abs, []
        return False, "", [
            "Visualization script executed but expected PNG was not created",
            f"expected_png={expected_png_abs}",
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
        if e.returncode < 0:
            # A negative returncode means the interpreter was killed by a signal (VTK
            # segfaulting on a missing X11/OpenGL library is the common case in a headless
            # container, not a broken PyVista install -- reinstalling the `viz` extra does
            # not fix this).
            error_msg += (
                "\n\nThe script was killed by a signal, not a Python exception -- this "
                "usually means VTK crashed trying to open a display. On a headless host "
                "(container, CI, SSH without X forwarding), install the OS packages VTK's "
                "off-screen rendering needs, e.g. on Debian/Ubuntu: "
                "`apt-get install -y xvfb libgl1-mesa-glx libxrender1 libxext6 libsm6`."
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
    # ponytail: some pyvista versions expose OFF_SCREEN as read-only; the env var set
    # above already forces headless mode, so this is belt-and-suspenders, not required.
    pass

try:
    pv.start_xvfb()
except Exception:
    # ponytail: start_xvfb is optional and may be unavailable (e.g. already running,
    # or a non-Linux host); rendering still works without it wherever a display exists.
    pass

foam_path = os.path.abspath({foam_file!r})
out_png = os.path.abspath({output_png!r})

reader = pv.OpenFOAMReader(foam_path)
# Many OpenFOAM readers expose available times; use the last one when present
try:
    reader.set_active_time_value(reader.time_values[-1])
except Exception:
    # ponytail: if this fails the reader keeps whatever time step it defaults to
    # (usually the first), so the script still produces a picture, just not of the
    # latest solved time.
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
        # ponytail: neither combine() nor indexing worked, so mesh is left as the raw
        # MultiBlock; add_mesh() below still accepts it, just without a merged surface.
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
    # ponytail: mesh may not expose point_data/cell_data at all (e.g. still a raw
    # MultiBlock); scalar_name stays None and the fallbacks below try again.
    pass

if scalar_name is None:
    # pick any available scalar
    try:
        keys = list(getattr(mesh, 'point_data', {{}}).keys())
        scalar_name = keys[0] if keys else None
    except Exception:
        # ponytail: same as above -- leave scalar_name unset and fall through to the
        # cell_data attempt, then finally to the uncoloured plot below.
        scalar_name = None

if scalar_name is None:
    try:
        keys = list(getattr(mesh, 'cell_data', {{}}).keys())
        scalar_name = keys[0] if keys else None
    except Exception:
        # ponytail: last fallback exhausted; add_mesh() below plots without a scalar
        # when scalar_name is still None, so this never blocks the screenshot.
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
    """Which field to colour by, from what the user asked for.

    Velocity is the answer to anything that does not name pressure or temperature, which
    is what the previous last two conditions came to: `"u" in text.lower()` is true of
    almost any English sentence.
    """
    text = (user_requirement or "").lower()
    if " p " in f" {text} " or "pressure" in text:
        return "p"
    if "temperature" in text:
        return "T"
    return "U"


@dataclass
class VisualizationResult:
    """Outcome of visualizing one case."""

    success: bool
    field_name: str
    output_image: str = ""
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
            success=True, field_name=field_name, output_image=output_image
        )

    return VisualizationResult(success=False, field_name=field_name, error_logs=errs)
