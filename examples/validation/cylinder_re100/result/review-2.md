<!-- foamagent: spec review, document 2 -->

# Specification review 2

## Review of spec.md — cylinder_re100 (round 2)

This spec has already been through one review round (`review-1.md`): a high-severity finding about relying on floating-point truncation alone to break flow symmetry, and a low-severity citation error in `gradSchemes`. I re-read the current `spec.md` and confirm both are fixed — the symmetry-breaking `setFields` perturbation is now in the "Initial conditions" section, and `gradSchemes` now reads `leastSquares`, matching the `offsetCylinder` tutorial. I did not re-litigate those; instead I re-derived the spec's own arithmetic independently and re-checked correspondence line-by-line against the verbatim request.

### 1. The reference area for the drag coefficient is a formula, not a number (Medium)

**What is wrong.** The spec defines `Aref` only as "D × spanwise thickness" without ever stating what the spanwise thickness will actually be, so there is no single number in the spec that the built mesh's z-extent can be checked against — and `Cd_mean` is directly proportional to `1/Aref`, so a mismatch here silently scales the one number the user asked for, with no solver error to catch it.

**Evidence.**

- Request: *"the time-averaged drag coefficient, using the cylinder diameter as the reference length and the free-stream speed as the reference velocity"* — the user is relying on a well-defined normalization.
- Spec, Geometry: *"2D domain, single cell thick in the spanwise (z) direction with `empty` type patches..."* — no numeric z-extent is ever given.
- Spec, Outputs: *"Aref = 1×span (=D×spanwise thickness)"* — a formula referencing a quantity ("span") that is never assigned a value anywhere in the document.

**Proposed correction.** State the literal z-extent that `blockMeshDict` will use (e.g. "z from −0.05 to 0.05 m, thickness 0.1 m") in the Geometry section, and write the corresponding literal `Aref` value (e.g. `Aref = 0.1`) in the Outputs section, so the two can be checked against each other before the mesh is built rather than inferred afterward.

### Checks that found nothing

- **Reynolds number and blockage arithmetic**, recomputed via `run_script` independently of round 1: Re = 1×1/0.01 = 100; blockage = 1/(2×15) = 3.33% — both agree with the spec and the request.
- **Shedding-period / cycle-count arithmetic**, recomputed via `run_script`: St = 0.164–0.167 → T = 5.99–6.10 s; t = 150 s → ≈24.9 cycles; extending 10 more cycles → t ≈ 210 s, ≈34.9 cycles total — matches the spec's own figures.
- **Mesh grading arithmetic**, recomputed via `run_script`: a 25-cell, ratio-10 geometric grading over the 0.2 m boundary-layer region gives a first (wall) cell of ≈2.0 mm and a last cell of ≈20.1 mm — the latter matches the spec's stated "~0.02 m" O-grid outer-edge size exactly, and the resolved region (0.2 m) is ~2× a rough laminar boundary-layer thickness estimate (D/√Re = 0.1 m), which is sensible.
- **Feasibility of run length**, recomputed via `run_script`: a Courant-1, 2 mm wall-adjacent cell with local velocities up to 2×U∞ implies dt ≈ 0.001–0.002 s and ≈100,000–210,000 time steps over the planned ≈210 s run on a ~26,000-cell mesh — a small, cheap case, not an infeasible one.
- **Setup-time symmetry-breaking box**: the stated box (x ∈ [0.3, 1.5]D) geometrically overlaps the solid cylinder for x ≲ 0.48–0.5D (verified by radius check); this has no functional effect since `setFields` only touches cells that exist, but it's worth noting as imprecise wording rather than a defect.
- **Correspondence — purpose, turbulence treatment, geometry/BC/IC assumptions, time treatment and stopping criterion, requested outputs and `results.json` schema**: each has a direct, faithful counterpart in the request, and every assumption the spec adds is explicitly labeled as such, as the request required.
- **Omission / excess**: no request item is missing a counterpart, and no unrequested condition was found beyond what's needed to build the case (all such choices — domain extents, BC types, numerics — are disclosed as assumptions rather than presented as given).
- **Feasibility of solver choice**: `pimpleFoam` is available and appropriate for transient, incompressible, laminar flow; the Euler `ddtScheme` claim was checked against the actual OpenFOAM-10 `offsetCylinder` tutorial `fvSchemes` (fetched from the OpenFOAM-10 GitHub repo) and matches verbatim.

The one substantive gap is the missing z-extent/`Aref` number above; everything else in the spec checks out against the verbatim request.
