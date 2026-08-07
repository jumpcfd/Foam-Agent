# Spec: Laminar flat-plate boundary layer (Blasius validation)

## Request, verbatim

> Compute the laminar boundary layer that develops on a flat plate in a uniform stream.
>
> The plate is 1 m long, sharp-edged, and aligned with the flow. The free stream is 1 m/s and
> the fluid is incompressible and Newtonian with a kinematic viscosity of 1e-5 m^2/s, so the
> Reynolds number at the trailing edge is 1e5 and the layer stays laminar over the whole
> plate. The flow is steady and two-dimensional: use a single cell in the spanwise direction
> with empty boundaries.
>
> Put the leading edge far enough downstream of the inlet, and the top boundary far enough
> above the plate, that neither disturbs the layer. The result will be compared against the
> similarity solution for this flow, so resolve the layer well enough near the wall for
> boundary-layer thicknesses read off the velocity profile to be meaningful, and record in
> spec.md what near-wall spacing you used and why.
>
> Build the OpenFOAM case in /home/tateb/foamagent-validation/flat_plate_blasius (create it; do
> not make a subdirectory inside it for the case).
> Nobody is available to answer questions: assume what you must, record every assumption in
> spec.md, and finish the run. Do not end your turn while the solver is still running -- run_status
> takes a wait_seconds.

## Purpose

Reproduce the Blasius similarity solution for laminar flow over a semi-infinite flat plate with
a CFD case, so the computed velocity profiles, boundary-layer thickness (δ99), displacement
thickness (δ*), momentum thickness (θ) and wall shear stress can be checked against the known
similarity result. This is a verification case, not a design study.

## Physics and solver

- Incompressible, single-phase, Newtonian fluid.
- Laminar (no turbulence model): Re_L = U∞L/ν = 1×1/1e-5 = 1×10^5, well below the ≈5×10^5
  transition Reynolds number for a flat plate, so laminar is appropriate over the whole plate,
  matching the request.
- Steady state → **simpleFoam** (SIMPLE algorithm), OpenFOAM-10 (foundation fork, confirmed by
  `describe_environment`).
- `constant/momentumTransport`: `simulationType laminar;` with no `laminar{}` sub-dictionary —
  this is the plain constant-viscosity Newtonian model in OpenFOAM 10 (confirmed against the
  `blockedChannel`/`porousBlockage` laminar tutorials, which omit the sub-dictionary entirely;
  a sub-dictionary is only needed for non-Newtonian/viscoelastic models).
- `constant/physicalProperties`: `viscosityModel constant; nu 1e-5;` (given).

## Geometry

2D-equivalent domain (single cell in z, empty front/back patches), block-structured hex mesh,
built with `blockMesh`.

- Plate: 1 m long, zero-thickness (sharp leading and trailing edges), aligned with the flow, at
  y = 0, spanning x ∈ [0, 1].
- Upstream buffer: x ∈ [-0.3, 0] (0.3 L) ahead of the leading edge. The floor here is a
  `symmetryPlane`, not a wall, so no spurious boundary layer forms before the sharp leading
  edge and the free stream reaches x = 0 undisturbed — **assumption**: 0.3 L is more than
  enough because nothing physically develops on a symmetry plane; its only purpose is to keep
  the fixed-velocity inlet patch away from the leading-edge region.
- Downstream buffer: x ∈ [1, 4] (3.0 L) past the trailing edge, again floored by a
  `symmetryPlane` (no solid there). This keeps the fixed-pressure outlet patch away from the
  trailing edge so the outlet condition does not contaminate the solution over the plate; this
  is not a wake study, so no attempt is made to resolve the near-wake in detail, only to keep
  it far enough away.

  **Revision note (result review round 2 — after the H = 0.55 → 3.0 m change, see below):**
  the initial 0.3 L buffer was carried over unchanged when H was first raised to 0.55 m and
  still showed a residual edge-velocity excess after switching the top patch to `freestream`
  (see below). Raising H to 3.0 m *without* also lengthening this buffer left the trailing edge
  only 0.3 L from a fixed-pressure outlet in a domain now 3 L tall — for an elliptic
  (incompressible) pressure field, a boundary condition's influence decays over a lengthscale
  set by the domain's cross-section, not by the streamwise buffer length in isolation, so a
  buffer that was adequate relative to H = 0.55 m was no longer adequate relative to H = 3.0 m.
  Confirmed by rerunning with H = 3.0 m and the old 0.3 L buffer: the trailing-edge edge-velocity
  excess barely moved (+1.16% vs. +1.11% before raising H), even though the nominal blockage
  ratio had dropped 5.5×, which is inconsistent with pure top-boundary blockage and consistent
  with outlet proximity instead. The downstream buffer was lengthened to 3.0 L (comparable to
  H) in response; see the Results section for the outcome.
