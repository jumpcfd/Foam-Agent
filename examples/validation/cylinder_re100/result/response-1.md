# Response to review-1.md

## Finding 1 (High): symmetric domain + symmetric IC risks an unreliable/stalled shedding onset

Agreed, and fixed. Kept the symmetric, unconfined-style domain (there is no reason to
prefer an asymmetric domain for an unconfined benchmark), but added an explicit,
one-time symmetry-breaking perturbation to the initial condition: `setFields` runs before
`pimpleFoam` and superimposes U = (1, 0.05, 0) — a 5% transverse velocity — on a small box
just downstream of the cylinder (x ∈ [0.3, 1.5]D, y ∈ [−0.15, 0.15]D), on top of the
uniform free-stream IC elsewhere. This is option (a) from the review's proposed
correction. It is a one-shot IC change, not a sustained forcing term, so it doesn't add
energy to the converged periodic solution — it only removes the risk of the run stalling
near the unstable symmetric solution. Recorded in spec.md under "Initial conditions" with
the citation the review supplied. `system/setFieldsDict` and the `Allrun` step have been
added accordingly.

## Finding 2 (Low): gradSchemes claim didn't match the cited tutorial

Agreed, and fixed. Changed `gradSchemes` default to `leastSquares` (was `Gauss linear`) so
`fvSchemes` now matches the `offsetCylinder` tutorial verbatim, and corrected the spec
text to state each scheme explicitly rather than asserting a blanket match. No physical
reason favored `Gauss linear` over `leastSquares` here, so this is a pure correction with
no other consequences.
