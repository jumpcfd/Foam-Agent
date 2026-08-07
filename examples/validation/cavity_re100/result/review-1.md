<!-- foamagent: spec review, document 1 -->

# Specification review 1

## Summary

The specification is a close, careful match to the verbatim request. I went through it clause by clause, verified the Reynolds-number arithmetic and the OpenFOAM dictionary/unit conventions it relies on, and checked what solver/utility feasibility I could from a sandbox with no OpenFOAM install. I found one genuine open item (not yet an error, just not yet done) and one limit on what I could verify myself. Everything else checked out.

## 1. The mesh-independence record the request explicitly asked for does not exist yet

**What is wrong:** the request requires the spec to *record how the mesh was shown to be fine enough*; the spec currently contains only a proposed method and an empty placeholder, not a result.

**Evidence:**
> "use a mesh fine enough that those profiles no longer move when it is refined, and record in spec.md how you satisfied yourself of that." — request

> "The specific grids tested, the comparison metric obtained, and the resolution chosen are recorded as an addendum below once the study is run." … "## Addendum: grid-convergence result\n\n*(to be filled in after the mesh study is run)*" — spec.md:113-114, 122-124

The proposed method itself is sound (three uniform grids, compare centreline profiles between the two finest, pick the coarsest that agrees to within a stated tolerance) and directly answers what was asked. This isn't a design flaw — it's simply that the deliverable the sentence calls for (the record) doesn't exist in the document yet, which matters because "not yet run" is exactly the state this review is checking.

**Proposed correction:** no change needed to the plan. Before this spec is treated as complete, run the 32/64/128 study and fill in the addendum with the actual per-resolution profile comparison and the resolution chosen — otherwise the case should not be considered to have satisfied this line of the request yet.

## 2. Solver/utility feasibility could not be independently confirmed from this review

**What is wrong:** the spec asserts `simpleFoam`, `blockMesh`, the `sample` function object, and the `physicalProperties`/`momentumTransport` file layout are all valid for "this OpenFOAM 10 installation," but the review sandbox (`run_script`) has no OpenFOAM install to check against — `shutil.which()` returned `None` for every solver/utility name and `WM_PROJECT_DIR`/`FOAM_APPBIN` are unset in this environment.

**Evidence:** spec.md:49 ("`simpleFoam` is present in this OpenFOAM 10 installation's solver list") and spec.md:51-52 (momentumTransport syntax "confirmed... against the tutorial catalogue") are claims I could not execute against directly.

I cross-checked what I could against the public OpenFOAM v10 user guide instead: it confirms `constant/physicalProperties` (not `transportProperties`) is the correct file for `nu` in v10, with the exact syntax `nu [0 2 -1 0 0 0 0] 0.01;` the spec uses, and that `momentumTransport` (formerly `turbulenceProperties` before v8) is the correct dictionary name. So the spec's technical claims are consistent with public documentation — I just can't call this a verified calculation the way I could the Reynolds number.

**Proposed correction:** none needed to the spec's content; noting this as a limit on my own review rather than a defect. Whoever builds the case should let `blockMesh`/`simpleFoam` themselves be the check.

## Checks that found nothing

- **Reynolds number arithmetic** — verified by computation, not eyeballing: `Re = U·L/ν = 1×1/0.01 = 100`, matching both the request and spec.md:36.
- **Dimension set for ν** — `m²/s` → OpenFOAM `[0 2 -1 0 0 0 0]`, computed and cross-checked against the v10 tutorial: correct.
- **Geometry, boundary conditions, 2D treatment** — square 1 m cavity, lid U=(1 0 0), no-slip on the other three walls, single-cell-thick z with `empty` front/back: all have exact counterparts in the spec, no drift.
- **Turbulence treatment** — request says laminar; spec sets `simulationType laminar;`, no turbulence fields. Matches.
- **Time treatment / stopping criterion** — request's "run until it stops changing" is read as steady-state via `simpleFoam` + `residualControl`, and the reasoning for that substitution (rather than a judged transient cutoff) is recorded as an explicit, well-justified assumption, exactly as the request instructed ("assume what you must, record every assumption").
- **Initial condition** — not specified by the request; spec assumes rest, flagged explicitly as an assumption. No hidden assumption.
- **Computational size** — largest mesh in the convergence study is 128×128 = 16,384 cells; trivially sized for the question being asked, no over- or under-resourcing.
- **Excess** — nothing in the spec adds scope, constraints, or physics beyond what was requested; the one piece of added context (naming Ghia, Ghia & Shin 1982 as the comparison dataset) is informational framing that doesn't change what gets built or run, and doesn't need to be flagged as a decision the user should be asked about.

**Sources:**
- [OpenFOAM v10 User Guide - 2.1 Lid-driven cavity flow](https://doc.cfd.direct/openfoam/user-guide-v10/cavity)
- [OpenFOAM v10 User Guide - Chapter 2 Tutorials](https://doc.cfd.direct/openfoam/user-guide-v10/tutorials)