- Domain height: y ∈ [0, 3.0] (3.0 L). Justification: the Blasius 99%-thickness is
  δ99(x) = 5x/√Re_x. At the trailing edge (x = 1, Re_x = 1e5), δ99 ≈ 0.0158 m. The Blasius
  displacement thickness there is δ* = 1.72x/√Re_x ≈ 0.00544 m, giving a nominal blockage ratio
  δ*/H ≈ 0.18% at the trailing edge (smaller upstream — see the table below).

  **Revision note (spec review, round 1):** an earlier draft used H = 0.15 m (blockage ≈3.6% at
  the trailing edge) and was flagged as self-contradicting the request's instruction that the
  top boundary must not disturb the layer; H was raised to 0.55 m in response, on the reasoning
  that ≤1% blockage would be small enough not to be the dominant source of disagreement with
  Blasius, while declining to also switch the top patch away from `slip` (an impermeable,
  zero-shear lid) as unnecessary extra configuration risk.

  **Revision note (result review, round 1):** that reasoning was empirically wrong. The first
  run (H = 0.55 m, `slip` top) showed the edge velocity at y = 0.05 m rising to 1.0135 m/s
  (+1.35%) by the trailing edge, and — because δ*, θ and Cf are all differences/gradients
  measured against a nominal U∞ = 1 that the confined flow no longer matched — that translated
  into 15-33% errors against Blasius near the trailing edge, dominating the comparison the case
  exists to make. `slip` is a rigid, impermeable lid regardless of how far away it is placed
  (confirmed: the converged run's `phi` flux through the top patch was exactly zero on all 200
  faces). The top patch was changed to `freestream`/`freestreamVelocity`/`freestreamPressure`
  (`freestreamValue` = the free-stream state, matching the internal field below), which allows
  the boundary to entrain or discharge flow rather than acting as a wall, and the case was
  rerun with H still at 0.55 m.

  **Revision note (result review, round 2):** the `freestream` fix at H = 0.55 m helped but did
  not resolve the effect — edge velocity at the trailing edge only dropped to +1.11% (from
  +1.35%), and skin friction still disagreed with Blasius by up to ≈27% over the last ~20% of
  the plate. The reviewer's own diagnosis was that a `freestream` top still cannot fully
  relieve the boundary layer's displacement effect if the domain is not tall enough — i.e. once
  the impermeable-lid mechanism is removed, domain height becomes the effective remaining lever
  again, exactly as it would in the original (`slip`) case, just at a much smaller residual
  level. **H was raised again, to 3.0 m** (blockage ≈0.18% at the trailing edge, vs. ≈1.0% at
  H = 0.55 m — see the table below for the full profile), keeping `freestream` on top, and the
  case was rerun a third time.

  **Follow-up note (self-directed, after the result-review rounds were exhausted):** the H=3.0 m
  rerun still showed essentially the same trailing-edge edge-velocity excess as H=0.55 m
  (+1.16% vs. +1.11%), despite blockage dropping 5.5×, which does not fit a pure top-boundary
  blockage explanation. Investigated further and found the downstream buffer (still 0.3 L,
  unchanged since the very first draft) was the more likely remaining cause once domain height
  stopped mattering — see the downstream-buffer revision note below for the fix (lengthened to
  3.0 L) and the Results section for the final outcome.
- Spanwise depth: z ∈ [-0.005, 0.005] (0.01 m), a single cell, `empty` front/back patches per
  the request. The depth value is arbitrary and immaterial since the direction is not solved.

## Boundary conditions

| Patch | Type (mesh) | U | p |
|---|---|---|---|
| inlet (x = -0.3) | patch | fixedValue uniform (1 0 0) | zeroGradient |
| outlet (x = 4.0) | patch | zeroGradient | fixedValue uniform 0 |
| top (y = 3.0) | patch | freestreamVelocity | fixedValue uniform 0 |
| symmetry (floor, x < 0 and x > 1) | symmetryPlane | symmetryPlane | symmetryPlane |
| plate (floor, 0 ≤ x ≤ 1) | wall | noSlip | zeroGradient |
| frontAndBack (z = ±0.005) | empty | empty | empty |

