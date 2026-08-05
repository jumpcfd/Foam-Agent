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

## The session did not see the answer

The reference values live in `reference.json` in this repository, and the sessions ran in a
working directory outside it. This is not a formality. The first FoamBench run here put the
submission next to the reference case, and two sessions in sixteen read the reference and
recorded in their own notes that they had -- not deceit, just a directory that was there to
be listed. The requests below say what flow to compute and against what kind of data it will
be checked, and nothing about the values.

## Reproducing

```bash
python scripts/validation/run.py --case cavity_re100     # produce it again
python scripts/validation/check.py examples/validation/cavity_re100/result   # check it
```

`run.py` starts one harness session per case with the reviews **on**, which is the way the
fork is meant to be used and the opposite of how the benchmark runs are configured. Each
session writes a spec, has it reviewed before building anything, builds and runs the case,
has the result reviewed, and answers both reviews.
