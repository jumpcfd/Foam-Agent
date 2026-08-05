#!/usr/bin/env python3
"""Compare a case against the published answer in its `reference.json`.

Nothing here is shown to the session that built the case, and nothing here reads what that
session claimed. The velocity field is sampled from the case's own last time and the
thicknesses and profiles are computed from it, so the comparison stands on the same
evidence a reader could recompute.

    python scripts/validation/check.py examples/validation/cavity_re100/result

Needs pyvista and numpy, which are the evaluator's dependencies rather than Foam-Agent's:

    uv run --with pyvista --with numpy python scripts/validation/check.py <case>
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

REFERENCE = "reference.json"
COMPARISON = "comparison.json"


# ---------------------------------------------------------------------------
# Reading the case
# ---------------------------------------------------------------------------


def open_case(case_dir: Path):
    """The case at its last written time, as a PyVista mesh with point data."""
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


def sample_line(block, start, end, points: int = 400):
    """Velocity along a straight line, as (coordinates, U) arrays.

    Only the points that landed inside the mesh are returned. The probe filter writes a
    zero rather than a gap for a point it missed, and a zero velocity is indistinguishable
    from a wall, so the validity mask has to be read rather than the values inspected.
    """
    import numpy as np

    line = block.sample_over_line(start, end, resolution=points - 1)
    U = np.asarray(line["U"])
    coords = np.asarray(line.points)
    mask = line.point_data.get("vtkValidPointMask")
    if mask is not None:
        inside = np.asarray(mask).astype(bool)
        coords, U = coords[inside], U[inside]
    return coords, U


def integrate(y, x):
    """np.trapezoid, under whichever name this NumPy has."""
    import numpy as np

    return (np.trapezoid if hasattr(np, "trapezoid") else np.trapz)(y, x)


# ---------------------------------------------------------------------------
# The three kinds of comparison
# ---------------------------------------------------------------------------


def compare_profile(case_dir: Path, reference: dict) -> dict:
    """A velocity component against a table of published values along a line."""
    import numpy as np

    block, time = open_case(case_dir)
    bounds = block.bounds
    z = 0.5 * (bounds[4] + bounds[5])
    x = 0.5 * (bounds[0] + bounds[1])
    coords, U = sample_line(block, (x, bounds[2], z), (x, bounds[3], z))

    height = bounds[3] - bounds[2]
    y = (coords[:, 1] - bounds[2]) / height
    ux = U[:, 0]
    if len(y) < 2:
        raise SystemExit(f"The centreline of {case_dir} sampled {len(y)} points.")

    rows = []
    for y_ref, u_ref in reference["points"]:
        u_case = float(np.interp(y_ref, y, ux))
        rows.append({"y": y_ref, "reference": u_ref, "case": round(u_case, 5),
                     "difference": round(u_case - u_ref, 5)})

    errors = [row["difference"] for row in rows]
    rms = math.sqrt(sum(e * e for e in errors) / len(errors))
    limit = reference["comparison"]["agreement"]["rms"]
    return {
        "time": time,
        "profile": rows,
        "rms": round(rms, 5),
        "max_absolute": round(max(abs(e) for e in errors), 5),
        "limit_rms": limit,
        "agrees": rms <= limit,
    }


def compare_boundary_layer(case_dir: Path, reference: dict) -> dict:
    """Boundary-layer thicknesses at a few stations against the similarity solution."""
    import numpy as np

    block, time = open_case(case_dir)
    bounds = block.bounds
    z = 0.5 * (bounds[4] + bounds[5])
    free_stream = reference["flow"]["free_stream"]
    nu = reference["flow"]["viscosity"]
    coefficients = reference["comparison"]["coefficients"]
    tolerance = reference["comparison"]["agreement"]["relative"]

    # The plate's leading edge is where the no-slip wall starts, which is not necessarily
    # the domain's inlet: the request asks for the edge to be set back from it. Take it as
    # the smallest x at which the wall velocity has been brought to zero.
    wall_y = bounds[2]
    leading_edge = find_leading_edge(block, wall_y, z, free_stream)

    stations = []
    for station in reference["comparison"]["stations"]:
        x = leading_edge + station
        coords, U = sample_line(block, (x, wall_y, z), (x, bounds[3], z), points=800)
        height = coords[:, 1] - wall_y
        u = U[:, 0]

        delta99 = float(np.interp(0.99 * free_stream, u, height))
        # Integrated over the sampled profile: displacement and momentum thickness.
        ratio = np.clip(u / free_stream, 0.0, 1.5)
        within = height <= 3 * delta99
        displacement = float(integrate(1.0 - ratio[within], height[within]))
        momentum = float(integrate(ratio[within] * (1.0 - ratio[within]), height[within]))

        re_x = free_stream * station / nu
        expected = {
            "delta99": coefficients["delta99"] * station / math.sqrt(re_x),
            "theta": coefficients["theta"] * station / math.sqrt(re_x),
            "shape_factor": coefficients["shape_factor"],
        }
        found = {
            "delta99": delta99,
            "theta": momentum,
            "shape_factor": displacement / momentum if momentum > 0 else float("nan"),
        }
        stations.append({
            "x": station,
            "Re_x": round(re_x),
            **{
                name: {
                    "reference": round(expected[name], 6),
                    "case": round(found[name], 6),
                    "relative": round(found[name] / expected[name] - 1.0, 4),
                }
                for name in expected
            },
        })

    worst = max(
        abs(entry[name]["relative"])
        for entry in stations
        for name in ("delta99", "theta", "shape_factor")
    )
    return {
        "time": time,
        "leading_edge_x": round(leading_edge, 4),
        "stations": stations,
        "worst_relative": round(worst, 4),
        "limit_relative": tolerance,
        "agrees": worst <= tolerance,
    }


def find_leading_edge(block, wall_y, z, free_stream) -> float:
    """The smallest x at which the bottom boundary is a no-slip wall.

    Sampled just above the boundary rather than on it, because a point exactly on a
    boundary face is as likely to pick up the free stream as the wall.
    """
    import numpy as np

    bounds = block.bounds
    offset = 0.001 * (bounds[3] - bounds[2])
    coords, U = sample_line(
        block, (bounds[0], wall_y + offset, z), (bounds[1], wall_y + offset, z), points=2000
    )
    u = U[:, 0]
    slowed = np.where(u < 0.5 * free_stream)[0]
    return float(coords[slowed[0], 0]) if len(slowed) else float(bounds[0])


def compare_range(case_dir: Path, reference: dict) -> dict:
    """Scalars the case reports, against the range published for them.

    The drag coefficient and the shedding frequency are recomputed here from the
    coefficient history OpenFOAM wrote, not taken from the session's own results.json.
    That file is read too, and any disagreement between the two is reported: a case whose
    claim does not match its own output is a finding in itself.
    """
    measured, detail = coefficients_from_history(case_dir)
    claimed = {}
    claim_file = case_dir / "results.json"
    if claim_file.is_file():
        try:
            claimed = json.loads(claim_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            claimed = {}

    quantities, agrees = {}, True
    for name, band in reference["comparison"]["quantities"].items():
        value = measured.get(name)
        if value is None:
            quantities[name] = {"case": None, "range": [band["low"], band["high"]],
                                "inside": False, "note": "not measurable from the case"}
            agrees = False
            continue
        inside = band["low"] <= value <= band["high"]
        distance = 0.0 if inside else min(abs(value - band["low"]), abs(value - band["high"]))
        quantities[name] = {
            "case": round(value, 4),
            "claimed": claimed.get(name),
            "range": [band["low"], band["high"]],
            "inside": inside,
            "outside_by": round(distance, 4),
        }
        agrees = agrees and inside

    return {"quantities": quantities, "measurement": detail, "agrees": agrees}


def coefficients_from_history(case_dir: Path) -> tuple[dict, dict]:
    """Mean Cd and the Strouhal number, read out of forceCoeffs' own output.

    OpenFOAM 10 writes `coefficient.dat`; older and newer versions write
    `forceCoeffs.dat`. Both are whitespace-separated with a `#` header naming the columns,
    so the columns are found by name rather than by position.

    Plain arithmetic on purpose: this is a mean and a count of sign changes, and keeping it
    off numpy means it can be tested in this project's own environment rather than only
    where the evaluator's dependencies happen to be installed.
    """
    files = sorted(case_dir.glob("postProcessing/*/*/coefficient*.dat"))
    files += sorted(case_dir.glob("postProcessing/*/*/forceCoeffs*.dat"))
    if not files:
        return {}, {"note": "no forceCoeffs output under postProcessing/"}

    times, columns = [], {}
    header = []
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

    if not times or "Cd" not in columns or "Cl" not in columns:
        return {}, {"note": f"{len(times)} rows read, columns {sorted(columns)}"}

    # The transient is discarded by taking the last half of the history, and the average is
    # then taken over a whole number of shedding cycles found from the lift signal.
    half = len(times) // 2
    time, cd, cl = times[half:], columns["Cd"][half:], columns["Cl"][half:]

    level = sum(cl) / len(cl)
    crossings = [
        i for i in range(len(cl) - 1)
        if cl[i] <= level < cl[i + 1]
    ]
    if len(crossings) < 3:
        return {"Cd_mean": sum(cd) / len(cd)}, {
            "note": "fewer than two complete shedding cycles after the transient",
            "window": [time[0], time[-1]],
        }

    first, last = crossings[0], crossings[-1]
    period = (time[last] - time[first]) / (len(crossings) - 1)
    window = cd[first:last]
    lift = cl[first:last]
    return (
        {"Cd_mean": sum(window) / len(window), "St": 1.0 / period},
        {
            "window": [time[first], time[last]],
            "cycles": len(crossings) - 1,
            "period": round(period, 4),
            "Cl_amplitude": round((max(lift) - min(lift)) / 2, 4),
        },
    )


COMPARISONS = {
    "profile": compare_profile,
    "boundary_layer": compare_boundary_layer,
    "range": compare_range,
}


# ---------------------------------------------------------------------------


def find_reference(case_dir: Path) -> Path:
    """`reference.json` beside the case, or one directory up when the case is `result/`."""
    for candidate in (case_dir / REFERENCE, case_dir.parent / REFERENCE):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"No {REFERENCE} beside {case_dir} or its parent.")


def write_profile_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("case_dir", type=Path, help="The case to check.")
    parser.add_argument("--reference", type=Path, default=None,
                        help=f"The {REFERENCE} to check against (default: beside the case, "
                             "or one directory up).")
    parser.add_argument("--out", type=Path, default=None,
                        help=f"Where to write {COMPARISON} (default: beside the case).")
    args = parser.parse_args(argv)

    case_dir = args.case_dir.resolve()
    reference_file = args.reference or find_reference(case_dir)
    reference = json.loads(reference_file.read_text(encoding="utf-8"))
    kind = reference["comparison"]["kind"]
    if kind not in COMPARISONS:
        raise SystemExit(f"Unknown comparison kind {kind!r} in {reference['case']}.")

    result = COMPARISONS[kind](case_dir, reference)
    result = {"case": reference["case"], "title": reference["title"],
              "source": reference["source"]["citation"], **result}

    destination = args.out or case_dir
    destination.mkdir(parents=True, exist_ok=True)
    (destination / COMPARISON).write_text(json.dumps(result, indent=2), encoding="utf-8")
    if "profile" in result:
        write_profile_csv(destination / "profile.csv", result["profile"])

    print(json.dumps({k: v for k, v in result.items() if k != "profile"}, indent=2))
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    sys.exit(main())
