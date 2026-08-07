Now I have everything needed to write the report.

---

# Flat-plate laminar boundary layer — report

## What was asked

Compute the laminar boundary layer that forms on a 1 m long, sharp-edged flat plate aligned with a 1 m/s uniform stream, for an incompressible Newtonian fluid with kinematic viscosity ν = 1×10⁻⁵ m²/s (Reynolds number 1×10⁵ at the trailing edge — laminar over the whole plate). The domain was to be effectively two-dimensional (one cell of thickness in the spanwise direction), with the inlet, outlet and top boundaries placed far enough away that they do not disturb the boundary layer. The purpose was to check the computed velocity profiles, boundary-layer thickness (δ99), displacement thickness (δ*), momentum thickness (θ), and wall shear stress against the Blasius similarity solution — the textbook exact answer for this exact flow.

## What was run

- **Solver:** `simpleFoam` (steady-state, incompressible, laminar — no turbulence model), OpenFOAM-10.
- **Fluid:** incompressible, Newtonian, ν = 1×10⁻⁵ m²/s — given. No density was assumed or needed; the solver works in kinematic (pressure/density) units throughout.
- **Geometry:** plate at y = 0, x ∈ [0, 1] m, no-slip wall. Ahead of and behind the plate the floor is a symmetry plane, not a wall, so no artificial boundary layer forms there. Inlet at x = −0.3 m (1 m/s, given), outlet at x = 4.0 m (fixed pressure = 0), domain height 3.0 m, one spanwise cell with empty front/back faces. The domain size (buffer lengths, height) was not given and had to be chosen; the final values were reached only after two rounds of enlargement once the first attempts were shown to be too small — see below.
- **Top boundary:** `freestream` type (lets flow pass through rather than acting as a rigid lid) — this, too, was a revision made after the first attempt (a solid slip lid) was shown to distort the result.
- **Mesh:** structured hex grid, 235 × 92 × 1 = 21,620 cells, graded so the first wall-adjacent cell is ≈0.047 mm — small enough to put 26–38 grid points inside the boundary layer at the stations sampled, which is what makes reading δ99/δ*/θ off the computed profile meaningful. `checkMesh` reports the mesh is orthogonal and low-skew but has some very stretched cells (aspect ratio up to ≈3717) in a corner of the outlet buffer, away from the plate — flagged below.
- **Convergence:** ran to residual convergence (p < 10⁻⁶, U < 10⁻⁸) in 3218 of a 5000-iteration ceiling, confirmed by inspecting the solver log directly — about 53 seconds of computation.
- **Outputs:** the U(y) velocity profile at five stations (x = 0.2, 0.4, 0.6, 0.8, 1.0 m) and the wall shear stress along the whole plate.

Everything the user specified (plate length, free-stream speed, viscosity, laminar treatment, spanwise treatment) was used as given. Everything else — buffer lengths, domain height, outlet pressure, top-boundary type, initial field, numerical schemes — was assumed, and is recorded in `spec.md`.

## The result

**The comparison against Blasius holds cleanly for roughly the first 70–80% of the plate, and does not hold at the trailing edge.** This is the headline finding, not a footnote.

| x (m) | δ99, computed | δ99, Blasius | error | edge speed at y = 0.05 m | skin friction Cf, computed | Cf, Blasius | error |
|---|---|---|---|---|---|---|---|
| 0.2 | 6.69 mm | 6.94 mm | −3.7% | 1.006 m/s (+0.6%) | 0.00472 | 0.00470 | +0.6% |
| 0.4 | 9.20 mm | 9.82 mm | −6.3% | 1.008 m/s (+0.8%) | 0.00337 | 0.00332 | +1.7% |
| 0.6 | 11.20 mm | 12.03 mm | −6.8% | 1.009 m/s (+0.9%) | 0.00278 | 0.00271 | +2.6% |
| 0.8 | 12.71 mm | 13.89 mm | −8.5% | 1.010 m/s (+1.0%) | 0.00247 | 0.00235 | +5.3% |
| 1.0 (trailing edge) | 13.38 mm | 15.53 mm | −13.8% | 1.012 m/s (+1.2%) | 0.00262 | 0.00210 | +24.8% |

