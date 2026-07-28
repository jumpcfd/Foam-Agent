"""Tests for the generated PyVista template.

The template is source code for a separate interpreter, so nothing it references can come
from this package. These tests check that property directly, because a name that leaks in
from the generating module is invisible until the script runs.
"""

import ast
import builtins

from foamagent.services.visualization import generate_deterministic_pyvista_script


def _undefined_names(source: str):
    """Return the names a module-level script reads without ever binding."""
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
