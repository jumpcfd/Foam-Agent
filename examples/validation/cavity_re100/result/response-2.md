# Response to review-2.md

## 1. Grid-independence addendum could not be independently re-audited

Fixed. The three-grid study (32x32, 64x64, 128x128) was re-run from the exact same
dictionaries as the final case (differing only in `blockMeshDict` resolution). It
reproduced identically: 415 / 1232 / 3810 iterations to convergence, and the same
centreline-difference table (32 vs 64: max|du|=0.00373, max|dv|=0.00517; 64 vs 128:
max|du|=0.00091, max|dv|=0.00094). The raw sampled centreline data and convergence
confirmation from each run is now archived under `gridStudy/<N>x<N>/` inside
`cavity_re100`, so the comparison can be recomputed from source data rather than taken on
the word of spec.md's summary table. spec.md's addendum has been updated to point to this
archive.

## 2. Independent momentum (force) balance was only approximate

Fixed with an exact check, per the reviewer's own suggested remedy. A `forces` function
object (`wallForces`, patches `movingWall` + `fixedWalls`, `rhoInf 1`) was added to
`controlDict` and the final case re-run (converged again in 3810 iterations, identical
residuals to before). `postProcessing/wallForces/0/forces.dat` at the converged time
(3810) gives:

- pressure force: (2.160908e-01, 3.068928e-02, 0)
- viscous force: (-2.160915e-01, -3.068879e-02, 0)
- sum: Fx = -7e-7, Fy = 4.9e-7

Both components cancel to ~1e-6, i.e. to solver precision, against a dominant force
magnitude of ~0.216 -- a relative imbalance of ~3e-6. This directly confirms the
momentum balance the reviewer's hand-rolled estimate could only bound to a few percent,
and is consistent with (tighter than) the mass-conservation check the review already
confirmed independently.

Nothing else in the review changed the case: the spec-conformance, convergence,
discretisation, and Ghia-comparison checks all passed and are unaffected by the two fixes
above.
