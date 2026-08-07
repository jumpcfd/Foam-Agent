# Specification: 2D lid-driven cavity, Re = 100

## Request, verbatim

> Compute the two-dimensional lid-driven cavity flow at a Reynolds number of 100.
>
> The cavity is a square of side 1 m. The top wall moves in the +x direction at a constant
> 1 m/s; the other three walls are stationary and no-slip. The fluid is incompressible and
> Newtonian with a kinematic viscosity of 0.01 m^2/s, so the Reynolds number based on the lid
> speed and the cavity side is 100. The flow is laminar and two-dimensional: use a single cell
> in the third direction with empty boundaries. Run until the flow has stopped changing.
>
> The result will be compared against published velocity profiles along the cavity's
> centrelines, so use a mesh fine enough that those profiles no longer move when it is
> refined, and record in spec.md how you satisfied yourself of that.
>
> Build the OpenFOAM case in /home/tateb/foamagent-validation/cavity_re100 (create it; do not
> make a subdirectory inside it for the case).
>
> Nobody is available to answer questions: assume what you must, record every assumption in
> spec.md, and finish the run. Do not end your turn while the solver is still running --
> run_status takes a wait_seconds.

## Purpose

Reproduce the classic lid-driven cavity benchmark at Re = 100 so that the steady-state
centreline velocity profiles (u along the vertical centreline x = 0.5, v along the
horizontal centreline y = 0.5) can be compared against the published tabulated values of
Ghia, Ghia & Shin (1982), *"High-Re solutions for incompressible flow using the
Navier-Stokes equations and a multigrid method"*, J. Comput. Phys. 48(3), which is the
standard reference dataset for this exact problem (Re = 100, unit square, unit lid speed).

## Physics and solver choice

- 2D, incompressible, laminar, single-phase, Newtonian, steady-state.
- Re = U_lid * L / nu = 1 * 1 / 0.01 = 100, matching the request.
- **Assumption:** "run until the flow has stopped changing" is read as "run to steady
  state." At Re = 100 the lid-driven cavity is known to have a unique, stable steady
  solution (2D cavity flow only becomes unsteady above roughly Re ~ 8000, far beyond 100),
  so a steady-state solve is the correct and most efficient way to satisfy this
  requirement, and it lets convergence be checked with explicit residual targets rather
  than by eyeballing a transient run.
- **Solver: `simpleFoam`** (SIMPLE steady-state algorithm), not `icoFoam`. `icoFoam` is
  transient (PISO) and this OpenFOAM installation's transient solvers have no built-in
  "stop when converged" criterion, which would leave "has it stopped changing" as a
  judgement call on a truncated transient. `simpleFoam` supports `residualControl` in
  `fvSolution`, which stops the run automatically once the field residuals fall below
  stated thresholds -- a direct, auditable answer to "stopped changing." `simpleFoam` is
  present in this OpenFOAM 10 installation's solver list.
- **Laminar, not turbulent:** `constant/momentumTransport` sets `simulationType laminar;`
  (confirmed as valid syntax against `incompressible/pimpleFoam/laminar/pitzDailyPulse` in
  the tutorial catalogue for this same OpenFOAM version). No turbulence model is solved for
  (no k, epsilon, omega, nut fields), consistent with Re = 100 being deep in the laminar
  regime and with the request's explicit "the flow is laminar."

## Geometry

- Square cavity, 1 m x 1 m in x-y, built with `blockMesh` (`convertToMeters 1`).
- **Assumption:** the third (z) direction is given an arbitrary extent of 1 m with a
  single layer of cells and `empty` patches on the front and back faces. Because the front
  and back patches are `empty` (2D solution, zero gradient/flux normal to those faces
  enforced by construction), the chosen z-thickness has no effect on the computed u, v, p
  fields -- only the mesh's x-y resolution matters. 1 m was picked simply so the single
  cell is roughly cubic at coarse resolutions; it carries no physical meaning.
- Mesh: uniform Cartesion grid in x and y (`simpleGrading (1 1 1)`), resolution chosen by
  the grid-convergence study below.

## Boundary conditions

- **Top wall (`movingWall`):** U = fixedValue (1 0 0) m/s; p = zeroGradient.
- **Left, right, bottom walls (`fixedWalls`):** U = noSlip (u = v = 0); p = zeroGradient.
- **Front/back (`frontAndBack`):** empty.
- **Pressure reference:** the domain is fully enclosed (Neumann p on every wall), so
  `fvSolution` fixes `pRefCell 0; pRefValue 0;` in the `SIMPLE` sub-dictionary to pin the
  otherwise-arbitrary pressure level.

## Material properties

- `constant/physicalProperties`: `nu [0 2 -1 0 0 0 0] 0.01;` (kinematic viscosity, as
  given). Density is not needed: the incompressible solvers here work in kinematic
  pressure p/rho, consistent with the tutorial `cavity` case for this OpenFOAM version.

## Initial conditions

