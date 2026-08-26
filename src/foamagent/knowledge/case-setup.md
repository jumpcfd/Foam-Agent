# Case set-up: classify first, then build in order

Prefer matching on **physics first, geometry second**: a lid-driven cavity is a better
starting point for any laminar incompressible box than a differently shaped case with the
wrong solver.

## Classify before you write

Fix these five before touching a file, because together they determine the solver, the
field set and the dictionaries:

| Question | Consequence |
|---|---|
| Steady or transient? | `simpleFoam` family vs `pimpleFoam`/`icoFoam` family; `controlDict` timing |
| Compressible? | `p` in m²/s² vs `p` in Pa; which thermophysical dictionary is needed |
| How many phases? | single-phase vs `interFoam` and an `alpha` field |
| Laminar or turbulent? | whether `k`/`epsilon`/`omega`/`nut` exist at all |
| Heat or buoyancy? | `p` vs `p_rgh`; whether an energy equation is solved |

## Then build it

1. **Mesh** — `blockMeshDict` for block geometry, `snappyHexMeshDict` for imported
   surfaces. The tutorial you picked has a working one.
2. **Fields** in `0/` — one file per field the solver needs, and every patch in the mesh
   named in every field's `boundaryField`.
3. **Properties** in `constant/` — transport, turbulence, thermophysical as applicable.
4. **Numerics** in `system/` — `controlDict`, `fvSchemes`, `fvSolution`. Start
   conservative (upwind, small time step, tight relaxation); loosen once it runs.
5. **`Allrun`** — the sequence of commands, mirroring the tutorial's own.

Write files with your own tools.

---

The classification checklist, the guardrail list and the failure table follow the structure
of `svd-ai-lab/sim-plugin-openfoam` (Apache-2.0), whose OpenFOAM skill is the closest prior
art for this shape of document. Its knowledge targets ESI OpenFOAM; the environment- and
version-specific answers here come from `describe_environment` and the built catalogue
instead.
