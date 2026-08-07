<!-- foamagent: result review, document 3 -->

# Result review 3

## Review: flat-plate Blasius validation — completed run

This is the first result-review round. `spec.md` was revised twice during spec review (raising the domain height from 0.15 m to 0.55 m specifically to bring the top-boundary blockage under 1%) — that history is not re-litigated here. This review checks whether the run that actually completed answers the request.

Overall conclusion: the case ran cleanly, converged properly, and conserves mass and momentum to machine-adjacent precision. But the effect the earlier spec review flagged and only partially fixed — the confined domain accelerating the outer flow — survived the fix in a form large enough to be the **dominant** source of disagreement with Blasius by the trailing edge, exactly the outcome review-1 warned about. A separate, unrelated defect makes the delivered skin-friction output unusable as written, though the underlying data needed to fix it is present.

---

### 1. Residual confinement effect grows along the plate and dominates the trailing-edge comparison

**Severity: qualifies the result — invalidates the trailing-edge portion of the Blasius comparison specifically, while the near-leading-edge portion remains reasonable.**

**Evidence.** Four independent calculations, all pointing the same way and none dependent on the others:

- **Edge velocity.** The last sample of each U(y) profile (y = 0.05 m, well outside any δ99) is not 1.0 m/s: it rises monotonically from **1.007 at x=0.2** to **1.0135 at x=1.0** (`review-work/3/script-5.py`). The outer flow is being accelerated, and increasingly so downstream.
- **Boundary-layer thickness.** Interpolating the profiles against a Blasius solution I solved myself (RK4 shooting on f'''+0.5 f f''=0, converged f''(0)=0.332057, matching the published constant to 6 figures — `script-3.py`) gives, at x=1.0: δ99 = 13.07 mm (CFD) vs 15.53–15.81 mm (Blasius), **−16%**; δ* = 4.19–4.24 mm vs 5.44 mm, **−22 to −23%**; θ = 1.40–1.45 mm vs 2.10 mm, **−31 to −33%** (`script-4.py`, `script-7.py` — the latter re-integrates with a tighter cutoff of 3×δ99 to rule out the deficit being an artifact of integrating too far into the outer flow; the deficit survives, just smaller: δ* −22%, θ −31% at x=1.0). Even at x=0.2 the deficit is already 6–13%, not negligible.
- **Skin friction, from the raw field (bypassing the broken graph — see finding 2).** Reconstructing the 150 plate face-center x-positions from the blockMeshDict grading and reading `1521/wallShearStress`'s plate boundary values directly gives Cf ≈ 24–28% **above** Blasius' 0.664/√Re_x over the back third of the plate (`script-6.py`), consistent in sign and magnitude with an accelerating (favourable-gradient) outer flow.
- **This is not a conservation or discretisation error.** A control-volume streamwise momentum balance (inlet/outlet momentum flux + pressure force, built from `1521/U`, `1521/p`, `1521/phi`, with outlet's zeroGradient U resolved via `constant/polyMesh/owner`) closes against the direct wall-shear integral to **0.01%** (`script-9.py`). The solver's converged state is internally momentum-consistent; the discrepancy with Blasius is a genuine feature of the flow the case set up, not solver error.

**Why this happened despite the spec-review fix.** `spec.md`'s own blockage table put δ*/H at ≤0.99% at the trailing edge with H=0.55 m, and the response to review-1 judged that "small enough not to be the dominant source of disagreement." The measured 1.35% edge-velocity excess is in the same ballpark as that estimate, but it does not translate linearly into the compared quantities — δ*, θ and Cf are all differences/gradients relative to a nominal U∞=1 that the local flow no longer matches, so a ~1% velocity perturbation is amplified into a 15–30% error in exactly the numbers the case exists to produce. Review-1's original objection (`review-1.md` finding 1) — raise H, or use `freestream` instead of `slip` on top — was answered only with "raise H"; the response explicitly declined `freestream` "since raising H alone already brings blockage under 1%." That reasoning is now shown empirically wrong: `slip` is an impermeable lid (confirmed by `1521/phi`'s top-patch flux being exactly zero for every one of 200 faces), so the confinement pressure field is still fully present regardless of H, and 1% of confinement still contaminates the comparison at the level that matters.

**How to settle it.** The result stands for early-plate comparisons (x≲0.2, where deviations are still ~5-15%) but should not be presented as validating Blasius near the trailing edge without qualification. The deciding fix is to switch the top patch to `freestream`/`freestreamVelocity`/`freestreamPressure` (letting the boundary entrain/discharge rather than acting as a rigid lid) and rerun; if the edge velocity at y=0.05 across all five stations comes back to 1.000 ± 0.001 and the δ99/δ*/θ/Cf errors drop to low single digits, this confirms the diagnosis and resolves it. A cheaper diagnostic without rerunning: sample p(x) along y=0.05 or the top patch — if it falls with x (favourable gradient) that corroborates the mechanism further, though the evidence above is already conclusive on its own.

---

### 2. The delivered skin-friction postprocessing output is all zeros

**Severity: qualifies the result — a genuine defect in what was delivered, though the underlying data is intact and I was able to recover it.**

**Evidence.** `system/controlDict`'s `wallShearStressGraph` (line 51) samples `wallShearStress` along a line at `y=0.0001`, i.e. inside the domain, not on the wall patch itself. But `wallShearStress`'s `internalField` is `uniform (0 0 0)` — only the `plate` patch's **boundary** field is populated (150 nonzero, physically sensible values, e.g. −0.041 near the leading edge decaying toward −0.0013 mid-plate, consistent with the expected 1/√x singular decay). `graphUniform` interpolates from cell/internal values, so every one of the 200 sampled stations in `postProcessing/wallShearStressGraph/1521/line.xy` — and at every earlier write time back to t=0 — reads exactly `0 0 0`. The spec explicitly promised this output "for skin-friction comparison against the Blasius Cf(x)"; as delivered it is unusable.

**How to settle it.** Check `postProcessing/wallShearStressGraph/*/line.xy` directly — every value is 0, which is definitive; no ambiguity here. The fix is to sample the wall patch's own face values (e.g. a `surfaceFieldValue`/patch-based sampling, or `sampledSurfaces` restricted to the `plate` patch, or simply post-extract the boundary field as I did in `script-6.py`) rather than an interior `graphUniform` line offset from the wall.

---

### 3. Convergence — sound, no issues

**Severity: note.**

Converged in 1521 of the 5000-iteration cap (`log.simpleFoam:12237`), well short of the cap. Residual history sampled at t=1, 200, 400, 600, 800, 1000, 1200, 1400, 1500, 1521 shows smooth, monotonic decay of roughly two orders of magnitude per 200 iterations with no stalling or oscillation. Final initial residuals (Ux ≈ 1.3×10⁻⁹, Uy ≈ 1.0×10⁻⁸, p ≈ 2.0×10⁻⁸) satisfy the `residualControl` thresholds (U<1e-8, p<1e-6) that triggered the stop — this was a genuine convergence-controlled stop, not a premature or forced one.

---

### 4. Mass conservation — exact, no issues

**Severity: note.**

Summing `phi` over all six patches at the converged state (`script-2.py`): inlet −5.500000×10⁻³, outlet +5.499999×10⁻³, top/symmetry/plate/frontAndBack all exactly 0 by construction (slip is impermeable, symmetry and empty patches have zero normal flux, the wall is no-slip). Net imbalance −1.44×10⁻⁹ m³/s, a fractional error of 2.6×10⁻⁷ relative to the through-flow rate — as good as this arithmetic gets.

---

### 5. Conformance to spec.md — checked directly, passes

**Severity: note.**

Checked the case files (not just re-read the prior spec review's claims): `constant/polyMesh/boundary` patch face counts (inlet 74, outlet 74, top 200, symmetry 50, plate 150) match the mesh block layout in `system/blockMeshDict`; `log.blockMesh` confirms first-cell height 4.7614×10⁻⁵ m and total mesh 200×74×1 = 14,800 cells, matching the revised (H=0.55 m) spec; `0/U`, `0/p`, `constant/momentumTransport` (`simulationType laminar`), `constant/physicalProperties` (`nu 1e-5`) all match spec.md verbatim; x-direction grading in `blockMeshDict` (finer toward the leading and trailing edges in each of the three blocks) matches the stated rationale. No transcription errors or misapplied boundary conditions found.

---

### What remains unchecked

- **Mesh quality metrics** (non-orthogonality, skewness, aspect ratio) were never computed — `checkMesh` was not run as part of `Allrun`, and I did not reconstruct it. Unlikely to be an issue for a graded structured hex mesh, but it is genuinely unverified rather than passed.
- **Upstream-buffer integrity** (that the symmetry-floored region ahead of x=0 stays fully undisturbed, i.e. no premature boundary layer) was not directly sampled — no profile exists there since the spec only requested profiles on the plate. Indirect evidence (clean inlet flux, uniform inlet U) is consistent with no problem, but I did not sample the actual field there.
- **Comparison basis**: the Blasius f'(η) values I compared against were computed by my own RK4 shooting integration of the standard similarity ODE, cross-checked against a partial published table (f''(0)=0.33206, f'(0.2)=0.06641, f'(1.0)=0.32978, f'(3.0)=0.84604, f'(5.0)=0.99154) retrieved via web search on 2026-08-07 citing a standard "Blasius Laminar Solution Table" compilation — my own integration matched it to 5 significant figures, so this is a first-principles calculation cross-validated against literature, not a value taken from memory.