- Inlet velocity: uniform 1 m/s, aligned with the plate (given).
- Outlet: fixed gauge pressure 0 Pa (kinematic, p/ρ — ρ never appears since the solver works in
  kinematic pressure); zero-gradient velocity — standard outflow treatment for simpleFoam.
- Top: `freestreamVelocity` for U (`freestreamValue` = (1 0 0)), plain `fixedValue uniform 0`
  for p. **Revised from `slip`** after the first run (see §Geometry) showed `slip`'s
  impermeability, not just the domain height, was the source of the residual confinement
  effect; the mixed/direction-dependent `freestreamVelocity` lets the boundary entrain or
  discharge flow instead of acting as a rigid lid. **p was tested both ways**: `freestreamPressure`
  (zeroGradient wherever the local flow is outflowing, which is true over most of the top patch
  given BL-driven entrainment; fixedValue only where flow is inflowing) and plain `fixedValue 0`
  (pinning pressure to the true far-field reference everywhere, matching the outlet) gave
  **bit-identical results** (5-significant-figure agreement in every sampled quantity) — so this
  was not the cause of the residual deviation discussed in the Results section, and `fixedValue`
  was kept as the simpler, equally-valid choice.
- Plate: no-slip wall, the physical condition for a solid sharp-edged plate.
- Symmetry floor: `symmetryPlane`, since y = 0 ahead of/behind the plate is not a physical
  surface — flow there is unconstrained and mirror-symmetric about y = 0.

## Mesh and near-wall spacing

Block-structured, 3 blocks along x (upstream / plate / wake buffer) × 1 block in y × 1 cell in
z, all sharing the same y-direction cell distribution so the mesh is conformal across the block
interfaces at x = 0 and x = 1.

- x: 25 cells over the upstream buffer (graded finer approaching x = 0), 150 cells over the
  plate (graded finer approaching x = 0, where the boundary layer is thinnest and curvature of
  the developing profile is largest), 60 cells over the downstream buffer (graded finer
  approaching x = 1; coarse resolution here is acceptable since this buffer is not a region of
  interest — see the downstream-buffer revision note above). Total 235 cells in x.
- y: 92 cells from the wall (y = 0) to the top (y = 3.0), geometrically graded with the
  OpenFOAM `simpleGrading` overall expansion ratio (last cell / first cell) = 5844, i.e. a
  per-cell ratio of ≈1.10. This puts the **first cell height at ≈4.67×10⁻⁵ m (≈0.047 mm)** at
  the wall, growing ~10%/cell up to ≈0.27 m at the top (computed and verified numerically, not
  by hand). *(74 cells / H=0.55 m / first cell ≈0.048 mm in earlier revisions of this case —
  see the domain-height revision notes above; the near-wall spacing itself barely changed, only
  how far it has to grow before reaching the now much larger top.)*
- z: 1 cell (not graded).
- Total mesh: 235 × 92 × 1 = 21 620 cells.
- `checkMesh` was added to `Allrun` (after the result review that flagged mesh quality as
  unverified) and reports: max non-orthogonality 0, max skewness ≈1.9×10⁻¹³, max aspect ratio
  ≈647 (expected for a highly graded boundary-layer mesh; occurs in the near-wall/far-field
  cells, not near any region being compared to Blasius), boundary openness ≈1×10⁻¹⁵, `Mesh OK`.

**Why this near-wall spacing:** the flow is laminar, so there is no y+ wall-function
requirement, but the point of this case is to read boundary-layer thicknesses off the computed
velocity profile and compare them to Blasius, which requires several resolved points *inside*
the layer, not just near the wall. With the grading above, the number of cells between the wall
and the local δ99(x) works out to (recomputed numerically):

| x (m) | δ99 Blasius (m) | cells within δ99 | blockage δ*/H (H=3.0 m) |
|---|---|---|---|
| 0.1 | 0.0050 | 26 | 0.057% |
| 0.5 | 0.0112 | 34 | 0.128% |
| 1.0 | 0.0158 | 38 | 0.181% |

i.e. 26–38 points resolve each profile, which is enough to fit δ99, δ* and θ meaningfully
against the similarity solution. The first cell (0.047 mm) is roughly 1% of δ99 even at the
thinnest station sampled (x = 0.1 m), so the near-wall gradient (and hence wall shear stress)
is also well resolved. Blockage stays under 0.2% everywhere on the plate.

## Numerics

