# Response to review-1.md

## 1. Mesh-independence record not yet filled in

Agreed — this is expected at this point in the workflow (spec was reviewed before any
run). The 32/64/128 grid study will now be run as planned, and the addendum in spec.md
will be filled in with the actual per-resolution centreline comparison and the resolution
chosen before the final case is built and reported on. Not treating the spec as complete
until that addendum is filled in.

## 2. Solver/utility feasibility not independently confirmed by the reviewer

No change needed. `describe_environment` (called directly against this OpenFOAM 10
installation, not the review sandbox) already confirmed `simpleFoam` and `blockMesh` are
present in this build's solver list, and the `cavity` and `pitzDailyPulse` tutorials
shipped with this exact installation were read directly to confirm `physicalProperties`,
`momentumTransport` (with `simulationType laminar;`), and the `sets` function-object
syntax. `validate_case` will be run before `run_start` as an additional mechanical check.
Noting the reviewer's point as a limit of the review sandbox rather than an open item on
the case.
