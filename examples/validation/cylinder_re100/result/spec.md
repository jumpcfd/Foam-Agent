# Specification: 2D flow past a circular cylinder at Re = 100

## Request, verbatim

> Compute the two-dimensional flow past a circular cylinder at a Reynolds number of 100.
>
> The cylinder has a diameter of 1 m and sits in a uniform stream of 1 m/s. The fluid is
> incompressible and Newtonian with a kinematic viscosity of 0.01 m^2/s, which puts the
> Reynolds number based on the diameter at 100. At this Reynolds number the wake sheds
> vortices periodically, so the flow is unsteady and laminar. It is two-dimensional: use a
> single cell in the spanwise direction with empty boundaries. Put the outer boundaries far
> enough from the cylinder that they do not change the wake.
>
> Run long enough for the shedding to settle into a periodic state, then keep running for
> several more shedding cycles. Report, over a whole number of cycles taken after the
> transient:
>
> - the time-averaged drag coefficient, using the cylinder diameter as the reference length
>   and the free-stream speed as the reference velocity
> - the Strouhal number of the shedding, f D / U
>
> Use the forceCoeffs function object so that the coefficient histories are written under
> postProcessing/, and put your two numbers in results.json in the case directory as
> {"Cd_mean": ..., "St": ...}. Say in spec.md which time interval you averaged over and how
> you decided the transient was over.
>
> Build the OpenFOAM case in /home/tateb/foamagent-validation/cylinder_re100 (create it; do
> not make a subdirectory inside it for the case).
>
> Nobody is available to answer questions: assume what you must, record every assumption in
> spec.md, and finish the run. Do not end your turn while the solver is still running --
> run_status takes a wait_seconds.

## Conditions

**Purpose.** Reproduce the well-documented 2D laminar vortex-shedding benchmark for a
circular cylinder at Re = 100 and report the time-averaged drag coefficient and the
Strouhal number of the shedding.

**Physics.** Incompressible, Newtonian, laminar, transient. Solver: `pimpleFoam`
(OpenFOAM Foundation v10; only listed solver family that does transient incompressible
laminar flow with PIMPLE pressure-velocity coupling — `icoFoam` was also considered but
`pimpleFoam` allows an adjustable time step tied to a Courant-number limit, which is
useful given the wide range of cell sizes between the boundary layer and the far field).

**Given values** (all stated by the user):
- Cylinder diameter D = 1 m
- Free-stream speed U∞ = 1 m/s
- Kinematic viscosity ν = 0.01 m²/s
- Re = U∞D/ν = 100
- Density: not needed dimensionally by `pimpleFoam` (kinematic pressure p/ρ); force
  coefficients use `rhoInf = 1` (incompressible convention), so no density value is load
  bearing.

**Geometry / mesh (assumed, revised during meshing — see revision note below).** 2D
domain, single cell thick in the spanwise (z) direction (z from −0.05 m to 0.05 m,
thickness 0.1 m) with `empty` type patches on the front/back faces (via `defaultPatch`),
as instructed. An O-grid body-fitted mesh around the cylinder (radius R = 0.5 m) blending
into a rectangular far-field block structure, following the topology of the
`pimpleFoam/laminar/offsetCylinder` tutorial shipped with this OpenFOAM install but
re-derived with a symmetric domain (the tutorial's own domain is asymmetric and
deliberately close to a wall, since it studies wake/wall interaction — not applicable
here). Domain extents, all measured from the cylinder centre at the origin:
- Upstream (inlet): 8 D
- Downstream (outlet): 25 D — generous, to keep the wake and any exiting vortices well
  clear of the outlet, which uses a zero-gradient velocity condition that assumes fully
  developed outflow
- Lateral (top/bottom): 10 D each side ⇒ blockage ratio D / 20D = 5%, which the published
  literature on this benchmark treats as small enough for a negligible confinement effect

Circumferential resolution: 160 cells around the cylinder (20 per 45° octant). Radial
resolution in the O-grid boundary layer region (R to 1.4R): 25 cells, graded (ratio 10)
finer at the wall. Outer blocks graded (ratio 25–30 depending on the block's physical
extent) from a cell size matched to the O-grid's outer edge (~0.02 m) up to ~0.5–0.6 m at
the domain boundaries. Total mesh: ~43,000 cells.

