<!-- foamagent: result review, document 3 -->

# Result review 3

# Review: 2D flow past a circular cylinder at Re = 100

Case: `/home/tateb/foamagent-validation/cylinder_re100`. This is the third review round for this case (two spec-review rounds already settled; this is the first review of the completed *result*). I read `spec.md`, `review-1.md`/`response-1.md`, `review-2.md`/`response-2.md`, the case dictionaries, the logs, `postProcessing/forceCoeffs1/`, and `results.json`, and ran independent arithmetic against the raw data with `run_script` (scripts saved under `review-work/3/` in the case directory, referenced by filename below).

## Finding 1 — Numerics section of spec.md does not describe the run that actually happened (Courant number, adaptive time step)

**Severity: Qualifies the result.** Not a correctness bug — the run is stable and the forces are converged (see Finding 4-onward below) — but the documented methodology and the executed methodology disagree, and the accuracy consequence of that disagreement is untested.

**Evidence.** `spec.md`'s Numerics section states: *"Time step is adaptive (`adjustTimeStep`, max Courant number 1)."* The actual `system/controlDict` sets `maxCo 2;` (not 1), and `script-13.py` parsed every `Courant Number` / `deltaT` line in `log.pimpleFoam` (7502 timesteps, t = 5→155 s):

- `deltaT` sits at the `maxDeltaT` ceiling of 0.02 s for **99.3%** of timesteps (7450/7502) — i.e. for almost the whole run the "adaptive" time step is not actually being limited by any Courant condition, it is a fixed step pinned against the ceiling.
- The local **max** Courant number is **> 1 in 99.97%** of timesteps, and averages **1.96** (range 1.92–1.98) specifically within the averaging window used for the reported numbers (t = 97–151 s).

So the case runs with an effectively fixed Δt = 0.02 s and a realized peak local Courant number of ~2, not the adaptive/Co≤1 scheme spec.md describes. This matters because the time scheme is first-order Euler; PIMPLE's implicit treatment keeps this unconditionally stable, but local truncation error at Co≈2 in the finest (near-wall) cells is not automatically negligible for the boundary-layer dynamics that set separation and hence drag.

**Mitigating evidence.** Two things argue this probably isn't corrupting the answer: (a) the shedding period (5.93 s) is still resolved by ~296 timesteps, so the *large-scale* unsteady motion is well sampled even if local near-wall cells see Co≈2; (b) within a single timestep the PIMPLE outer loop converges hard — at t = 100 s the `Ux`/`Uy` initial residual falls from ~1e-3 to ~1e-7 and `p` from ~1e-2 to ~1e-6 over the 5 outer correctors (`log.pimpleFoam`, `Time = 100.02s` block) — so under-iteration within a step isn't the issue, only the step size itself.

**How to settle it.** Halve `maxDeltaT` to 0.01 s (or set `maxCo 1` for real) and rerun; compare `Cd_mean`/`St` to the values here. If the change is inside the ~0.01% window-sensitivity found in Finding 3, this is fully settled as immaterial. It isn't settled by anything in this run alone.

## Finding 2 — spec.md's stated convergence timestamps don't match the data it claims to summarize

**Severity: Notes** (documentation-accuracy issue; does not change the reported numbers).

**Evidence.** `spec.md` states the shedding period "first reaches [5.927 s, 4 sig figs] at the zero-crossing t = 91.25 s" and the `Cl` peak amplitude "agree[s] to 4 significant figures (0.3112) from t ≈ 92.7 s onward." Independently recomputing zero-crossings and peaks from the raw `forceCoeffs.dat` (`script-4.py`, `script-14.py`):

| t (crossing) | period (this review) | spec's claim |
|---|---|---|
| 91.25 s | 5.92767 → rounds to **5.928**, not 5.927 | claims 5.927 reached here |
| 97.18 s | 5.92728 → rounds to **5.927** | actually first reached here |

| t (peak) | Cl peak (this review) | 4-sig-fig value |
|---|---|---|
| 92.74 s | 0.310834 | 0.3108 |
| 110.52 s | 0.311155 | **0.3112** (first reached here) |

The claimed convergence times are each about one shedding cycle (~6 s) too early relative to what the raw data actually show. The qualitative conclusion ("settled well before t=100 s") still holds — but the specific figures written down to justify it don't reproduce.

**How to settle it.** Already settled by direct recomputation above; `spec.md`'s wording should be corrected, no new run needed.

## Checks that passed, with the arithmetic behind them

**Reported `Cd_mean`/`St` are correct and robust.** Concatenating both `forceCoeffs.dat` files (`script-3.py`, 8022 samples, t=0→155 s, monotonic, no gaps) and independently re-running spec's own zero-crossing/trapezoidal method reproduces `Cd_mean = 1.379915` and `St = 0.168721` (`script-5.py`) against the reported `1.3799`/`0.1687` — exact. Sliding the averaging window ±2 shedding cycles and varying its length from 5 to 11 cycles (`script-6.py`) changes `Cd_mean` by ≤0.0002 and `St` by ≤0.00001 — the answer is not sensitive to the specific window chosen, so the transient-over judgement, even with the timing imprecision in Finding 2, doesn't threaten the headline numbers.

**Mass is conserved to solver precision.** Parsing the `phi` boundary field at ten times spanning the run (`script-11.py`), net flux across all six patches is O(1e-7) against a through-flow of 2.0 m³/s (i.e. relative imbalance ~5e-8–4e-7) at every time checked, including inside the averaging window. `down`/`up` (slip) carry exactly zero flux at every face, as they should for a slip condition, not merely in aggregate.

