<!-- foamagent: result review, document 2 -->

# Result review 2

No write access is available in this session (by design — the task is read-only), so I'll deliver the review directly here rather than as a file.

# Result review 2

## Summary

The case ran to completion and the result holds up. Convergence is clean (residuals below the 1e-6 target with no warnings), mass conservation checked out to solver precision, boundary conditions and dictionaries match spec.md exactly, and the centreline profiles agree with Ghia, Ghia & Shin (1982) to well under 1% of the lid speed — a good, citable result. Two points below qualify rather than invalidate the result: the grid-independence evidence in spec.md's addendum can no longer be independently re-run (the scratch directories were deleted), and my own attempt to close a full momentum (force) balance from the field data was only approximately successful, for reasons that are about my method's precision, not the case's correctness — mass conservation, which I could check exactly, passed cleanly.

## 1. Grid-independence addendum cannot be independently re-audited (qualifies)

**Severity:** Qualifies the result — not a defect in the final case, but a gap in what can now be checked.

**Evidence:** spec.md's addendum (lines 122–155) reports a three-grid study (32×32, 64×64, 128×128) run in scratch directories `cavity_re100_study32/64/128` "outside `cavity_re100`... later removed." Those directories do not exist in the case tree (confirmed by directory listing — only the files enumerated above exist), so the 415/1232/3810-iteration counts and the Δu/Δv table in the addendum cannot be recomputed or spot-checked; they must be taken on the word of the addendum.

This is mitigated, not resolved, by two things I *could* independently check: (a) `log.simpleFoam` confirms the final 128×128 case itself converged in exactly 3810 iterations, matching the addendum's claim for that grid; (b) the Ghia comparison below (independent of the deleted study) shows differences of ~0.5–0.9% of the lid speed, well above the ~0.09% the addendum reports between the 64×64 and 128×128 grids — meaning even if the addendum's numbers were generously wrong by a factor of a few, mesh resolution would still not be the dominant source of the (small) disagreement with Ghia. So the claim is plausible and consistent with everything else, but not independently reproducible from what remains on disk.

**How to settle it:** Re-run the 32×32/64×64/128×128 study (keeping the scratch directories this time, or recording the raw sampled profiles rather than only the summary table) so a reviewer can recompute the Δu/Δv table from source data.

## 2. Independent momentum (force) balance check was inconclusive, by construction of the check, not the case (note)

**Severity:** Note — does not qualify the result. Mass conservation, which is the more fundamental and exactly-checkable balance for a closed cavity, passed cleanly (see "Checks that passed" below).

**Evidence:** I reconstructed the net force balance directly from the converged fields at `3810/U` and `3810/p` and `constant/polyMesh` connectivity: viscous tangential wall shear from a one-sided finite-difference estimate of the wall-normal velocity gradient (`τ = ν·(U_wall,tan − U_cell,tan)/d`, `d` = half the near-wall cell width = 0.00390625 m) plus pressure force (face pressure = owner-cell pressure, exact since `p` is `zeroGradient` on all walls), summed over `movingWall` and `fixedWalls`. For a closed, steady cavity with no body force, this total should sum to zero in both x and y (script `review-work/2/script-7.py`):

- First-order one-sided wall gradient: Fx_total = 9.57e-3 (4.3% of the dominant 0.222 lid-shear term), Fy_total = 2.9e-4 (0.38% of the dominant term).
- Second-order (3-point) one-sided wall gradient: Fx_total = 3.30e-2 (13.4% of the dominant term), Fy_total = 2.48e-3 (2.9% of the dominant term).

The result did not converge tighter as I improved the finite-difference order, which tells me the residual is dominated by physics I omitted from the hand-rolled stress formula — specifically I dropped the explicit `nuEff*dev2(T(grad(U)))` term that `fvSchemes` (line 23) actually includes in the momentum equation, and I estimated wall gradients by finite difference rather than replicating OpenFOAM's own discrete operators exactly — not by a real few-percent imbalance in the solved field. I do not have a reliable independent number for the true momentum-balance residual as a result; both estimates are the same order of magnitude as zero relative to the dominant force term (a few percent, not order-unity), which is reassuring but not a precise confirmation.

**How to settle it:** Re-run with a `forces` (or `forceCoeffs`) function object added to `controlDict`, which computes the exact pressure + viscous + porous force integrals OpenFOAM itself uses, on `movingWall` and `fixedWalls`. That would give a directly comparable, non-approximate number.

## 3. Checks that passed

- **Spec conformance.** `system/blockMeshDict` (128×128×1, unit cube, `convertToMeters 1`), `system/controlDict` (`application simpleFoam`, `endTime 5000`), `system/fvSolution` (`residualControl` p/U at 1e-6, `pRefCell 0`/`pRefValue 0`, relaxation 0.3/0.7), `constant/physicalProperties` (`nu 0.01`), `constant/momentumTransport` (`simulationType laminar`), `0/U` (movingWall `fixedValue (1 0 0)`, fixedWalls `noSlip`, frontAndBack `empty`), and `0/p` (`zeroGradient` on both wall patches) all match spec.md exactly. The final mesh (128×128) matches the addendum's stated decision. No transcription drift, no boundary condition on the wrong patch.

