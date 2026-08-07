# Lid-driven cavity flow, Re = 100 — Report

## What was asked

A 2D simulation of the classic "lid-driven cavity" problem: a 1 m × 1 m square box of fluid, with the top wall sliding at a constant 1 m/s and the other three walls stationary. The fluid's kinematic viscosity was specified as 0.01 m²/s, which together with the 1 m/s lid speed and 1 m cavity size gives a Reynolds number of 100 — a standard, well-studied laminar test case. The request asked for the simulation to be run until it settled to a steady state, on a mesh fine enough that refining it further would not change the result, and for the outcome to be checked against a well-known published reference (Ghia, Ghia & Shin, 1982).

## What was run

- **Solver:** `simpleFoam` (OpenFOAM), a steady-state solver appropriate for a flow that is known to have a single, stable, non-oscillating solution at this Reynolds number (2D cavity flow doesn't become unsteady until roughly Re ≈ 8000).
- **Mesh:** a uniform 128×128 grid over the square (16,384 cells), one cell thick in the out-of-plane direction with "empty" faces front and back to enforce a strictly 2D solution.
- **Given values:** cavity size 1 m, lid speed 1 m/s, kinematic viscosity 0.01 m²/s — all taken directly from the request.
- **Assumed values (none affect the physics):** the fluid starts at rest; the out-of-plane thickness (1 m, arbitrary, has no effect since the front/back faces are 2D "empty" faces); a convergence threshold of 1×10⁻⁶ on the velocity and pressure residuals, used as the stand-in for "stopped changing."
- **Mesh choice:** three grids (32×32, 64×64, 128×128) were run and compared. The centreline velocity profiles changed by less than 0.1% of the lid speed between the two finest grids, so 128×128 was judged fine enough, with margin, and used for the reported result.
- **Run length:** the solver converged and stopped itself after 3,810 iterations, in about 21–22 seconds of computer time.

## The result

The steady-state velocity field was sampled along the cavity's two centrelines (vertical line through the middle for the horizontal velocity component u, horizontal line through the middle for the vertical velocity component v) and compared point-by-point against the published values of Ghia, Ghia & Shin (1982), the standard reference table for this exact problem.

| Comparison | Maximum difference | RMS difference |
|---|---|---|
| u along vertical centreline | 0.0049 m/s (0.49% of lid speed) | 0.0023 m/s |
| v along horizontal centreline | 0.0088 m/s (0.88% of lid speed) | 0.0044 m/s |

This is a good match — well within the range routinely reported when other solvers reproduce this benchmark, and smaller than the difference the mesh study itself found between the two finest grids is not the case; rather, the disagreement with Ghia's numbers is *larger* than the mesh's own residual sensitivity, meaning the small remaining gap is most plausibly attributable to differences between this solver and Ghia's 1982 method, not to under-resolution here. The full sampled profiles are in `postProcessing/centerlineSampling/3810/`.

The flow field itself is physically sensible: a single large vortex fills most of the cavity, with small secondary eddies in the trailing corners, consistent with what is expected at this Reynolds number.

**Bottom line: the calculation succeeded and answers the question asked.** It produced a converged, mesh-independent steady solution whose centreline velocity profiles match the standard published benchmark to under 1% of the lid speed.

## The disputed points, and how each was settled

Three review passes were made on this case. Here is every objection raised, and the ruling on each.

**1. "The mesh-independence record the request explicitly asked for wasn't filled in yet."**
Raised at the specification stage, before any run had happened — at that point `spec.md` had a placeholder instead of results. **Upheld**, but as a scheduling gap rather than a defect: the three-grid study was run afterward exactly as planned, and the completed comparison (32×32 vs 64×64 vs 128×128) was added to `spec.md`. No further issue.

**2. "The reviewer's sandbox couldn't independently confirm `simpleFoam` and related settings were valid for this OpenFOAM installation."**
**Rejected** as a defect in the case — it was a limitation of the review environment, not of the case itself. The actual OpenFOAM installation confirmed these settings worked (the case ran and converged), and the file/dictionary formats matched OpenFOAM's own documentation.

**3. "The scratch directories used for the original grid study were deleted, so the mesh-independence numbers couldn't be independently re-checked."**
**Upheld.** This was a real gap — the claimed convergence numbers had to be taken on trust. It was fixed: the three-grid study was re-run and the raw data archived permanently inside the case directory (`gridStudy/`), and a later review recomputed the comparison table directly from that archived data and got the same numbers.

**4. "A hand-computed check of the force balance on the walls only closed to within a few percent, not exactly."**
**Upheld** as a genuine gap in verification, though not a flaw in the simulation itself — the reviewer's own manual estimate was imprecise, not the solver's result. It was fixed by adding an exact force calculation (a `forces` function object) to the case and re-running it: the net force on the cavity walls, which must be zero for a closed box in steady state, canceled to about 3 parts in a million — as good a confirmation as this kind of check can give.

**5. "A quoted vortex-centre location, said to be 'within half a grid cell' of Ghia's value, was actually sourced from memory rather than a document, and the search method used to find it wasn't self-validating (it only finds the right vortex if the search area is chosen with foreknowledge of where it is)."**
**Upheld** as a valid criticism of that specific side-observation, but it does not touch the actual result. This vortex-location comparison was never part of the requested output — it was an extra check a reviewer added. The number the request specifically asked to be checked (the centreline velocity profiles) uses a different, complete, and independently reproduced comparison method (item under "The result" above). No change to the case was made or needed; this point was simply logged as unsourced and best treated as indicative only, not evidence.

**6. "The specification's reasoning for picking 128×128 partly cited its 'similarity' to the grid density Ghia et al. used, which overstates the comparison because Ghia's grid was clustered near the walls while this one is uniform."**
**Upheld** as an imprecise piece of *reasoning* in the write-up. It did not affect the result, because the actual decision to use the 128×128 mesh rested on the grid-convergence numbers (item 3 above), not on this comparison. The wording in `spec.md` was corrected to state plainly that the two grids aren't directly comparable and that this was only offered as loose, non-load-bearing corroboration.

No objection in any of the three reviews was found to invalidate the numerical result itself; every fix was either closing a documentation/traceability gap or adding an exact check in place of an approximate one.

## Limits of this calculation

- **No comparison to experiment.** Every number here — in the case itself and in all three rounds of review — was checked against Ghia, Ghia & Shin's 1982 numerical solution, not against a physical experiment. That is the standard practice for this textbook problem (steady 2D cavity flows at Re = 100 aren't really an experimental test case), but it means "matches the literature" here specifically means "matches another computer simulation," not "matches a measurement."
- **Only one reference dataset was used.** No comparison was made against other independent solutions of this same problem (e.g., higher-accuracy spectral solutions by Botella & Peyret), which could have served as a second check on the small remaining ~0.5–0.9% disagreement with Ghia's numbers.
- **The vortex-centre position was not independently confirmed.** A side-check on where the main vortex sits inside the cavity used a comparison value that could not be traced to a citable source, and a search method that depends on already knowing roughly where to look. This does not affect the requested centreline-velocity result but means the vortex location shouldn't be quoted as a verified number from this work.
- **Ghia et al.'s exact mesh design was not confirmed.** A remark in the write-up about how this case's mesh compares to Ghia's original grid could not be fully verified from a primary source; it was reworded to avoid overstating the similarity, but Ghia's precise 1982 grid-stretching parameters remain unconfirmed here.

## References

- Ghia, U., Ghia, K.N., Shin, C.T. (1982). *High-Re solutions for incompressible flow using the Navier–Stokes equations and a multigrid method.* Journal of Computational Physics, 48(3). — standard reference table for this benchmark, used for all velocity comparisons.
- Reference table values (u-velocity): https://gist.github.com/ivan-pi/3e9326d18a366ffe6a8e5bfda6353219 — retrieved 2026-08-07.
- Reference table values (v-velocity): https://gist.github.com/ivan-pi/caa6c6737d36a9140fbcf2ea59c78b3c — retrieved 2026-08-07.
- OpenFOAM v10 User Guide, Lid-driven cavity flow tutorial: https://doc.cfd.direct/openfoam/user-guide-v10/cavity — retrieved during specification review, 2026-08-07.
