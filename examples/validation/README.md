# Validation cases

Three flows with a published or analytic answer, each set up and run from a plain English
request by a Claude Code session using this fork's MCP tools, and each checked afterwards
against the literature by a script the session never saw.

This is a demonstration, not a benchmark. There is no score here and nothing to optimise:
the point is that the requests, the cases the sessions produced, the reviews they were given
and the comparison against published data are all in this repository, so the claim can be
checked rather than believed.

| Case | Flow | Compared against |
|---|---|---|
| [cavity_re100](cavity_re100/) | Lid-driven cavity, Re = 100 | Ghia, Ghia & Shin (1982), Table I |
| [flat_plate_blasius](flat_plate_blasius/) | Laminar boundary layer on a flat plate | The Blasius similarity solution |
| [cylinder_re100](cylinder_re100/) | Vortex shedding behind a circular cylinder, Re = 100 | Published Cd and Strouhal number |

## What each directory holds

    request.md      the request, exactly as the session received it
    reference.json  the published values, their citation, and what counts as agreement
    result/         what the session produced, and how it compared

`result/` holds the case's input files (`0/`, `constant/`, `system/`, `Allrun`), the
session's own `spec.md`, the reviews it was given and its answers to them, its final report,
and `comparison.json` with the numbers side by side. The mesh and the fields are not
committed; `Allrun` regenerates them.

## Results

| Case | Comparison | Result |
|---|---|---|
| cavity_re100 | RMS deviation from Ghia's 17-point table | **Agrees** -- RMS 0.0022, limit 0.02 |
| flat_plate_blasius | delta99 / momentum thickness / shape factor at 3 stations, 10% each | **Does not agree** -- delta99 within 5-9% at every station, but momentum thickness is 11-17% low at all three, growing with distance from the leading edge |
| cylinder_re100 | Cd_mean and Strouhal number against published ranges | **Does not agree** -- Cd_mean 1.3798 (range 1.32-1.38); St 0.1687, 0.0007 above the range's 0.168 |

Two of three land on published values within the stated tolerance; the third comes close
enough to be informative about why it misses, which is what a comparison this size is for.
The full numbers, and each case's own account of what its result does and does not establish,
are in `result/comparison.json` and `result/report.md`.

**flat_plate_blasius**, read alongside `result/spec.md`: the momentum-thickness miss grows
with x (from the leading edge outward) rather than shrinking, which points at the finite
domain height (3 plate lengths) rather than at near-wall mesh resolution -- a Blasius profile
assumes an unbounded free stream, and a bounded one accelerates slightly as the boundary
layer's displacement effect grows, thinning what gets measured relative to the idealized
solution the farther downstream the station sits.

**cylinder_re100**, read alongside `result/review-3.md`: the reviewer traced Cd_mean and St
by hand from the raw force-coefficient history and reproduced both numbers exactly, and
found the run held a peak local Courant number of about 2 against `spec.md`'s stated
adaptive scheme (max Courant 1) for most of the run -- noted as an open sensitivity question
in `result/response-3.md`, not one this run settled.

## The session did not see the answer

The reference values live in `reference.json` in this repository, and the sessions ran in a
working directory outside it. This is not a formality. The first FoamBench run here put the
submission next to the reference case, and two sessions in sixteen read the reference and
recorded in their own notes that they had -- not deceit, just a directory that was there to
be listed. The requests below say what flow to compute and against what kind of data it will
be checked, and nothing about the values.

## Reproducing

```bash
python -m foamagent.validation.run --case cavity_re100     # produce it again, and check it
```

`run.py` starts one harness session per case with the reviews **on**, which is the way the
fork is meant to be used and the opposite of how the benchmark runs are configured. Each
session writes a spec, has it reviewed before building anything, builds and runs the case,
has the result reviewed, and answers both reviews. `run.py` then checks the result against
`reference.json` itself, while the mesh it needs for `cavity_re100` and
`flat_plate_blasius` still exists in the build workspace -- `result/` in this repository
does not keep it, so `python -m foamagent.validation.check result/` on its own can only re-check
`cylinder_re100`, whose comparison reads `postProcessing/` rather than the mesh. To re-check
either of the other two without rebuilding, point `check.py` at the build workspace
(default `~/foamagent-validation/<case>/`) instead:

```bash
uv run --with pyvista --with numpy python -m foamagent.validation.check \
    ~/foamagent-validation/cavity_re100 --reference examples/validation/cavity_re100/reference.json
```

## Case-local checkers

A case whose comparison does not fit `profile`, `boundary_layer` or `range` can supply its
own `check.py` beside `request.md` and `reference.json`, instead of growing another kind into
the shared script. `run.py` runs it the same way it runs the built-in checker: positional
argument the built case directory, `--reference` the case's `reference.json`, `--out` the
directory to write into; it must write `comparison.json` there with an `agrees` boolean and
exit 0 if `agrees` else 1. To avoid repeating the CLI wrapper, a checker may define a
`check(case_dir, reference)` function and finish with `raise SystemExit(run_checker(check))`
from `foamagent.validation.checker_cli`. Reusable mesh and history helpers are in
`foamagent.validation.primitives`; the old `foamagent.validation.check` imports remain
available for compatibility.
