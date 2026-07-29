---
name: openfoam-cfd
description: Use when the user asks for a CFD simulation in OpenFOAM — setting up a case, running a solver, diagnosing why one failed, or post-processing a result. Drives the Foam-Agent MCP server, which provides the OpenFOAM installation, its tutorials, and asynchronous runs.
---

# OpenFOAM through Foam-Agent

You are the one doing the CFD. Foam-Agent's tools measure this machine, run OpenFOAM,
check a case and read the logs; none of them calls a model. Solver choice, dictionary
contents, and what to change after a failure are yours.

## First, look

Call `describe_environment`. It answers three questions you would otherwise guess at:

1. **Which OpenFOAM is here** — fork (foundation or esi) and version. Their dictionary
   names differ (`physicalProperties` vs `transportProperties`,
   `momentumTransport` vs `turbulenceProperties`), so this decides the syntax you write.
2. **Which solvers exist** — the real contents of `$FOAM_APPBIN`. Never name one that is
   not in that list.
3. **Where the tutorial catalogue is** — `library.catalog`, if one has been built.

If `library` is empty, tell the user to run `foamagent index build` once. Everything below
is much weaker without it.

## Work from a tutorial, not from memory

`catalog.md` is a table of every tutorial this installation ships: case, solver, domain,
category, and the directory holding it. It is around 35 kB — read all of it.

Pick the case closest to what is being asked for and read its files. They are a working,
version-correct answer, which beats recalling OpenFOAM syntax from training data. Prefer
matching on **physics first, geometry second**: a lid-driven cavity is a better starting
point for any laminar incompressible box than a differently shaped case with the wrong
solver.

`by-solver.md` inverts the table when the solver is already decided.
`commands/<name>.txt` holds each application's `-help` output.

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

Write files with your own tools when you have them; use `write_case` when you do not.

## Check, run, read

```
validate_case   → fix what it reports (it costs milliseconds; a failed run costs minutes)
run_start       → returns a run_id immediately
run_tail_log    → watch progress; "latest" follows the log being written
run_status      → running / succeeded / failed / timed_out
classify_errors → when it failed: the category, the line that said so, and what it means
```

Never wait on a solver by polling in a tight loop. Check, do something else, check again.

## What to ask the user

Ask before generating, not after failing, when the requirement leaves out something that
changes the answer: fluid properties (viscosity, density), inlet and outlet conditions,
whether the flow is turbulent, the domain size, or the physical duration. A CFD case with
invented numbers looks exactly like one with correct numbers, which is what makes guessing
here worse than asking.

This holds even when a defensible number exists. "Re=100 is the textbook cavity case" is a
guess about which case was wanted, not a fact about this one, and running it spends minutes
of solver time on a question one sentence would have settled. Ask, and end the turn there:
a reply that is only a question is a finished piece of work. Announcing the assumption
afterwards does not substitute for asking first.

## Guardrails

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

## When it fails

Work from the first error, not the last. `classify_errors` gives you the category:

| Category | What it means | Usual fix |
|---|---|---|
| `missing_keyword` | A dictionary lacks an entry the solver reads | Add it; the message names both |
| `missing_mesh` | No `constant/polyMesh/points` | The mesher never ran, or ran into an error of its own |
| `patch_mismatch` | Field files and mesh disagree on patch names | `validate_case` prints both lists |
| `duplicate_face` | A face is in two patches in `blockMeshDict` | Remove it from one |
| `unknown_solver` | A type name this build does not have | The message lists the valid ones |
| `diverged` | NaN, floating point exception | Reduce the time step; go back to upwind; check the mesh |
| `dimension_mismatch` | Incompatible units | Check the `dimensions` line of the fields named |
| `unrecognised` | No known pattern matched | Read the excerpt it returns |

After a fix, rerun from the failing step rather than from scratch when the mesh is
unchanged.

## Reporting back

State the solver and why, the mesh, the boundary conditions, whether the run reached `End`,
the residual behaviour, and the requested quantity with units. Say plainly when a value was
assumed rather than given -- which should only ever be a value the section above does not
list, since those are asked about instead of assumed.

---

The classification checklist, the guardrail list and the failure table follow the structure
of `svd-ai-lab/sim-plugin-openfoam` (Apache-2.0), whose OpenFOAM skill is the closest prior
art for this shape of document. Its knowledge targets ESI OpenFOAM; the environment- and
version-specific answers here come from `describe_environment` and the built catalogue
instead.