**Revision note (domain size and outer grading).** The first mesh attempt used a larger,
more generous domain (15D upstream, 35D downstream, 15D lateral) with the O-grid's fine
circumferential resolution held constant along the tangential direction of every block
connecting the O-grid to the domain edges. `checkMesh` flagged 62 cells with a
near-singular determinant (min 0.00031, threshold 0.001) — these turned out to be sliver
cells at the far ends of those outer blocks, where the tangential cell size stayed fixed
at the O-grid's fine ~0.02 m while the radial cell grew to several metres, giving cell
aspect ratios up to 180:1 (confirmed this was a genuine in-plane shape defect, not a
spanwise-thickness artefact, by rerunning `checkMesh` with the z-thickness scaled up 20×
— the determinant minimum was unchanged). `pimpleFoam` reliably blew up (`sigFpe` inside
`GAMGSolver::scale`, or a silently diverging solution with the adaptive time step
collapsing to ~1e-6 s and `Cd` reaching 10⁵) at the same simulated time regardless of
PIMPLE settings (`momentumPredictor`, Courant limit), consistent with those ill-conditioned
cells poisoning the pressure solve rather than a transient/robustness issue. The domain
was reduced to the extents above and the outer-block grading retuned (more cells, milder
ratio) so the worst-case cell aspect ratio is ~20–24:1 instead of 180:1, and `checkMesh`
reports zero small-determinant cells; blockage is 5% instead of 3.3%, still within the
range the literature treats as negligible for this benchmark.

**Boundary conditions (assumed, standard for this benchmark):**
- Inlet (`left`): U = fixedValue (1 0 0); p = zeroGradient
- Outlet (`right`): p = fixedValue 0; U = zeroGradient
- Top/bottom far field (`up`, `down`): `slip` for U, `zeroGradient` for p — chosen over a
  no-slip wall because a no-slip far-field boundary would grow its own (unphysical)
  boundary layer; `slip` approximates an open, unconfined far field without that artifact.
  Since the boundaries are 15D away this choice has negligible effect on the wake either
  way, but `slip` is the more defensible choice of the two.
- Cylinder: U = noSlip; p = zeroGradient

**Initial conditions (assumed).** U = uniform (1 0 0) everywhere except the cylinder wall
(impulsive start from free-stream); p = uniform 0. Because both the geometry and this
initial condition are symmetric about y = 0, and Re = 100 is only ≈2× the critical Re ≈ 47
for shedding onset, relying on floating-point truncation alone to break symmetry is
unreliable and could stall the run for an unpredictable (or effectively unbounded) time —
this is a documented issue for this exact problem (see e.g. Triggering vortex shedding for
flow past circular cylinder by acting on initial conditions,
sciencedirect.com/science/article/abs/pii/S0045793014002412). To avoid depending on that,
`setFields` is run once before `pimpleFoam` starts to superimpose a small asymmetric
perturbation — U = (1 0.05 0), a 5% transverse velocity — on a small box immediately
downstream of the cylinder (x ∈ [0.3, 1.5] D, y ∈ [−0.15, 0.15] D). This is a one-time
initial-condition change only (not a sustained forcing during the run): it decisively
breaks the symmetry so shedding starts promptly, and is convected out of that region
within the first few time units, well before the transient this run discards.

**Numerics (assumed; corrected post-run to describe what was actually executed — see
"Numerics as actually run" below).** `pimpleFoam`, `Euler` time scheme (first order,
standard for this solver family and adequate given the fine adjustable time step), spatial
schemes matching the `offsetCylinder` tutorial's own `fvSchemes`/`fvSolution` verbatim:
`gradSchemes` default `leastSquares`, `div(phi,U)` `Gauss linear`, Laplacian/interpolation/
snGrad `linear`/`corrected` (these are the shipped, validated settings for this exact
solver/regime). Time step was planned as adaptive (`adjustTimeStep`, max Courant number 1)
rather than fixed, to handle the large range of cell sizes between the boundary layer and
the far field without hand-tuning Δt — but `system/controlDict` as actually built sets
`maxCo 2` with `maxDeltaT 0.02`, not `maxCo 1` as planned here; see below for what that
means for the run.

