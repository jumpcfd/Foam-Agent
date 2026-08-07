# Response to review-3.md

No defect in the CFD result was found in this round; both notes concern the precision of
secondary, non-load-bearing claims.

## 1. Vortex-centre "location match" mixes a reproducible number with an unsourced reference

Noted, no change made to this case's files: the vortex-centre comparison was the
reviewer's own supplementary check in review-2.md/review-3.md, not a claim in spec.md or
the response files, and the reviewer's own finding already flags it as "indicative only."
Agreed that it doesn't affect the result -- the load-bearing comparison against Ghia et
al. is the digit-by-digit centreline profile match (spec.md's stated output), which is
independently confirmed in finding 3 of review-3.md, not the vortex-centre location.

## 2. spec.md's mesh-comparability rationale overstated similarity to Ghia's grid

Fixed. spec.md's addendum now states plainly that this case's mesh is uniform while Ghia
et al.'s was wall-clustered, so matching cell count does not imply matching near-wall
resolution, and reframes that point as loose corroboration rather than the basis for the
grid-independence conclusion. The actual grid-independence claim was never based on this
comparison -- it rests on the 64x64 -> 128x128 convergence trend from this case's own
mesh study, which review-3.md's Richardson-extrapolation check independently confirmed is
a real, non-artifactual plateau.