- U = (0 0 0) m/s and p = 0 throughout, at t = 0 (the SIMPLE iteration count, not physical
  time, since this is a steady-state solve). **Assumption:** starting from rest is the
  natural, unbiased choice for a steady solve with no other information given.

## Convergence / stopping criterion

- `simpleFoam` with `residualControl`: p and U residuals both below **1e-6**.
  **Assumption:** this is tighter than the 1e-2/1e-3 typically used for
  engineering-accuracy RANS cases (e.g. the `pitzDaily` tutorial), chosen deliberately
  because the result here is being compared digit-by-digit against a published reference
  profile, not just checked for engineering plausibility.
- `endTime` set high enough (iteration cap) that the residual target is reached rather
  than the iteration cap; if the cap is hit first, that is treated as non-convergence and
  the case is re-run with a higher cap or relaxed under-relaxation, not silently accepted.

## Mesh resolution / grid-independence check

**Assumption/method:** no target grid was specified, so grid independence is established
empirically rather than assumed from the literature. Before building the final case,
uniform grids of 32x32, 64x64 and 128x128 cells are each run (in scratch case
directories outside `cavity_re100`, to satisfy "do not make a subdirectory inside it for
the case") to full residual convergence (see criterion above). For each resolution, u(y)
along x = 0.5 and v(x) along y = 0.5 are extracted with a `sets` function object
(`sample`, `cellPoint` interpolation) at matching sample points. The resolutions are
judged grid-independent once the centreline profiles from the two finest grids differ
negligibly (target: max difference across the profile below ~1% of the lid speed, 0.01
m/s). The final mesh used for the reported case is the coarsest of the grids tested that
meets this criterion (using a finer-than-necessary mesh only adds runtime with no benefit
to the comparison). The specific grids tested, the comparison metric obtained, and the
resolution chosen are recorded as an addendum below once the study is run.

## Outputs

- Steady-state U and p fields.
- Centreline profiles u(y) at x = 0.5 and v(x) at y = 0.5, sampled with the `sets`
  function object, for comparison against Ghia et al. (1982) Table I (Re = 100 columns).
- Net pressure and viscous force on the wall patches, from a `forces` function object
  (`postProcessing/wallForces`), added after the result review below asked for an exact
  momentum-balance check rather than the reviewer's own approximate finite-difference
  estimate. For a closed, steady cavity with no body force the total force should sum to
  zero; this is not a quantity the request asked for directly, but it is a cheap,
  independent confirmation that the converged solution is physically consistent.

## Addendum: grid-convergence result

Three uniform grids were run as `simpleFoam` (steady, laminar, `residualControl` p/U <
1e-6) in scratch case directories outside `cavity_re100` (`cavity_re100_study32`,
`_study64`, `_study128`), otherwise identical to the final case described below. Each
converged well before the iteration cap (5000): 32x32 converged in 415 iterations, 64x64
in 1232, 128x128 in 3810. The raw sampled centreline data and convergence confirmation
from each of the three runs is archived under `gridStudy/<N>x<N>/` in this case
directory, so the comparison below can be recomputed without re-running the study.

Centreline profiles (u(y) at x = 0.5, v(x) at y = 0.5) were sampled at the converged state
with a `sets` function object and interpolated onto a common 201-point grid to compare
resolutions directly:

| comparison | max &#124;&Delta;u&#124; (m/s) | max &#124;&Delta;v&#124; (m/s) | rms &Delta;u | rms &Delta;v |
|---|---|---|---|---|
| 32x32 vs 64x64   | 0.00373 | 0.00517 | 0.00196 | 0.00264 |
| 64x64 vs 128x128 | 0.00091 | 0.00094 | 0.00049 | 0.00043 |

The differences shrink by roughly 4x as the grid is halved (consistent with the
discretisation's order of accuracy), and even the 64 vs 128 comparison is two orders of
magnitude below the lid speed (1 m/s) -- both pairs are in fact already inside the ~1%
(0.01 m/s) tolerance stated above, so by the letter of the stated rule the 32x32 grid
would already qualify.

**Decision:** the final case nonetheless uses the **128x128** mesh, not the coarsest
grid that technically clears the tolerance. Reasons: (1) the tolerance above was checked
against the max/rms difference over the whole centreline, which can hide a large relative
error in the low-magnitude secondary-vortex region of the profile (the corner eddies,
which are also compared qualitatively against Ghia et al.) even when the dominant-motion
region is well converged; (2) 128x128 has roughly the same cell count as the 129x129
grid used in the Ghia et al. (1982) reference -- note this mesh is uniform, while Ghia et
al.'s was wall-clustered, so equal cell count does not imply equal near-wall resolution;
this point is offered as loose corroboration only, not as the basis for the
grid-independence conclusion, which rests on (3); (3) the cost is negligible -- the
128x128 run took 37 s, and 64x64 -> 128x128 already changes the profiles by under 0.1%
of the lid speed, so 128x128 is judged grid-independent with a comfortable margin above
the stated tolerance, on this case's own convergence trend alone.