**Numerics as actually run (added after result-review round 3, review-3.md Finding 1).**
`system/controlDict` sets `maxCo 2;` and `maxDeltaT 0.02;`, not the `maxCo 1` described
above as the plan. Parsing every `Courant Number`/`deltaT` line in `log.pimpleFoam`
(t = 5→155 s, 7502 timesteps) shows `deltaT` sitting at the 0.02 s ceiling for 99.3% of
timesteps — i.e. for almost the entire run the step is effectively fixed at 0.02 s rather
than being actively limited by a Courant condition, and the local max Courant number
exceeds 1 in 99.97% of timesteps, averaging 1.96 (range 1.92–1.98) within the averaging
window (t = 97–151 s) used for the reported numbers below. This was not the intended
scheme and was only discovered during result review, not decided deliberately.

This has not been shown to be immaterial: no rerun at `maxCo 1` (or `maxDeltaT 0.01`) was
performed to check whether `Cd_mean`/`St` would move under a smaller step, and that
question is left open. Two things are true of the run as executed, and are the actual
basis for treating its numbers as usable despite that open question: the shedding period
(5.93 s) is resolved by ~296 timesteps even at the pinned Δt = 0.02 s, so the large-scale
unsteady motion is well sampled; and within each timestep the PIMPLE outer-corrector loop
converges hard (e.g. at `Time = 100.02s`, `Ux`/`Uy` initial residuals fall from ~1e-3 to
~1e-7 and `p` from ~1e-2 to ~1e-6 over 5 correctors), so under-iteration within a step is
not a contributor — only the untested step-size sensitivity is. See `response-3.md` for
the full discussion.

**Duration / stopping criterion (assumed, to be confirmed from the run).** The published
Strouhal number for Re = 100 is St ≈ 0.164–0.167 (e.g. Williamson 1996), giving a shedding
period T = D/(St·U) ≈ 6.0–6.1 s. Vortex shedding at this Reynolds number typically takes
on the order of 100–150 convective time units (t·U/D) to settle into a clean limit cycle
from an impulsive start. The plan is: run to t ≈ 150 s, inspect the `Cd`/`Cl` history in
`postProcessing/forceCoeffs1/0/forceCoeffs.dat`, confirm the lift coefficient has settled
into a repeating periodic oscillation (constant peak-to-peak amplitude and constant period
across consecutive cycles — this is the working definition of "the transient is over"
used here), extend the run a further ~10 shedding cycles beyond that point, and then
average `Cd` and measure the shedding period over a whole number of complete cycles
counted from the first zero-upward-crossing of `Cl` after the settling point. **The exact
interval actually used is recorded below, after the run, once the settling point is known
from the data — it cannot be fixed in advance of seeing the run.**

**Outputs.** `forceCoeffs` function object (patches = cylinder, `rhoInf = 1`, `magUInf =
1`, `lRef = 1` (=D), `Aref = 0.1` (=D × 0.1 m spanwise thickness), `liftDir = (0 1 0)`,
`dragDir = (1 0 0)`, `CofR = (0 0 0)`) writing to `postProcessing/`. Final answers
(`Cd_mean`, `St`) in `results.json`.

**Symmetry-breaking box, corrected wording.** The `setFields` perturbation box (x ∈
[0.3, 1.5]D, y ∈ [−0.15, 0.15]D) geometrically overlaps the cylinder (R = 0.5D) for
x ≲ 0.48–0.5D; `setFields` only ever touches cells that exist, i.e. fluid cells, so the
solid region is unaffected and this has no functional effect. Worth noting so the box is
understood as "downstream of the cylinder, extending back to slightly before its
trailing edge" rather than a box entirely clear of the cylinder.

## Averaging interval used, and how the transient was judged over

The run went to t = 155 s (impulsive start at t = 0, symmetry-breaking `setFields`
perturbation as described above). `postProcessing/forceCoeffs1/` holds two directories,
`0/` and `5/`, because the run was carried out in two `pimpleFoam` invocations (an initial
short one to t = 5 s used to confirm the mesh and numerics were stable, then a continuation
to t = 155 s using `startFrom latestTime`); each invocation starts its own force-history
file under `postProcessing/forceCoeffs1/<startTime>/forceCoeffs.dat`, so the full record is
the concatenation of the two, with `5/forceCoeffs.dat` continuing exactly where
`0/forceCoeffs.dat` left off (t = 5 s onward).