**Physical consistency — no artificial lift bias, correct Cd/Cl frequency relationship.** Mean `Cl` over the averaging window is `-2.6e-6` (`script-5.py`) — the one-sided `setFields` symmetry-breaking perturbation left no residual bias once the limit cycle was reached, as it should not. `Cd` oscillates with mean peak-to-peak period 2.9635 s (`script-18.py`), matching half the `Cl` shedding period (5.9269/2 = 2.9635 s) to 4 significant figures — this is the textbook signature that drag responds to vortex shedding from *either* side of the cylinder (frequency-doubled relative to lift), and is strong evidence the simulation is reproducing genuine shedding physics rather than a numerical artifact of some other frequency.

**Mesh geometry and grading reproduce exactly.** From `system/blockMeshDict`'s O-grid block definition (25 cells, R=0.5→0.7, `simpleGrading` ratio 10), a geometric-series calculation (`script-16.py`) gives a wall cell radial size of 0.0020125 m — matching `checkMesh`'s reported minimum edge length (0.00201248 m) to 5 figures. Domain volume computed directly from the stated geometry (33 m × 20 m rectangle minus the cylinder, × 0.1 m span, `script-19.py`) gives 65.92146 m³ against `checkMesh`'s reported 65.9215 m³ (relative difference 6e-7). Blockage ratio D/H = 1/20 = 5%, as stated.

**Boundary-layer resolution — indicative pass, not rigorously validated.** A local-similarity (Blasius-analogy) estimate of the laminar boundary-layer thickness around the cylinder shoulder (θ=30°–100°) gives δ₉₉ ≈ 0.26–0.33 D (`script-17.py`) — this is an order-of-magnitude estimate for a curved, adverse-pressure-gradient boundary layer using a flat-plate formula, not a validated cylinder-specific number, so treat it as indicative only. Against that estimate, the O-grid's 25 graded cells span 0.2 D radially with a 0.002 D wall cell, i.e. roughly 20+ cells fall within/around the estimated boundary-layer thickness — consistent with adequate near-wall resolution for a laminar case, but this was not checked against an actual extracted near-wall velocity profile.

**`checkMesh` and the solver log are clean.** `Mesh OK`, zero failed geometry checks, max non-orthogonality 43.9°, max skewness 0.50, max aspect ratio 31 — all within OpenFOAM's own default thresholds. `grep` across the full 435,183-line `log.pimpleFoam` for `FATAL|Warning|blown up|diverg|nan|inf|failed` returns nothing, and the continuity-error trace stays at ~1e-8–1e-7 cumulative throughout.

## Literature comparison — indicative only, sourcing incomplete

I attempted to pull a primary comparison table (Rajani/Kandasamy/Majumdar 2009, Qu et al. 2013, Posdziech & Grundmann 2007, and others) via `WebFetch`, but every PDF fetched in this session returned unreadable/compressed content, and ResearchGate blocked direct access (403) to a table page a search engine had already surfaced (`Results of flows passing a cylinder at Re=100`, ResearchGate tbl1_257439845). I could not open and read a primary source with numeric comparison values this session.

What I have is second-hand, from search-engine summaries rather than an opened document, and should be weighted accordingly:
- Williamson (1996), *Vortex Dynamics in the Cylinder Wake*, Ann. Rev. Fluid Mech. 28:477–539 — widely and consistently cited (across many independent search results) as St ≈ 0.164–0.167 at Re=100. This is the same figure `spec.md` already cites.
- Park, Kwon & Choi (1998) — a search-engine-summarized ResearchGate table reports Cd_mean ≈ 1.33, St ≈ 0.165 at Re=100, for what is described elsewhere as a large/near-unconfined domain.
- Multiple independent searches on blockage effects agree qualitatively that increasing blockage ratio increases both Cd and St for a confined cylinder, but I could not retrieve a quantitative correction formula from a source I actually opened.

Against these indicative numbers: computed `St = 0.1687` is about 1% above the top of the 0.164–0.167 range; computed `Cd_mean = 1.3799` is about 3.75% above the indicative unconfined value of 1.33. Both are in the direction spec.md's own reasoning predicts from 5% blockage (blockage raises both Cd and St), and both are inside the range of a plausible blockage correction — but I have not verified a blockage-correction formula against a primary source, so this remains a plausibility argument, not a settled comparison. Retrieved 2026-08-07 (search-engine summaries only; dates of underlying papers 1996/1998 as cited).

**How to settle it properly:** rerun spec.md's originally-planned larger domain (15D/35D/15D) — the meshing problem that forced the smaller domain (sliver cells, per the revision note in spec.md) is a meshing-topology issue unrelated to whether a wider domain changes the physical answer, and re-deriving that mesh with the corrected O-grid-to-outer-block topology used here would give a direct, in-house zero-blockage-limit estimate to compare against, rather than relying on someone else's blockage correction.

## Summary

Ranked by severity: **(1)** the documented adaptive/Co≤1 time-stepping doesn't match the actual run (fixed 0.02 s step, Co≈2) — qualifies the result pending a Δt-sensitivity check; **(2)** spec.md's stated convergence timestamps are off by about one shedding cycle versus the raw data — a documentation defect, not a numerical one. Everything else checked — the two headline numbers, mass conservation, within-timestep convergence, the Cd/Cl frequency relationship, mesh grading arithmetic, and domain geometry — reproduced exactly or landed within expected physical bounds under independent recomputation. The literature comparison is directionally consistent but should be read as indicative, since I could not open a primary source with a validated comparison table this session.
