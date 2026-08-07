<!-- foamagent: spec review, document 1 -->

# Specification review 1

## Review of `spec.md` — flat-plate Blasius validation case

### 1. The top boundary is acknowledged, in the spec's own words, to disturb the layer — directly contradicting the request

**What is wrong:** The request explicitly requires a domain tall enough that the top boundary does not disturb the boundary layer; the spec's own analysis shows the chosen height/BC combination *does* disturb it, and the disturbance grows over the length of the plate.

**Evidence:**
- Request: *"the top boundary far enough above the plate ... that neither disturbs the layer."*
- Spec (§Geometry): *"the top boundary is a slip wall ..., so this residual blockage imposes a small favourable pressure gradient that is **not present in the true (semi-infinite) Blasius problem**. 3.6% was judged an acceptable ... compromise."*

This isn't a matter of interpretation — the spec names the effect itself. I quantified it with a 1‑D continuity estimate using the spec's own δ*(x): with an impermeable top at H = 0.15 m, the local edge velocity accelerates from U∞ by
- +1.65% at x = 0.2 m
- +2.63% at x = 0.5 m
- +3.76% at x = 1.0 m (trailing edge)

That's a streamwise-growing favorable pressure gradient over exactly the region where δ99, δ*, θ and Cf are read off and compared to the zero-pressure-gradient Blasius solution — the case's stated purpose. An effect of this size is not obviously smaller than the discretization/solver error the mesh study elsewhere goes to real trouble to bound, so it risks being the dominant source of disagreement with Blasius, for a reason that isn't physics.

The mesh is only 12,000 cells (trivial cost), so this tradeoff wasn't necessary:
- Tripling the domain height (H ≈ 0.55 m, computed from δ*(1.0)/H = 1%) brings trailing-edge blockage under 1%, and mostly adds cells in the coarse, already-graded far-field region.
- Alternatively, OpenFOAM's `freestream`/`freestreamVelocity`/`freestreamPressure` BC (mentioned in the spec and rejected only "for simplicity") is a standard, no-extra-effort substitute for `slip` that lets the boundary entrain/discharge flow instead of acting as a rigid lid, essentially eliminating the blockage effect regardless of H.

**Proposed correction:** Either raise the domain height so trailing-edge blockage is ≲1% (H ≈ 0.5–0.6 m rather than 0.15 m), or switch the top patch to `freestream` type. Given the run is inexpensive, doing both costs little and removes the self-acknowledged discrepancy with the request.

---

### 2. Minor: cells-within-δ99 table has an off-by-one at the trailing edge

**What is wrong:** The spec's table claims ≈37 cells lie within δ99 at x = 1.0 m; recomputing the same geometric series (r ≈ 1.10, 60 cells, h₁ ≈ 4.94×10⁻⁵ m) gives 36.

**Evidence:** Spec table: *"1.0 | 0.0158 | ≈37"*; recomputed cumulative-height count = 36 cells with face height ≤ 0.01581 m (the 37th cell's outer face lands just past δ99).

**Proposed correction:** Cosmetic only — restate as "≈36" or "36–37" — the conclusion ("enough points to resolve the profile") is unaffected. Not worth reopening the mesh design over.

---

### Correspondence — everything else checked out
Plate length/geometry, sharp leading edge, free-stream velocity, ν, Re_L = U·L/ν = 1×1/10⁻⁵ = 1×10⁵ (verified by direct calculation, matches the request's stated value), laminar-only treatment (Re_L well under the ~5×10⁵ transition threshold), steady-state solver choice (simpleFoam), single-cell spanwise domain with `empty` patches, upstream/downstream symmetry-floored buffers, no-slip plate, and the record of near-wall spacing with its rationale (independently recomputed and matches the spec's stated first-cell height, growth ratio, and total domain height to within rounding) all correspond correctly to the verbatim request.

### Omission — nothing found
Every assumption the spec had to make in the absence of a user to ask (buffer lengths, outlet pressure, spanwise depth, top BC, convergence criteria) is disclosed in the "Assumptions summary," as the request required.

### Excess — minor, not worth correcting
The spec's Purpose section lists δ*, θ, and wall shear/Cf as outputs, which go slightly beyond the verbatim request's mention of only "boundary-layer thicknesses." These are cheap byproducts of the same velocity-field sampling already needed, consistent with the case's evident intent, and not a real problem — flagged only for completeness of the excess check.

### Feasibility — sound, with one caveat
simpleFoam, `blockMesh`, `wallShearStress`, and `graphUniform` are all standard OpenFOAM‑10 capabilities; 12,000 cells is trivially cheap; the 5000-iteration cap is very unlikely to be the binding constraint for a laminar case this size. Whether the tight residual targets (U < 10⁻⁸) are reached within that cap can't be confirmed without running the solver — that's expected at this stage and not a defect in the spec.