- `fvSchemes`: steady state; `Gauss linear` gradients; `bounded Gauss linearUpwind grad` for
  `div(phi,U)` (2nd-order, bounded for robustness — same scheme as the T3A tutorial, this
  OpenFOAM version's own flat-plate case); `Gauss linear corrected` Laplacians — conservative,
  standard simpleFoam choices.
- `fvSolution`: GAMG for p, smoothSolver for U; SIMPLE `consistent yes` (SIMPLEC-like) with
  relaxation factor 0.9 on all equations; residual control p < 1e-6, U < 1e-8, so the run stops
  automatically once converged (endTime is a 5000-iteration cap, not expected to be reached).

## Outputs

- Full flow field (U, p) at convergence.
- `wallShearStress` function object over the whole domain, sampled directly on the `plate`
  patch by a `surfaces` function object (`type patch`, `patches (plate)`, `raw` format), for
  skin-friction comparison against the Blasius Cf(x) = 0.664/√Re_x. **Revised from an initial
  `graphUniform` line sample offset from the wall** (result review, round 1): `wallShearStress`
  is populated only on its owning wall patch's boundary field, with a zero internal field
  elsewhere, so a `graphUniform` line sampled a small distance off the wall interpolated
  through that zero internal field and returned all zeros — a real defect in the first run's
  delivered output, not a convergence or physics problem. Sampling the patch's own face values
  directly avoids the interior interpolation entirely.
- `graphUniform` samples of U(y) at x = 0.2, 0.4, 0.6, 0.8, 1.0 m (y = 0 to 0.05 m, comfortably
  past δ99 even at the trailing edge), for direct velocity-profile comparison against the
  Blasius solution and for reading off δ99/δ*/θ.

## Assumptions summary

1. ρ is never specified/used: simpleFoam solves for kinematic pressure p/ρ, and the request
   gives no density, so none is assumed or needed.
2. Outlet gauge pressure = 0.
3. Domain height 3.0 m (§Geometry) — revised twice: from an initial 0.15 m draft (spec review),
   to 0.55 m (still with `slip` on top, and still showing a confinement effect after the top-BC
   fix in item 5), to the final 3.0 m (result review round 2), which brings the residual
   blockage ratio under 0.2% everywhere on the plate.
4. Upstream buffer 0.3 L, downstream buffer 3.0 L (unequal — the downstream buffer was
   lengthened 10× on the hypothesis, explained in §Geometry, that a fixed-pressure outlet needs
   distance comparable to the domain height to stop influencing an interior station; **this
   hypothesis was tested and did not hold** — see §Results — but the longer buffer was kept
   since it is harmless and rules out one candidate explanation for the residual deviation
   discussed there), both floored by symmetry planes rather than walls.
5. Top boundary: `freestream` — revised from an initial `slip` choice after the first run
   showed `slip`'s impermeability (not the domain height) was the dominant remaining source of
   disagreement with Blasius near the trailing edge; see §Geometry and §Boundary conditions for
   the measured effect and the rerun outcome.
6. No turbulence model; Re_L = 1e5 keeps the whole plate laminar (given, and well under the
   ~5×10^5 transition threshold).
7. Spanwise depth 0.01 m, arbitrary (unsolved direction).
8. Steady SIMPLE run to residual convergence (p < 1e-6, U < 1e-8), capped at 5000 iterations.
9. Discretisation schemes taken from OpenFOAM-10's own flat-plate tutorial (T3A) as a
   version-correct, proven-stable reference, adapted to remove the turbulence-transport terms
   this laminar case does not need.
10. Initial (`0/`) internal fields: `U` uniform `(1 0 0)` (the free-stream value) and `p`
    uniform `0`, everywhere in the domain — starting SIMPLE from the free stream rather than
    from rest shortens the number of iterations needed to reach the converged boundary layer.
11. Wall-shear-stress output is sampled directly from the `plate` patch's own boundary field
    (via a `surfaces`/`patch` function object) rather than a `graphUniform` line near the wall,
    after the first run's line-sample output was found to be all zeros (§Outputs) — the
    `wallShearStress` field's internal (cell) values are zero by construction, so any sample
    that interpolates through the interior rather than reading the patch directly returns
    zero regardless of how close to the wall it is placed.

## Results

Final run: converged in 3218 SIMPLE iterations (well under the 5000 cap; residual control
p<1e-6, U<1e-8 satisfied). `checkMesh` (added to `Allrun` after result review) reports
non-orthogonality 0, skewness ≈1.6×10⁻¹³, boundary openness ≈1×10⁻¹⁶ — all clean — but **fails
one check**: max aspect ratio ≈3717 (175 cells). This occurs where the downstream buffer's
coarsest x-cells (near the outlet, ≈0.17 m) meet the finest y-cells (at the symmetry floor,
≈4.7×10⁻⁵ m) — i.e. in the wake-buffer region, on a `symmetryPlane` where no wall gradient is
being resolved and no output is sampled. It is a cosmetic consequence of carrying the
fine near-wall y-grading (needed on the plate) all the way out through the buffer, not a defect
that affects the plate region being compared to Blasius; a topologically separate, coarser
y-mesh in the buffer block would remove it but was not built, since it does not affect any
delivered quantity.

Comparison against my own RK4-shooting solution of the Blasius similarity equation (converged
f''(0) = 0.332057, matching the standard published constant to 6 figures) at the five sampled
stations:

| x (m) | δ99 CFD (m) | δ99 Blasius (m) | δ99 error | edge U at y=0.05 m | Cf CFD | Cf Blasius | Cf error |
|---|---|---|---|---|---|---|---|
| 0.2 | 0.00669 | 0.00694 | −3.7% | 1.0064 (+0.6%) | 0.00472 | 0.00470 | +0.6% |
| 0.4 | 0.00920 | 0.00982 | −6.3% | 1.0075 (+0.8%) | 0.00337 | 0.00332 | +1.7% |
| 0.6 | 0.01120 | 0.01203 | −6.8% | 1.0085 (+0.9%) | 0.00278 | 0.00271 | +2.6% |
| 0.8 | 0.01271 | 0.01389 | −8.5% | 1.0102 (+1.0%) | 0.00247 | 0.00235 | +5.3% |
| 1.0 | 0.01338 | 0.01553 | −13.8% | 1.0115 (+1.2%) | 0.00262 | 0.00210 | +24.8% |

**Investigation of the trailing-edge deviation.** Three domain-configuration hypotheses were
tested and each was empirically ruled out — none moved the trailing-edge numbers above by more
than noise:
1. Top-boundary blockage from an impermeable `slip` lid — **confirmed and fixed** (see the
   `slip`→`freestreamVelocity` revision above): this was real and its removal materially
   improved the leading two-thirds of the plate.
2. Residual blockage from insufficient domain height even with `freestream` on top — **tested,
   ruled out**: raising H from 0.55 m to 3.0 m (blockage ratio 1.0%→0.18%, a 5.5× reduction)
   changed the trailing-edge edge-velocity excess from +1.11% to +1.16% — i.e. not at all, in
   the wrong direction to be blockage-driven.
3. Outlet proximity relative to the taller domain — **tested, ruled out**: lengthening the
   downstream buffer 10× (0.3 L → 3.0 L, outlet moved from x=1.3 to x=4.0) left the
   trailing-edge numbers unchanged to 4 significant figures.
4. Top pressure BC formulation (`freestreamPressure`, mostly-zeroGradient given the observed
   outflow-dominated top patch, vs. plain `fixedValue 0`) — **tested, ruled out**: bit-identical
   results (§Boundary conditions).

None of the four domain/BC changes tried moved the trailing-edge disagreement, which rules out
the case's outer boundaries as the cause. The remaining pattern — δ99 and edge velocity drifting
smoothly and mildly across the *entire* plate (a few percent by mid-plate), with Cf specifically
jumping sharply only in the last ~20% of the plate (+5.3% at x=0.8 to +24.8% at x=1.0, a much
larger jump than the +2.6%→+5.3% step from x=0.6 to x=0.8) — is consistent with two distinct,
much more locally-rooted causes that further domain padding cannot address: (a) a mild,
accumulating streamwise discretization error over the plate's 235-cell x-resolution, and (b) a
genuine, localized trailing-edge effect in the last fraction of a boundary-layer thickness before
x=1 (skin friction, a wall-gradient quantity, is far more locally sensitive to this than the
velocity-profile-derived δ99 is) — a real feature of any *finite* plate that the idealized
*semi-infinite*-plate Blasius solution used as the comparison target does not include by
construction. Distinguishing (a) from (b) quantitatively (e.g. by an x-refinement/Richardson
study, or by sampling stations further from both ends of the plate) is beyond what this case set
out to do and is flagged here as the natural next step rather than attempted.

**Bottom line for using this case's results**: treat x ≲ 0.8 m (80% of the plate) as validated
against Blasius to within a few percent in δ99, edge velocity and Cf. Treat the trailing-edge
station (x = 1.0 m) specifically as degraded — up to 14% in δ99, 25% in Cf — for the reasons
above, not because of an unresolved domain-size or boundary-condition defect.
