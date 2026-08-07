# Report: 2D Flow Past a Circular Cylinder at Re = 100

## 1. What was asked

Compute the two-dimensional, laminar, unsteady flow past a circular cylinder (diameter D = 1 m) in a uniform stream of 1 m/s, with kinematic viscosity ν = 0.01 m²/s (Re = 100). Let the vortex shedding develop and settle into a periodic state, then run several more cycles and report, over a whole number of post-transient cycles:

- the time-averaged drag coefficient **Cd**, referenced to D and U∞
- the **Strouhal number** of the shedding, St = fD/U

Use OpenFOAM's `forceCoeffs` function object, write the two results to `results.json`, and record every assumption in `spec.md` since no one was available to answer questions during the run.

## 2. What was run

**Solver:** `pimpleFoam` (OpenFOAM‑10), transient, incompressible, laminar.

**Given by you:** D = 1 m, U∞ = 1 m/s, ν = 0.01 m²/s (Re = 100 — checked and confirmed by direct arithmetic).

**Assumed (not stated in your request), and disclosed in `spec.md`:**
- Domain: 8D upstream, 25D downstream, 10D to each side (20D total width) of the cylinder → **5% blockage** (the original plan was a wider domain at 3.3% blockage, but that mesh produced degenerate, near-singular cells and was abandoned — see the disputed points below).
- Mesh: O‑grid around the cylinder blending into a rectangular far-field block structure, ~42,800 cells, wall cell ≈2.0 mm, verified clean by `checkMesh` (max non‑orthogonality 43.9°, max skewness 0.50, max aspect ratio 31, no failed geometry checks).
- Boundary conditions: fixed-velocity inlet, fixed-pressure (0) outlet, slip top/bottom, no-slip cylinder wall.
- Initial condition: uniform free-stream flow, plus a one-time, localized asymmetric velocity perturbation applied before the solver starts (via `setFields`) to reliably trigger shedding rather than depending on floating-point round-off — a known risk at this Reynolds number, since it is only about 2× the critical value for shedding onset.
- Numerics: first-order-in-time (`Euler`), `leastSquares` gradients, `Gauss linear` convection, matching the shipped OpenFOAM `offsetCylinder` tutorial. Time step was intended to be Courant-limited (max Co = 1) but was **actually run** at `maxCo 2`/`maxDeltaT 0.02 s` — for 99.3% of the 7,502 timesteps the step sat fixed at the 0.02 s ceiling rather than being actively Courant-limited, with the local peak Courant number averaging 1.96 (range 1.92–1.98) during the averaging window. I verified this directly from `log.pimpleFoam` and it matches exactly. See §4 and §5.
- Run length: to t = 155 s (about 26 shedding periods), in two `pimpleFoam` invocations, ≈1,433 s (~24 minutes) of solver run time.

## 3. The result

| Quantity | Value |
|---|---|
| Time-averaged drag coefficient, **Cd_mean** | **1.3799** |
| Strouhal number, **St** | **0.1687** |

Averaged over 6 complete shedding cycles, t = 114.9627–150.5241 s (35.5614 s), starting well after the shedding was judged to have settled into its periodic limit cycle (~t = 115 s, ~19 cycles after the impulsive start). I recomputed both numbers independently from the raw `postProcessing/forceCoeffs1/` data (zero-crossing period, trapezoidal drag integration) and reproduced `Cd_mean = 1.37993` and `St = 0.16872` exactly — these match `results.json` to the reported precision.

These two numbers are the well-supported part of this result. Whether they would still round to the same four digits under the originally-planned finer time step is genuinely untested — see §5.

## 4. The disputed points, and how each was settled

**1. Relying on floating-point round-off alone to break wake symmetry risked a stalled or unpredictable run. — Upheld.**
The domain and impulsive-start initial condition are both symmetric, and at Re = 100 the flow is close enough to the shedding threshold that symmetry can persist for an unbounded time without an explicit trigger — this is a documented issue in the literature for this exact problem. Fixed by adding a small, one-time asymmetric perturbation to the initial condition just downstream of the cylinder. It decays into the flow well before the transient discarded from the averaging window and left no residual bias (mean lift over the averaging window is ≈ −1×10⁻⁶, confirmed by direct recomputation).

**2. The spec claimed its spatial schemes matched the reference tutorial verbatim, but the gradient scheme didn't. — Upheld.**
The tutorial uses `leastSquares` gradients; the spec had `Gauss linear`. No physical justification favored one over the other here, so this was corrected to actually match the cited source. Has no bearing on the physics.

**3. The reference area (Aref) for the drag coefficient was given as a formula ("D × spanwise thickness") with no literal spanwise thickness ever stated. — Upheld.**
This mattered because Cd is directly proportional to 1/Aref, so an unstated thickness is a silent way to get the wrong drag coefficient with no solver error to flag it. Fixed: the spec now states the z-extent explicitly (0.1 m) and Aref = 0.1 m² is written as a literal number, matching what was actually built into `forceCoeffs`.

**4. The symmetry-breaking perturbation box was described as being clear of the cylinder, but geometrically overlaps it for x ≲ 0.5D. — Upheld (wording only, no functional consequence).**
`setFields` only ever touches fluid cells, so the overlap with the solid cylinder region has no effect on the solution — but the description was imprecise and was corrected to say so accurately.

