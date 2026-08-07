<!-- foamagent: spec review, document 2 -->

# Specification review 2

## Review of `spec.md` — flat-plate Blasius validation case

I read `spec.md`, the prior `review-1.md`/`response-1.md` round (which already fixed the domain-height/blockage issue once), and independently recomputed the load-bearing numbers with `run_script`. Re_L, the blockage-ratio table, the first-cell height, and the total mesh count all check out arithmetically. One issue survived the previous revision, and one omission is new.

### 1. The boundary-conditions table still points the top patch at the *old*, rejected height — reintroducing the exact defect the last review round fixed

**What is wrong:** `spec.md` was revised (per `response-1.md`) to raise the domain height from 0.15 m to 0.55 m specifically because 0.15 m let the top boundary disturb the layer by up to 3.6%, contradicting the request. The prose and assumptions list were updated, but the boundary-conditions table row for the top patch was not — it still says `y = 0.15`. If a mesh/BC file is generated from this table as written, the case reverts to the height that was already flagged and rejected.

**Evidence:**
- Request: *"the top boundary far enough above the plate ... that neither disturbs the layer."*
- Spec, §Geometry: *"Domain height: y ∈ [0, 0.55] (0.55 L)."* and §Assumptions: *"Domain height 0.55 m ... (revised upward from an initial 0.15 m / 3.6% draft after spec review...)"*
- Spec, §Boundary conditions table (unrevised): `| top (y = 0.15) | patch | slip | zeroGradient |`

I recomputed the blockage ratio both ways: at H = 0.55 m, δ*/H = 0.31% / 0.70% / 0.99% at x = 0.1 / 0.5 / 1.0 m — matching the spec's table exactly. At H = 0.15 m, the same calculation gives 1.62% / 2.56% / 3.63% at x = 0.2 / 0.5 / 1.0 m, reproducing the disturbance level the request rules out and the last review round rejected.

**Proposed correction:** Change the boundary-conditions table row to `top (y = 0.55)` so it matches the rest of the document.

### 2. The initial internal field is never stated, despite an explicit instruction to record every assumption

**What is wrong:** The request says *"assume what you must, record every assumption in spec.md,"* and the spec's nine-item assumptions list is otherwise thorough (density, outlet pressure, buffer lengths, top-BC type, turbulence treatment, spanwise depth, convergence criteria, scheme provenance) — but it never states what `internalField` values `U` and `p` are initialized to before SIMPLE iteration begins.

**Evidence:**
- Request: *"Nobody is available to answer questions: assume what you must, record every assumption in spec.md."*
- Spec, §Assumptions summary: nine items, none addressing the initial field (checked §Boundary conditions and §Numerics too — absent there as well).

**Proposed correction:** Add a tenth assumption stating the chosen `0/U` and `0/p` internal field values (e.g., uniform freestream `(1 0 0)` and `0`, to shorten the transient toward steady state) and why.

### 3. Minor: cells-within-δ99 table is consistently one cell higher than a direct recount

Recomputing the geometric cell distribution (r ≈ 1.09997, h₁ ≈ 4.76×10⁻⁵ m, 74 cells) and counting cells whose cumulative height falls within δ99(x) gives 25/33/37 at x = 0.1/0.5/1.0 m, versus the spec's 26/34/38 — a consistent off-by-one, likely a counting-convention difference (e.g., counting the cell straddling δ99 as "inside"). This doesn't change the conclusion (still >30 resolving points near the trailing edge); not worth reopening the mesh design over, but worth a one-character fix alongside item 1 since the table is being touched anyway.

### Correspondence, omission (beyond §2), excess, feasibility — nothing else found

Re_L, viscosity, plate geometry, laminar/steady treatment, solver choice, spanwise `empty` treatment, mesh total (200×74×1 = 14,800, verified), and outputs all check out against the verbatim request. No other silent assumptions or added scope stood out. Solvers/utilities (`simpleFoam`, `blockMesh`, `wallShearStress`, `graphUniform`) are standard OpenFOAM-10 capabilities and the mesh size is trivial for the machine; whether the 5000-iteration cap is reached can't be confirmed before running, which is expected at this stage.
