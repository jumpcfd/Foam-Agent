"""Small, reusable readers and numeric helpers for case-local checkers.

These functions deliberately know how to read an OpenFOAM case but do not decide whether a
case agrees with a reference. Case-specific checkers compose them with their own physics and
tolerances.
"""

from __future__ import annotations

import statistics
from pathlib import Path


def open_case(case_dir: Path):
    """The case at its last written time, as a PyVista mesh with point data."""
    if not (case_dir / "constant" / "polyMesh").is_dir():
        raise SystemExit(f"{case_dir} has no constant/polyMesh -- blockMesh was never run.")

    import pyvista as pv

    marker = next(case_dir.glob("*.foam"), None) or (case_dir / "case.foam")
    if not marker.is_file():
        marker.write_text("", encoding="utf-8")

    reader = pv.OpenFOAMReader(str(marker))
    times = list(reader.time_values)
    if not times:
        raise SystemExit(f"{case_dir} has no time directories to read.")
    reader.set_active_time_value(times[-1])
    reader.cell_to_point_creation = True

    mesh = reader.read()
    block = mesh["internalMesh"] if "internalMesh" in mesh.keys() else mesh[0]
    return block, times[-1]


def sample_line(block, start, end, points: int = 400, fields=("U",)):
    """One or more fields along a straight line, as (coordinates, values) arrays.

    With the default `fields=("U",)`, `values` is the velocity array, exactly as before this
    parameter existed. Passing a different tuple of field names returns `values` as a dict of
    arrays keyed by field name.
    """
    import numpy as np

    line = block.sample_over_line(start, end, resolution=points - 1)
    values = {name: np.asarray(line[name]) for name in fields}
    coords = np.asarray(line.points)
    mask = line.point_data.get("vtkValidPointMask")
    if mask is not None:
        inside = np.asarray(mask).astype(bool)
        coords = coords[inside]
        values = {name: array[inside] for name, array in values.items()}
    if fields == ("U",):
        return coords, values["U"]
    return coords, values


def integrate(y, x):
    """np.trapezoid, under whichever name this NumPy has."""
    import numpy as np

    return (np.trapezoid if hasattr(np, "trapezoid") else np.trapz)(y, x)


def wall_patch_names(case_dir: Path) -> list[str]:
    """Every patch `constant/polyMesh/boundary` declares `type wall;` for."""
    import re

    text = (case_dir / "constant" / "polyMesh" / "boundary").read_text(
        encoding="utf-8", errors="replace"
    )
    return re.findall(r"(\S+)\s*\{\s*type\s+wall\s*;", text)


def find_leading_edge(case_dir: Path) -> float:
    """The smallest x any no-slip wall patch reaches.

    This reads the wall patch geometry rather than inferring the leading edge from a velocity
    threshold at a fixed height, which can be downstream of a thin boundary layer's actual
    start.
    """
    import pyvista as pv

    walls = set(wall_patch_names(case_dir))
    if not walls:
        raise SystemExit(f"{case_dir}'s polyMesh/boundary declares no wall-type patch.")

    marker = next(case_dir.glob("*.foam"), None) or (case_dir / "case.foam")
    if not marker.is_file():
        marker.write_text("", encoding="utf-8")
    reader = pv.OpenFOAMReader(str(marker))
    reader.enable_all_patch_arrays()
    times = list(reader.time_values)
    reader.set_active_time_value(times[-1])
    boundary = reader.read()["boundary"]

    minima = [
        float(boundary[name].points[:, 0].min())
        for name in boundary.keys()
        if name in walls and boundary[name] is not None and boundary[name].n_points
    ]
    if not minima:
        raise SystemExit(f"{case_dir}: none of {sorted(walls)} came back with points.")
    return min(minima)


def _read_coefficient_history(case_dir: Path) -> tuple[list[float], dict[str, list[float]]]:
    """Read coefficient history files under `postProcessing/` by their header names."""
    files = sorted(case_dir.glob("postProcessing/*/*/coefficient*.dat"))
    files += sorted(case_dir.glob("postProcessing/*/*/forceCoeffs*.dat"))

    times: list[float] = []
    columns: dict[str, list[float]] = {}
    header: list[str] = []
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("#"):
                fields = line.lstrip("#").split()
                if "Cd" in fields or "Cd(f)" in fields or "Cl" in fields:
                    header = fields
                continue
            values = line.split()
            if not header or len(values) != len(header):
                continue
            times.append(float(values[0]))
            for name, value in zip(header, values):
                columns.setdefault(name, []).append(float(value))
    return times, columns


def steady_window_mean(case_dir: Path, tail_fraction: float = 0.25) -> dict | None:
    """Mean Cl/Cd over the trailing `tail_fraction`, with coefficient of variation."""
    times, columns = _read_coefficient_history(case_dir)
    if not times or "Cl" not in columns or "Cd" not in columns:
        return None

    tail = max(1, int(len(times) * tail_fraction))
    result = {"n_rows": len(times), "tail_rows": tail, "window": [times[-tail], times[-1]]}
    for name in ("Cl", "Cd"):
        window = columns[name][-tail:]
        mean = statistics.fmean(window)
        variance = sum((v - mean) ** 2 for v in window) / len(window)
        result[name] = mean
        result[f"{name}_cv"] = (variance**0.5 / abs(mean)) if mean else None
    return result


def coefficients_from_history(case_dir: Path) -> tuple[dict, dict]:
    """Read mean Cd and Strouhal number from a force-coefficient history."""
    times, columns = _read_coefficient_history(case_dir)
    if not times:
        return {}, {"note": "no forceCoeffs output under postProcessing/"}

    if "Cd" not in columns or "Cl" not in columns:
        return {}, {"note": f"{len(times)} rows read, columns {sorted(columns)}"}

    half = len(times) // 2
    time, cd, cl = times[half:], columns["Cd"][half:], columns["Cl"][half:]
    level = statistics.fmean(cl)
    crossings = [
        i for i in range(len(cl) - 1)
        if cl[i] <= level < cl[i + 1]
    ]
    if len(crossings) < 3:
        return {"Cd_mean": statistics.fmean(cd)}, {
            "note": "fewer than two complete shedding cycles after the transient",
            "window": [time[0], time[-1]],
        }

    first, last = crossings[0], crossings[-1]
    period = (time[last] - time[first]) / (len(crossings) - 1)
    window = cd[first:last]
    lift = cl[first:last]
    return (
        {"Cd_mean": statistics.fmean(window), "St": 1.0 / period},
        {
            "window": [time[first], time[last]],
            "cycles": len(crossings) - 1,
            "period": round(period, 4),
            "Cl_amplitude": round((max(lift) - min(lift)) / 2, 4),
        },
    )


__all__ = [
    "coefficients_from_history",
    "find_leading_edge",
    "integrate",
    "open_case",
    "sample_line",
    "steady_window_mean",
    "wall_patch_names",
]