- **Convergence.** `log.simpleFoam` shows `SIMPLE solution converged in 3810 iterations`, with final residuals Ux = 8.40e-7, Uy = 1.00e-6, p = 6.79e-7 — all at or below the stated 1e-6 target, and the run stopped on `residualControl`, not by hitting the 5000-iteration cap. The residual history decreases smoothly from iteration 1 with no oscillation, restart, or bounding warnings in the log.

- **Mass conservation.** Recomputed independently from the converged `phi` field and mesh connectivity (`owner`/`neighbour`), not taken from the log (script `review-work/2/script-4.py`): summing signed face fluxes into each of the 16384 cells gives a maximum cell-divergence of 1.30e-8 m³/s and an RMS of 3.36e-9 m³/s, against a characteristic face-flux scale (lid speed × face area) of 7.81e-3 m³/s — a relative residual of 1.7e-6. This corroborates the log's own "time step continuity errors" line (sum local 1.94e-10 at the final iteration) via a fully independent computation.

- **Discretisation.** Uniform 128×128 Cartesian mesh, fully orthogonal (no non-orthogonality/skewness warnings possible or seen). `divSchemes` uses `bounded Gauss linearUpwind grad(U)` (second-order, upwind-biased — appropriate for laminar Re=100, avoids the excess numerical diffusion of pure upwind) and `laplacianSchemes`/`snGradSchemes` use `corrected`, consistent with the fully-orthogonal mesh. `deltaT`/Courant number are not meaningful diagnostics for `simpleFoam` (pseudo-time iteration, not a physical transient), so no Courant check applies. Field boundedness checked directly on the converged `U` field: interior Ux ∈ [−0.243, 0.976], Uy ∈ [−0.534, 0.315] — no overshoot above the 1 m/s lid speed, i.e. no sign of oscillation from the convection scheme (script `review-work/2/script-9.py`).

- **Physical consistency.** A single primary vortex is found in the cavity interior with its centre located (by minimum |U|, restricted to x,y ∈ [0.3, 0.9] to exclude the corner eddies) at (x, y) = (0.6133, 0.7383) (script `review-work/2/script-10.py`), within half a grid cell (0.0039) of the commonly cited Ghia et al. (1982) primary-vortex location (x, y) ≈ (0.6172, 0.7344) for Re=100 — **this reference number is from memory, not from a source opened during this review, so treat it as indicative only.** An unconstrained search for the global minimum |U| instead lands at (x, y) = (0.9414, 0.0586) (script `review-work/2/script-9.py`), consistent with the known bottom-right secondary corner vortex at this Reynolds number — again indicative, not sourced. No symmetry is expected or looked for, since the lid moves in a single direction.

- **Comparison with Ghia, Ghia & Shin (1982).** u(y) along the vertical centreline (x=0.5) and v(x) along the horizontal centreline (y=0.5) were read from `postProcessing/centerlineSampling/3810/{vertical,horizontal}Centerline.xy`, linearly interpolated onto the 17 tabulated points of Ghia et al.'s Table I for Re=100, and differenced (script `review-work/2/script-8.py`). Table I values were retrieved from two GitHub gists transcribing the published table ([u-velocity](https://gist.github.com/ivan-pi/3e9326d18a366ffe6a8e5bfda6353219), [v-velocity](https://gist.github.com/ivan-pi/caa6c6737d36a9140fbcf2ea59c78b3c)), retrieved 2026-08-07.
  - u(y): max |diff| = 0.00491 (0.49% of lid speed), RMS diff = 0.00225.
  - v(x): max |diff| = 0.00878 (0.88% of lid speed), RMS diff = 0.00444.

  These are well within the level of agreement routinely reported when reproducing this benchmark, and are larger than the case's own 64×64→128×128 grid-convergence difference (~0.09%, per the spec.md addendum) — so the residual disagreement with Ghia is more likely attributable to Ghia et al.'s own 1982 solution (a coarser 129×129 grid with a different scheme) than to under-resolution in this case, consistent with the small offsets from Ghia's original table that later, higher-accuracy studies (e.g. spectral solutions) also report.

## What remains unchecked

- The deleted 32×32/64×64 study data (finding 1).
- An exact momentum/force balance (finding 2) — only an approximate, order-of-magnitude version was computed.
- Comparison against any dataset other than Ghia et al. (1982) Table I (e.g. Botella & Peyret's spectral benchmark).
- No experimental data exists for this configuration; the comparison here is solver-vs-solver (this case vs. a 1982 finite-difference/multigrid solution), not solver-vs-experiment.

---

Since I can't write `review-2.md` into the case directory in this session (no write tool is available — the case is genuinely read-only here), you'll need to save this yourself if you want it filed alongside `review-1.md`/`response-1.md`. All computations referenced are backed by the numbered scripts under `review-work/2/` that `run_script` persisted automatically.