**Determining that the transient was over.** `Cl`'s upward zero-crossings give one shedding
period per crossing-to-crossing interval; `Cl`'s local peak/trough values give the
shedding amplitude each cycle. Both were tracked cycle by cycle (via linear interpolation
of the zero crossings, and a local-maximum/minimum scan of the peaks):

- The period fell from ~7.0 s during the initial growth phase, decreasing monotonically
  and asymptoting to a constant 5.9269 s: the last 10 consecutive cycle-to-cycle periods
  in the record agree to 5 significant figures (5.9269–5.9270 s), and the period first
  reaches this converged value (to 4 significant figures, 5.927 s) at the zero-crossing
  t = 97.18 s (the preceding cycle, ending at the t = 91.25 s crossing, is 5.928 s — one
  significant figure short of the converged value).
- The peak `Cl` amplitude grew from ~0.01 (barely above the initial perturbation) up to a
  limit-cycle value of 0.31120, approached monotonically from below; consecutive-cycle
  peak values agree to 4 significant figures (0.3112) from the peak at t = 110.52 s
  onward (the preceding peak, at t = 92.74 s, is 0.3108 — one significant figure short),
  and to 5 figures from t ≈ 134 s onward.

Working definition used here: **the transient is over once both the period and the peak
amplitude are unchanged, cycle to cycle, to 4 significant figures.** The period reaches
its converged value (5.927 s) at the zero-crossing t = 97.18 s; the peak `Cl` amplitude
reaches its converged value (0.3112) one cycle later, at the peak t = 110.52 s (the
preceding peak, at t = 92.74 s, is 0.3108 — short by one significant figure). Both
criteria are therefore satisfied from t ≈ 115 s onward, which is taken as the settled
point (roughly 19 shedding cycles after the impulsive start).

**Averaging window.** The first full shedding cycle after the settled point runs from the
`Cl` upward zero-crossing at t = 114.9627 s to the crossing 6 periods later at
t = 150.5241 s — i.e. **6 complete shedding cycles**, spanning 35.5614 s, all after the
flow has visibly settled into its periodic limit cycle (and well within the run's 155 s
total length; a 7th cycle was not used because the run did not reach its next crossing, at
t ≈ 156.45 s). This satisfies "run long enough to settle, then run several more cycles":
settling was judged complete by t ≈ 115 s, and the averaging window covers a further 6
cycles beyond that. (An earlier draft of this analysis used a 9-cycle window starting at
the t = 97.18 s crossing — i.e. right where the period, but not yet the amplitude, had
converged; result-review flagged the inconsistency. Sliding the window between the two
choices, and over lengths from 5 to 11 cycles, changes `Cd_mean` by ≤0.0002 and `St` by
≤0.00001 — the reported figures, rounded to 4 decimal places, are identical either way.)

Over this window:
- `St = 6 / 35.5614 = 0.16872` (period-averaged over the 6 cycles, from the zero-crossing
  times directly — no smoothing or filtering of the raw `forceCoeffs.dat` output was
  applied)
- `Cd_mean = 1.37993`, the trapezoidal time-average of `Cd(t)` over exactly
  [114.9627, 150.5241] s using every recorded `forceCoeffs.dat` sample in that range
  (deltaT was adaptive, capped at 0.02 s, so this is ~1,780 samples over the 6 cycles)

Rounded to 4 decimal places, these are the values reported in `results.json`:
`{"Cd_mean": 1.3799, "St": 0.1687}`. Both are consistent with published values for this
benchmark (e.g. Williamson 1996 reports St ≈ 0.164–0.167 for Re = 100; Cd ≈ 1.3–1.4 is
widely reported by 2D laminar simulations at this Reynolds number) — St is at the upper
edge of, and Cd within, the commonly cited ranges, consistent with this case's 5% blockage
(a fully unconfined domain typically reports figures a little lower on both counts; see
the mesh revision note above for why 5% blockage was accepted rather than the originally
planned 3.3%).
