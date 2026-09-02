#!/usr/bin/env python3
"""Compare a case against the published answer in its `reference.json`.

Nothing here is shown to the session that built the case, and nothing here reads what that
session claimed. The velocity field is sampled from the case's own last time and the
thicknesses and profiles are computed from it, so the comparison stands on the same
evidence a reader could recompute.

`run.py` calls this automatically against the workspace it just built, before its own
`collect()` step strips the mesh out of `examples/validation/<case>/result/` -- the mesh
regenerates from `Allrun`, so it is not committed, but that also means `result/` alone has
no field data for a `profile` or `boundary_layer` comparison to read. Pointed at `result/`
directly, only a `range` comparison (reads `postProcessing/`, not the mesh) can succeed; the
other two need a directory the mesh is still in, e.g. the original build under
`~/foamagent-validation/<case>/`, or a fresh `Allrun` run in a scratch copy of `result/`.

    uv run --with pyvista --with numpy python -m foamagent.validation.check <built case dir>

Needs pyvista and numpy, which are the evaluator's dependencies rather than Foam-Agent's.

A case whose comparison does not fit `profile`, `boundary_layer` or `range` can supply its
own `check.py` beside `request.md` instead (see `run.run_comparison`). The reusable case
readers and numeric helpers live in `foamagent.validation.primitives`; they are re-exported
from this module for compatibility with existing case-local checkers.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

from foamagent.validation.primitives import (
    coefficients_from_history,
    find_leading_edge,
    integrate,
    open_case,
    sample_line,
    steady_window_mean,
    wall_patch_names,
)

REFERENCE = "reference.json"
COMPARISON = "comparison.json"


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
    # the domain's inlet: the request asks for the edge to be set back from it.
    wall_y = bounds[2]
    leading_edge = find_leading_edge(case_dir)

    stations = []
    for station in reference["comparison"]["stations"]:
        x = leading_edge + station
        re_x = free_stream * station / nu
        expected = {
            "delta99": coefficients["delta99"] * station / math.sqrt(re_x),
            "theta": coefficients["theta"] * station / math.sqrt(re_x),
            "shape_factor": coefficients["shape_factor"],
        }

        # A line sampled at fixed resolution all the way to the domain top spaces its
        # points by millimetres over metres -- fine for delta99 (one crossing, found by
        # interpolation) but far too coarse for the integrals below, which need to resolve
        # the profile's shape *inside* a layer that is itself a few millimetres thick. Sample
        # densely over a multiple of the layer's expected thickness instead of the whole
        # domain; the multiple is generous because a real profile can run thicker than the
        # similarity solution before this same sampling narrows in on it.
        sample_top = min(bounds[3], wall_y + 8 * expected["delta99"])
        coords, U = sample_line(block, (x, wall_y, z), (x, sample_top, z), points=2000)
        height = coords[:, 1] - wall_y
        u = U[:, 0]

        delta99 = float(np.interp(0.99 * free_stream, u, height))
        # Integrated over the sampled profile: displacement and momentum thickness.
        ratio = np.clip(u / free_stream, 0.0, 1.5)
        within = height <= 3 * delta99
        displacement = float(integrate(1.0 - ratio[within], height[within]))
        momentum = float(integrate(ratio[within] * (1.0 - ratio[within]), height[within]))
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
            # ponytail: a malformed results.json is treated as "nothing claimed" rather
            # than raising. The `agrees` verdict below is driven entirely by `measured`
            # (recomputed from the coefficient history), so this only drops the
            # claimed-vs-measured cross-check for this one case, not the verdict itself.
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
