# Guardrails: the mistakes that recur

These are the mistakes that recur. They are cheap to avoid and expensive to debug.

- **Do not invent dictionary keys, patch types or solver names.** Every one comes from a
  closed vocabulary. Check the tutorial you are working from, or `commands/<name>.txt`.
- **Do not mix turbulence fields.** k-ε needs `k`, `epsilon`, `nut`; k-ω SST needs `k`,
  `omega`, `nut`; Spalart-Allmaras needs `nuTilda`, `nut`. A mismatched set aborts at
  startup.
- **Do not use `p` where the solver wants `p_rgh`.** Buoyant and VOF solvers use `p_rgh`;
  pure incompressible solvers use `p`.
- **Do not put central differencing on a VOF `alpha` field.** It is unbounded; use
  `vanLeer` or the interface-compression family.
- **Do not assume `0/` exists.** Many tutorials ship `0.orig/` and copy it in `Allrun`.
- **Do not run more MPI ranks than `numberOfSubdomains` in `decomposeParDict`.**
- **Do not treat `checkMesh` warnings as noise when the run is diverging.** Most early
  divergence is mesh quality.
- **Do not raise the time step to finish faster.** Watch the Courant number instead.

---

The classification checklist, the guardrail list and the failure table follow the structure
of `svd-ai-lab/sim-plugin-openfoam` (Apache-2.0), whose OpenFOAM skill is the closest prior
art for this shape of document. Its knowledge targets ESI OpenFOAM; the environment- and
version-specific answers here come from `describe_environment` and the built catalogue
instead.
