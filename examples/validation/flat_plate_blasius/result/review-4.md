<!-- foamagent: result review, document 4 -->

# Result review 4

# Result review — flat-plate Blasius validation

## Context

This is the **first review of the second completed run**. `spec.md`, `review-3.md` and the two spec-review rounds (`review-1`/`response-1`, `review-2`/`response-2`) were read in full; that history is not re-litigated. Briefly: `review-3` found that the first completed run (domain height 0.55 m, `slip` top) suffered a confinement effect — the impermeable top boundary forced the outer flow to accelerate as the boundary layer displaced streamlines, producing 15–33% errors against Blasius near the trailing edge. In response, the top patch was switched to `freestream`/`freestreamVelocity`/`freestreamPressure` and the case was rerun. **No `response-3.md` exists** — the fix is recorded only as revision notes inside `spec.md` itself.

The first thing this review had to establish was whether that rerun actually happened, since `spec.md` promises "see the Results section for the outcome" and no such section exists anywhere in the file or the directory (`grep -n Results spec.md` → only the dangling reference itself, line 84). It did happen: `log.simpleFoam` shows a single continuous run starting at `Time = 0`, converging at **iteration 1640** (not 1521, the old run's endpoint), and `0/U`/`0/p` on disk carry `freestreamVelocity`/`freestreamPressure`. The postprocessing directories at `.../1521/` are stale leftovers from the superseded `slip` run that `Allrun` never cleaned before the rerun (see Finding 3). All analysis below uses time **1640**, the genuine final state, not 1521.

---

## 1. The confinement effect review-3 diagnosed was reduced, not resolved — the trailing-edge Blasius comparison is still degraded

**Severity: qualifies the result.** The plate is usable for comparison up to roughly x≈0.7 (errors mostly single-digit); the last ~20–30% of the plate, including the trailing-edge station the spec's own output table is built around, still disagrees with Blasius by double digits.

**Evidence.**

- **Edge velocity** at y = 0.05 m (`review-work/4/script-4.py`, reading `postProcessing/profile_*/1640/line.xy`): rises monotonically from **+0.61%** at x=0.2 to **+1.11%** at x=1.0. Under `slip` (per `spec.md`'s own account of the prior run) it was +1.35% at the trailing edge. The `freestream` fix cut the excess by only ~18% relative — it did not eliminate it.
- **Skin friction** (`review-work/4/script-8.py`, `script-9.py`, reading `postProcessing/plateWallShearStress/1640/plate.xy` against Cf=0.664/√Re_x): agreement is good and smooth from the leading edge out to x≈0.65 (error ≤3%), then grows **monotonically and smoothly** — 5% at x=0.8, 12% at x=0.92, **27% at x=0.98**, easing slightly to 25% at the last sampled face. The smoothness of this growth (no jump at the last cell) is itself evidence this is a real, growing favourable-pressure-gradient effect, not a mesh/corner artifact.
- **δ\*, θ** (`review-work/4/script-6.py`, `script-15.py`): I solved the Blasius similarity ODE myself by RK4 shooting (f''(0)=0.332057, matching the standard published constant to 6 figures, and f'(η) matching a published table — Schlichting-derived, e.g. f'(1)=0.32979, f'(3)=0.84605, f'(5)=0.99155 — to 5 significant figures; script `review-work/4/script-5.py`). Interpolating the CFD profiles onto it, with the deficit integral cut off at 3×δ99(x) to avoid contaminating the result with the far-field tail (same robustness check review-3 used):
  - Normalized by each station's own **local edge velocity**: δ* error −0.65% (x=0.2) growing to **−11.5%** (x=1.0); θ error −0.93% growing to **−6.0%**.
  - Normalized by the **nominal U∞=1** the request actually specifies (arguably the more honest comparison, since Blasius is defined relative to the true undisturbed free stream, not the locally-contaminated one): δ* error −5.2% growing to **−20.0%**; θ error −11.7% growing to **−26.1%**.

  Both normalizations agree on the shape of the problem: modest-to-good agreement over most of the plate, a sharp, real degradation concentrated at the trailing edge.

- **Mechanism, cross-checked**: `0/U`'s `top` boundary flux (`review-work/4/script-3.py`, reading `1640/phi`) is now genuinely nonzero on all 200 top faces (sum 1.637×10⁻⁵ m³/s, versus exactly 0 on every face under the old `slip` BC) — `freestream` is doing something real. But the velocity right at the top boundary itself stays within 0.1% of U∞ everywhere (`review-work/4/script-14.py`), while the excess is concentrated at y=0.05 m, close to the plate. That is the classic signature of displacement-driven outer acceleration in a *finite-height* domain: the boundary layer's growing displacement thickness still has to be accommodated somehow, and a `freestream` top only partly relieves it — H=0.55 m is not tall enough, or the domain isn't long enough downstream, to make the residual effect negligible right where δ*/θ/Cf are read off.

**Why this matters relative to review-3's own test.** Review-3 proposed a specific, falsifiable criterion for whether the fix worked: *"if the edge velocity at y=0.05 across all five stations comes back to 1.000 ± 0.001 and the δ99/δ*/θ/Cf errors drop to low single digits, this confirms the diagnosis and resolves it."* That did not happen — edge velocity at the trailing edge is 1.011, an order of magnitude outside that band, and the trailing-edge errors are still 6–27% depending on quantity and normalization, not "low single digits." The fix is real and helped (leading-edge agreement improved substantially versus the old run's reported 6–13% deficit at x=0.2), but by review-3's own stated bar it did not resolve the problem — it shrank the region it affects.

**How to settle it.** Whichever of these is right, it's decidable without more guessing:
- Rerun with a taller domain (e.g., H≈1.0–1.5 m rather than 0.55 m) and/or a longer downstream buffer, and check whether the edge-velocity excess at x=1.0 drops below ~0.1–0.2%. If it does, this confirms domain size (not BC type) is the remaining lever, and the case should state that height explicitly rather than reusing 0.55 m under a different BC label.
- Alternatively, report the comparison honestly split by region: x≲0.7 as validated against Blasius to within a few percent, x≳0.8 flagged as confinement-limited and not fit for quantitative comparison as delivered.

---

## 2. Convergence — sound

**Severity: note.**

`log.simpleFoam` (`review-work/4/script-1.py`, `script-11.py`) shows a clean, monotonic residual decay of roughly 1.5–2 orders of magnitude per 200 iterations from iteration 1 to 1640, no stalling or oscillation. The solver's own message — `SIMPLE solution converged in 1640 iterations` — is corroborated by hand: at iteration 1600, Uy's initial residual (1.877×10⁻⁸) still exceeded the `U<1e-8` tolerance in `fvSolution`; by 1640 it had dropped to 9.32×10⁻⁹, and p's initial residual (2.59×10⁻⁸) was already well under its 1e-6 tolerance. This is a genuine convergence-controlled stop, well inside the 5000-iteration cap, not a premature or forced one.

## 3. Conservation — mass balance is essentially exact; a housekeeping defect (stale postprocessing data), not a conservation one

**Severity: note** on the balance itself; **minor** on the housekeeping issue.

Summing `1640/phi` over all six patches (`review-work/4/script-3.py`): inlet −5.500000×10⁻³, outlet +5.483631×10⁻³, top +1.637×10⁻⁵ (now genuinely nonzero, all 200 faces — confirms `freestream` is exchanging mass rather than acting as a lid), symmetry/plate/frontAndBack all exactly 0 by construction. Net imbalance −1.27×10⁻⁹ m³/s, a fractional error of **2.3×10⁻⁷** relative to the through-flow rate.

Separately: `postProcessing/*/1521/` (from the superseded `slip` run) was never removed before the rerun and now sits alongside the genuine final state at `1640/`. `Allrun` runs `blockMesh` and `simpleFoam` with no cleaning step in between reruns. This cost real effort to untangle in this review (the initial file listing surfaced `.../1521/` before the true final time) and could mislead a future reader who assumes the highest-numbered or first-listed postprocessing directory is authoritative. **How to settle it:** `Allclean` (present in the case but apparently not invoked between the two runs) followed by a clean `Allrun` would remove the ambiguity; barring a rerun, deleting the orphaned `.../1521/` directories and noting the correct final time (1640) in `spec.md` would fix it cheaply.

## 4. Conformance to spec.md — checked directly, passes

**Severity: note.**

`0/U`, `0/p` boundary types (`fixedValue`/`freestreamVelocity`/`symmetryPlane`/`noSlip`/`empty` for U; `zeroGradient`/`fixedValue`/`freestreamPressure`/`symmetryPlane`/`zeroGradient`/`empty` for p) match the current BC table in `spec.md` exactly, including the `freestream` revision. `constant/polyMesh/boundary` patch face counts (inlet 74, outlet 74, top 200, symmetry 50, plate 150) and `log.blockMesh`'s `nCells: 14800` match the 200×74×1 mesh spec.md describes; the mesh itself was not regenerated between runs, only the BC files changed, so review-3's independent mesh checks (first-cell height, grading) still apply and were not repeated here. `fvSolution`'s residual control (p<1e-6, U<1e-8) and relaxation (0.9, `consistent yes`) match spec.md's Numerics section.

The output-side fix from review-3 (finding 2 — the wall-shear line sample returning all zeros) also checked out: `system/controlDict` now uses a `plateWallShearStress` `surfaces`/`patch` function object instead of the old `wallShearStressGraph` line, and `postProcessing/plateWallShearStress/1640/plate.xy` contains 150 physically sensible nonzero values (e.g. −0.041 near the leading edge, decaying with the expected 1/√x trend up to x≈0.65 as shown in Finding 1). That specific defect is resolved.

## What remains unchecked

- **Mesh quality metrics** (non-orthogonality, skewness, aspect ratio): `checkMesh` is still not part of `Allrun` and was not run independently — same gap review-3 flagged, unchanged.
- **Upstream-buffer integrity** (x<0, symmetry-floored): not directly sampled; by construction a `symmetryPlane` cannot generate a wall boundary layer, so risk is low, but this remains an assertion rather than a measurement.
- **Full control-volume momentum balance** for this specific (freestream) run: review-3 established the methodology and closed it to 0.01% for the prior (`slip`) run; I did not repeat that exact calculation here because reconstructing `zeroGradient` outlet U from `constant/polyMesh/owner` added complexity beyond what the mass-balance result and the smooth, self-consistent Cf/edge-velocity/pressure trends already justify. The evidence gathered (exact mass closure, smooth monotonic residual decay, and a growing-Cf/growing-edge-velocity pattern that corroborates rather than contradicts itself across three independent quantities) is consistent with a converged, internally-consistent solution, but this specific check was not redone from scratch.
- **Comparison basis**: as in review-3, the Blasius f'(η) table used here is my own RK4 integration, cross-checked against a standard published compilation (Schlichting-derived values, matching to 5 significant figures) rather than a source fetched fresh today — flagged as indicative-but-verified, per the same caveat review-3 recorded.