I re-derived the Blasius reference numbers independently and re-computed the skin friction at the last plate cell directly from the raw wall-shear output rather than trusting the summary table; both checks reproduce the numbers above.

The free-stream speed away from the plate should read exactly 1.000 m/s everywhere if the boundary conditions were doing their job perfectly; instead it drifts upward, mildly at first and more so toward the trailing edge, and the skin friction over the last ~20% of the plate is a quarter higher than the exact answer. So: the boundary-layer thickness and skin friction results at x = 1.0 m (the trailing edge — where a reader would naturally look first, since it's the design condition, Re_L = 1×10⁵) should not be taken as a validated match to Blasius. The result answers the question well for most of the plate and not at the point most likely to be quoted.

## The disputed points, and how each was settled

**1. The confined domain accelerates the free stream and distorts the trailing-edge comparison — upheld, and only partly fixed.**
The domain was originally 0.15 m tall with a solid (`slip`) lid on top. A reviewer showed this let the outer flow accelerate by up to 3.8% by the trailing edge — a real, self-inflicted pressure gradient the true (unbounded) Blasius problem doesn't have, which the user's request explicitly said to avoid. The domain was raised to 0.55 m. A later review of the completed run showed that even at 0.55 m, the solid lid still confined the flow enough to produce 15–33% errors near the trailing edge — the height increase alone hadn't fixed it. The top boundary was then changed from a solid lid to a `freestream` type (letting flow pass through). That helped substantially over the front of the plate but a further review of the next run showed the trailing-edge distortion was reduced, not eliminated — edge speed was still 1.1% too fast and skin friction still 25–27% high near x = 1.0 m. Three more changes were then tried and each was tested directly rather than assumed: the domain height was tripled again (to 3.0 m, cutting the theoretical blockage ratio 5.5×), the downstream buffer was lengthened tenfold, and the outlet-adjacent pressure condition was tested in two different, physically valid forms. **None of the three moved the trailing-edge numbers.** That is a meaningful result in its own right: it rules out the size and shape of the box as the explanation for what remains. **Verdict: upheld** as a real defect in the earlier drafts, which was fixed for most of the plate; **the trailing-edge portion of the disagreement survives this fix and its cause was not identified** — see Limits, below.

**2. The delivered skin-friction output was silently all zeros — upheld, fixed.**
The first completed run's wall-shear-stress sample was taken along a line just above the wall rather than reading the wall itself, and OpenFOAM only fills in wall-shear values on the wall's own face data — the line sample interpolated through empty interior data and returned exactly zero at all 200 points, at every saved time. This was a genuine defect in the delivered output, not a physics or convergence problem: the underlying wall data was there and looked physically sensible once read correctly. The output method was changed to sample the plate's own face values directly, and the corrected output was verified to contain 150 non-zero, physically reasonable values. **Verdict: upheld and fixed.**

**3. Two rounds of documentation slipped out of sync with the case itself — upheld, fixed.**
After the domain height was raised from 0.15 m to 0.55 m, one table in the specification kept listing the old 0.15 m figure — a copy-paste miss that, if used to regenerate the case, would have silently reintroduced the already-rejected setup. Separately, the specification's list of assumptions never stated what values the velocity and pressure fields were initialized to before the solver started iterating, despite the request's explicit instruction to record every assumption made. Both were corrected. **Verdict: upheld and fixed** (paperwork issues, not physics ones).

**4. Two small counting/arithmetic slips in a supporting table — upheld, fixed, immaterial.**
A table estimating how many grid points fall inside the boundary layer at each station was off by one, twice, due to a hand-arithmetic slip later replaced with a direct computation. Neither version changed the conclusion (more than enough points resolve the profile either way). **Verdict: upheld as an inaccuracy, fixed, but never affected any delivered number.**

**5. Mesh quality was never actually checked — upheld, fixed; reveals a minor, non-critical flaw.**
Early in the process, nobody had run OpenFOAM's own mesh-quality diagnostic (`checkMesh`); it was simply assumed the mesh was fine. Once added, it reported the mesh is clean everywhere except for a patch of severely stretched cells (aspect ratio up to ≈3700) where the coarse far-downstream buffer meets the fine near-wall grading. That patch sits well past the plate, on the symmetry floor, where no wall gradient is being resolved and nothing is measured — so it doesn't touch the reported results, but it is a genuine mesh-quality flaw that was left in rather than fixed by re-meshing the buffer separately. **Verdict: upheld as an oversight (should have been checked from the start), fixed by adding the check; the flaw the check turned up was correctly judged not to matter for the numbers reported here.**

**6. Leftover data from earlier, superseded runs cluttered the case directory — upheld, fixed.**
Because the case was re-run several times as boundary conditions changed, old output from earlier (later-invalidated) runs was not automatically cleared out before each rerun, which briefly made it possible to mistake stale numbers for the final ones. This was cleaned up before the final run; the directory now contains only the results from the run reported here. **Verdict: upheld, fixed.**

**7. The velocity-profile outputs go slightly beyond what was literally requested — raised, not a defect.**
A reviewer noted the case reports displacement thickness, momentum thickness, and skin friction in addition to the boundary-layer thickness the request named explicitly. These come for free from data already being collected for the requested comparison and match the evident purpose of the case (checking against Blasius, which is normally reported in exactly these terms). **Verdict: rejected as an issue** — flagged only for completeness, not something that needed correcting.

## Limits of this calculation

- **The trailing 20–30% of the plate (roughly x = 0.8 to 1.0 m) does not match Blasius, and the reason is not established.** Every domain-size and boundary-condition explanation that could be tested was tested and ruled out by direct experiment (tripling the domain height, lengthening the outlet buffer tenfold, and trying two different pressure treatments at the top boundary all left the trailing-edge numbers unchanged). What's left as candidate explanations — a build-up of small numerical (discretization) error along the plate's 235-cell length, and/or a real physical effect of the plate actually ending at x = 1 m, which the idealized Blasius solution (an infinitely long plate) has no counterpart for — were not distinguished from each other. Separating them would need a mesh-refinement study, which was not performed. Until that is done, treat δ99, δ*, θ and skin friction at x = 1.0 m specifically as unreliable, even though the same quantities look good earlier on the plate.
- **The near-wall grid spacing ahead of the plate (the symmetry-floored buffer) was never directly measured to confirm no boundary layer forms there before x = 0.** It's argued to be safe from first principles (a symmetry plane cannot generate a wall boundary layer by construction), but this rests on the physics of the boundary condition rather than on a check of the actual flow field there.
- **A full momentum balance was performed only for an earlier, already-superseded configuration** (the 0.55 m domain with the solid top lid, where it closed to 0.01%) — it was not repeated for the final configuration used to produce the numbers above. A simple mass balance was checked for the final state and is essentially exact (error ~2×10⁻⁷ of the through-flow rate), but that is a weaker check than a full momentum balance.
- **The last set of changes — raising the domain to 3.0 m tall, lengthening the outlet buffer, and testing the pressure condition — was made after the review process had run its planned rounds, and was not checked by an independent pass.** The numbers in this report reflect that final, self-checked state; nobody outside the process that produced them verified this specific configuration.
- **The reference values used for comparison are a similarity solution computed independently for this case** (a numerical integration of the Blasius equation, reproducing the standard published constant f″(0) = 0.33206 to six figures, and matched to five figures against a separately retrieved published table). This is a solid, standard method — Blasius has no simpler closed form — but it means the "textbook answer" being compared against was computed by the same process being checked, not taken verbatim from an external, independently curated source.
- **Nothing here was compared against a physical experiment.** This is a computation of a mathematical idealization (the Blasius solution) checked against another computation (the CFD run); it establishes internal consistency of the numerical method, not agreement with a wind-tunnel or other real measurement.

## References

- H. Schlichting, *Boundary-Layer Theory* — standard tabulated values of the Blasius similarity function f′(η) (f″(0) = 0.33206, etc.), used as an external check on the case's own numerical solution of the Blasius equation. Retrieved via web search, 2026-08-07 (as recorded in the review notes; not independently re-fetched for this report).
- OpenFOAM-10 documentation (openfoam.org) — `simpleFoam`, `freestreamVelocity`/`freestreamPressure`, and `checkMesh` reference behavior, as used to interpret the solver and mesh-diagnostic output in the case's own log files.