**5. The numbers reported for when the shedding transient converged didn't match the raw data (off by about one shedding cycle). — Upheld, corrected; does not change the headline result.**
Independent recomputation from the raw force-history data showed the period first reaches its converged value one cycle later than originally stated, and likewise for the peak lift amplitude. `spec.md` was corrected. Crucially, the actual averaging window and the reported `Cd_mean`/`St` were untouched by this — only the narrative description of *when* convergence was judged to have happened was wrong. I confirmed both the corrected timestamps and the unaffected final numbers by direct recomputation.

**6. The numerics section described a Courant-limited adaptive time step (max Co = 1); the run actually executed at `maxCo 2`, effectively a fixed 0.02 s step for 99.3% of timesteps, with local peak Courant numbers averaging ~2. — Upheld as a documentation/execution mismatch. The question of whether it affects the answer is unresolved, not settled either way.**
I confirmed this discrepancy directly against `system/controlDict` and by parsing every timestep line in `log.pimpleFoam`: `maxCo 2`/`maxDeltaT 0.02` is what's actually set, 7,450 of 7,502 timesteps sit exactly at the 0.02 s ceiling, and the average local peak Courant number in the averaging window is 1.96. `spec.md` now correctly describes what was run rather than what was planned. What this finding does **not** settle is whether a smaller step would change `Cd_mean`/`St` — no run at the originally intended Co ≤ 1 was performed to check. The mitigating evidence (the shedding period is resolved by ~296 timesteps even at this step size, and each individual timestep converges tightly within its PIMPLE outer-corrector loop) supports treating the reported numbers as usable, but it is evidence toward plausibility, not a substitute for the sensitivity check. This is carried forward into §5 as an open limitation rather than being ruled either way.

## 5. Limits of this calculation

- **The time-step sensitivity question is open.** The run was executed at an effectively fixed 0.02 s step with local Courant numbers averaging ~2, not the Co ≤ 1 originally planned. No comparison run at a smaller step exists. It is plausible but not established that `Cd_mean`/`St` would be unchanged at a finer step.
- **This case has not been compared against experimental data**, only against other published simulations. No wind-tunnel or experimental Re = 100 cylinder dataset was checked.
- **The literature comparison itself is second-hand and incomplete.** An attempt was made to pull a primary comparison table (Rajani et al. 2009, Qu et al. 2013, Posdziech & Grundmann 2007, and others), but every PDF fetched returned unreadable content and a relevant results table was blocked by the host site. What's available instead is search-engine-summarized figures, not numbers read directly from an opened paper — weight it accordingly. Against those indicative figures, this run's St (0.1687) is about 1% above the commonly cited 0.164–0.167 range, and Cd_mean (1.3799) is about 3.75% above an indicative unconfined value of ~1.33 — both shifts are in the direction expected from this case's 5% blockage, but no validated blockage-correction formula was checked against a primary source, so this is a plausibility argument, not a settled comparison.
- **The 5% blockage was not benchmarked in-house against a lower-blockage version of this same mesh.** The originally planned wider, lower-blockage domain (3.3%) produced a degenerate mesh (near-singular cells causing the solver to diverge) and was abandoned in favor of the smaller, more blocked domain actually used. Whether that specific blockage measurably shifts Cd/St from a near-zero-blockage limit was reasoned about via literature trends, not computed directly.
- **Boundary-layer resolution near the cylinder was checked only by an order-of-magnitude estimate** (a flat-plate approximation), not against an extracted near-wall velocity profile from the actual solution — treat this as indicative, not verified.

Everything else — the Reynolds number and blockage arithmetic, the mesh geometry and grading, mass conservation (imbalance ~5×10⁻⁸–4×10⁻⁷ relative to through-flow), the Cd/Cl frequency relationship expected from shedding physics, and the two headline numbers themselves — reproduced exactly under independent recomputation and shows no sign of numerical corruption.

## 6. References

- C.H.K. Williamson, *Vortex Dynamics in the Cylinder Wake*, Annual Review of Fluid Mechanics 28:477–539 (1996) — cited for St ≈ 0.164–0.167 at Re = 100. Cited via search-engine summary, not an opened primary source; retrieved 2026-08-07.
- J. Park, K. Kwon, H. Choi (1998) — cited via a search-engine-summarized table (Cd_mean ≈ 1.33, St ≈ 0.165 at Re = 100, large/near-unconfined domain). Retrieved 2026-08-07; not verified against the original paper.
- [Triggering vortex shedding for flow past a circular cylinder by acting on initial conditions](https://www.sciencedirect.com/science/article/abs/pii/S0045793014002412) — basis for the symmetry-breaking initial-condition perturbation.
- [OpenFOAM-10 `offsetCylinder` tutorial `blockMeshDict`/`fvSchemes`](https://raw.githubusercontent.com/OpenFOAM/OpenFOAM-10/master/tutorials/incompressible/pimpleFoam/laminar/offsetCylinder/) — used as the numerics/topology reference for this case; retrieval date not recorded in the case notes.
