# Response to result review round 2

`rounds_left: 0` was returned with this review, so no further automated review round will see
this response. Both findings were nonetheless investigated and acted on as far as the evidence
supported, and the case was rerun twice more. The full investigation and final numbers are now
recorded in `spec.md`'s new `## Results` section (previously a dangling reference, per Finding
0 below) rather than only in this file, since that is where a reader of the case would look.

## Finding 0 (review context): dangling "see the Results section" reference — FIXED

Agreed — `spec.md` promised a Results section that did not exist. Added one, covering
convergence, `checkMesh` output, the Blasius comparison table, and the investigation below.

## Finding 1: confinement effect only reduced, not resolved — INVESTIGATED FURTHER, PARTIALLY
EXPLAINED, NOT FULLY ELIMINATED (see spec.md §Results for the honest final characterization)

Took the reviewer's own falsifiable criterion seriously (edge velocity 1.000±0.001, low-single-
digit δ99/δ*/θ/Cf errors) and kept testing rather than declaring victory at "smaller than
before." Three further changes were made and measured, in order:

1. **Raised H from 0.55 m to 3.0 m** (blockage ratio 1.0%→0.18%, 5.5× reduction). Result:
   trailing-edge edge-velocity excess went from +1.11% to +1.16% — unchanged within noise, and
   in the wrong direction for a blockage-driven effect. This falsifies "domain height, even with
   `freestream` on top" as the remaining cause.
2. **Lengthened the downstream buffer 10×** (0.3 L→3.0 L, outlet moved from x=1.3 to x=4.0), on
   the hypothesis that a fixed-pressure outlet's influence decays over a lengthscale set by
   domain height (now 3.0 m) rather than buffer length alone, and that 0.3 m was no longer
   enough once H was raised. Result: trailing-edge numbers unchanged to 4 significant figures.
   This falsifies outlet proximity as the cause too.
3. **Tested the top pressure BC formulation directly**: `freestreamPressure` (which behaves as
   zeroGradient wherever the local flow is outflowing — true over most of the top patch, given
   BL-driven entrainment) vs. plain `fixedValue 0` (pinning the true far-field reference
   pressure everywhere). Result: bit-identical output to 5 significant figures. Also ruled out.

Having falsified all three domain/BC hypotheses with direct measurement rather than assumption,
I looked at the *shape* of the remaining deviation instead of continuing to guess at more
padding: δ99 and edge velocity drift mildly and smoothly across the whole plate (single digits
by x=0.8), while Cf specifically jumps sharply only in the last ~20% (+5.3% at x=0.8 to +24.8%
at x=1.0 — a much bigger step than the prior +2.6%→+5.3%). That pattern — smooth global drift
plus a sharp, wall-gradient-specific jump right at the trailing edge — points at (a) mild
accumulated streamwise discretization error and (b) a genuine, localized finite-plate
trailing-edge effect that the idealized semi-infinite-plate Blasius solution has no equivalent
of, rather than anything a bigger box would fix. `spec.md` §Results states this plainly, gives
the reasoning, and recommends an x-refinement/Richardson study as the way to separate (a) from
(b) — out of scope for what this case set out to do, and not attempted here.

I did not keep iterating on domain size after this, because three independent, large-magnitude
changes (5.5× blockage, 10× buffer, a full BC-type swap) each moved the trailing-edge number by
less than measurement noise — that is strong enough evidence against a domain-configuration
explanation that a fourth guess in the same family did not seem justified. What *did* survive
from this round: the original `slip`→`freestream` fix (finding 1 from the previous round) was
real and materially improved x≲0.8 of the plate; that fix is kept, and the honest limit of what
it fixed is now documented rather than overstated.

## Finding 2 (result review round 1 recap): mesh quality never verified — FIXED

Added `runApplication checkMesh` to `Allrun`. Result: **1 failed check** — max aspect ratio
≈3717 (175 cells), located where the downstream buffer's coarsest x-cells meet the plate's
fine near-wall y-cells, on the `symmetryPlane` floor of the wake buffer (no wall gradient is
resolved there, no output is sampled there). All other checks (non-orthogonality, skewness,
openness) pass cleanly. Documented in `spec.md` §Results rather than silently accepted or
silently fixed by further remeshing, since it does not touch the plate region being compared to
Blasius and remeshing the buffer separately was judged not worth the added complexity for a
non-interest region.

## Housekeeping

Stale `postProcessing/*/1521/` (and later `.../1640/`) directories from superseded runs, which
the previous round's review flagged as confusing, were deleted before each subsequent rerun;
the case directory now contains only the time directories and postprocessing output from the
final (3218-iteration) run.
