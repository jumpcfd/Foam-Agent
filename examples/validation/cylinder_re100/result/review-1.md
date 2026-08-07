<!-- foamagent: spec review, document 1 -->

# Specification review 1

## Review of spec.md — cylinder_re100

### 1. The spec bets the entire run on a coin flip it doesn't need to make (High)

**What is wrong.** The spec deliberately builds a domain that is *symmetric* about the wake centerline and then relies on floating-point truncation error alone to break that symmetry and trigger shedding — a strategy the reference tutorial it otherwise follows explicitly avoids, and one the literature documents as unreliable at exactly this kind of Reynolds number.

**Evidence.**

- Request: *"At this Reynolds number the wake sheds vortices periodically, so the flow is unsteady and laminar."* — periodic shedding is presupposed as the physical outcome to be measured, not something that needs to be coaxed into happening.
- Spec, Geometry: *"re-derived with a symmetric, much larger domain (the tutorial's own domain is asymmetric and deliberately close to a wall... — not applicable here)."*
- Spec, Initial conditions: *"the mesh's own asymmetries and truncation error are normally sufficient to break symmetry and trigger shedding within the initial transient."*
- I pulled the actual OpenFOAM-10 `offsetCylinder` tutorial (`system/blockMeshDict`) to check the spec's characterization of it: the domain runs from x = −5 to 5, y = −1.5 to 2.5 around a D≈1 cylinder centered at the origin — i.e. the cylinder sits off-center in the channel (1.5D below, 2.5D above), a genuinely asymmetric mesh. The spec is right that this differs from an unconfined benchmark, but the *reason* the tutorial is built asymmetric is also, in practice, to guarantee shedding starts promptly rather than depending on round-off — it isn't purely a confinement study.
- Published literature on this exact problem states it plainly: *"When the domain geometry and approaching flow conditions are symmetric, vortex triggering requires a long run-time, especially for low Reynolds numbers... it is well known that the shedding process needs to be initiated artificially for flows in the threshold regime."* (see sources below). Re = 100 is only ≈2× the critical Re ≈ 47, still close enough to the threshold that this caution applies.

The spec's own duration budget (t ≈ 150 s to reach a settled periodic state, extend ~10 cycles, i.e. ≈24–25 shedding periods total) is sized for *settling after shedding has already started*. It has no margin, and no contingency, for the case where a symmetric mesh with a symmetric impulsive-start IC takes an unpredictably long time (or effectively forever, numerically) to depart from the unstable symmetric solution. Given the instruction *"Nobody is available to answer questions... assume what you must... and finish the run,"* a silent stall here is the failure mode with no one to catch it.

**Proposed correction.** Either (a) keep the symmetric domain but add an explicit, cheap symmetry-breaking trigger — e.g. a brief asymmetric perturbation to the initial condition or wall BC for the first few time units, which the spec itself notes in the literature check "does not bring any energy to the flow" when done via the IC — and record that as an assumption; or (b) add a monitoring/contingency rule to the stopping-criterion section: *"if Cl remains within machine-symmetric noise (no growth above X) by t = Y, apply a perturbation and restart the clock."* Either way this should be decided and written down now, not discovered mid-run.

Sources: [Triggering vortex shedding for flow past circular cylinder by acting on initial conditions](https://www.sciencedirect.com/science/article/abs/pii/S0045793014002412), [OpenFOAM-10 offsetCylinder blockMeshDict](https://raw.githubusercontent.com/OpenFOAM/OpenFOAM-10/master/tutorials/incompressible/pimpleFoam/laminar/offsetCylinder/system/blockMeshDict)

### 2. Minor: the "matches the tutorial" claim for gradSchemes is not quite accurate (Low)

**What is wrong.** The spec says its spatial schemes match the shipped `offsetCylinder` tutorial verbatim, but the tutorial's `gradSchemes` default is `leastSquares`, not `Gauss linear`.

**Evidence.**

- Spec, Numerics: *"linear/`Gauss linear` spatial schemes matching the `offsetCylinder` tutorial's own `fvSchemes`/`fvSolution`... these are the shipped, validated settings for this exact solver/regime."*
- Actual tutorial `system/fvSchemes` (OpenFOAM-10): `gradSchemes { default leastSquares; }` — `div(phi,U)` and the laplacian/interpolation/snGrad entries do match what the spec describes, but the gradient scheme does not.

This has no bearing on what the user asked for and either scheme is a defensible choice for this mesh, so it's not consequential to the physics — but the spec is citing tutorial fidelity as its justification for these settings, and that citation is factually off for one entry.

**Proposed correction.** Either set `gradSchemes` to `leastSquares` to actually match the cited tutorial, or drop the "matching the tutorial" justification for `Gauss linear` gradients and state the independent reason for choosing it.

### Checks that found nothing

- **Reynolds number arithmetic**: Re = U·D/ν = 1×1/0.01 = 100, computed via `run_script` — agrees with both the request and the spec.
- **Blockage/domain size**: lateral 15D each side → blockage = D/30D = 3.33%, computed via `run_script` — matches the spec's stated figure and is consistent with the request's "far enough... that they do not change the wake."
- **Strouhal-based period estimate**: St ≈ 0.164–0.167 → T ≈ 6.0–6.1 s, computed via `run_script` — matches the spec's stated range, and t = 150 s corresponds to ≈150 convective time units / ≈25 shedding cycles, consistent with the spec's stated settling and extension plan.
- **Boundary conditions, initial conditions (aside from the symmetry issue above), spanwise/empty-patch treatment, purpose, turbulence treatment, and output specification** (`forceCoeffs`, `results.json` schema, deferred averaging-interval note) all have direct, faithful counterparts in the request. No excess conditions were found — every assumption the spec adds beyond the literal request is both necessary to build the case and explicitly labeled as an assumption, as the request itself asked for.
- **Feasibility of solver/mesh size**: `pimpleFoam` is an appropriate, available solver for this regime; ~26,000 cells and an adaptive Courant-limited time step (first cell ≈2 mm at the wall, confirmed by grading arithmetic) imply on the order of 10⁴ time steps to cover the full run — a small, fast case with no evident feasibility problem.
