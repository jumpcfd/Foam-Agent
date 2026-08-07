# Response to review-3.md

## Finding 1 (Qualifies the result): Numerics section doesn't describe the run that actually
happened (Courant number, adaptive time step)

Confirmed as reported: `system/controlDict` sets `maxCo 2;`, not the `maxCo 1` that
spec.md's Numerics section describes, and the run spent 99.3% of its timesteps pinned at
the `maxDeltaT` ceiling of 0.02 s rather than being actively limited by a Courant
condition. This is a genuine discrepancy between the documented methodology and the
executed one, and spec.md's Numerics section is corrected below to describe the run that
actually happened rather than the one that was planned.

**This was not re-run at a smaller time step in this session.** The review's suggested
check — halve `maxDeltaT` to 0.01 s (or set `maxCo 1` for real) and compare `Cd_mean`/`St`
— was not performed. No new solve was carried out; no dictionary or result file was
touched. The Δt-sensitivity question the review raises is therefore still open: I have not
established that a Co≤1 run gives the same `Cd_mean`/`St` to within the reporting
precision, only that this run, at Co≈2, produced clean, converged forces (see below). It
would be dishonest to describe this as settled.

What *is* the honest basis for treating `Cd_mean = 1.3799` and `St = 0.1687` as usable
despite that open question is exactly the mitigating evidence the review itself already
supplied, not a resolution of the sensitivity question:

- The shedding period (5.93 s) is resolved by ~296 timesteps at the actual Δt = 0.02 s, so
  the large-scale unsteady motion the two reported numbers are derived from is
  well-sampled regardless of what the local near-wall Courant number is doing.
- Within a single timestep, PIMPLE's outer-corrector loop converges hard (`Ux`/`Uy`
  residuals ~1e-3 → ~1e-7, `p` ~1e-2 → ~1e-6 over 5 correctors, confirmed at
  `Time = 100.02s` in `log.pimpleFoam`), so under-iteration within a step is not
  contributing error — only the step size itself is untested.
- The reported figures are insensitive to exactly which whole-cycle averaging window is
  used (±2 cycles, 5–11 cycle lengths, changes `Cd_mean` by ≤0.0002 and `St` by ≤0.00001,
  per review-3's own recomputation) — this bounds sampling/window-choice noise, but it says
  nothing about whether a smaller Δt would shift the mean itself.

Put plainly: the shedding is well-resolved and each step is tightly converged, which is
why the reported numbers are a reasonable, usable estimate — but whether they would move
outside their last reported digit under `maxCo 1` is a question this run cannot answer,
because it never ran that way. spec.md's Numerics section is corrected to state
`maxCo 2` / a step effectively pinned at 0.02 s as what was actually run, and to flag the
Δt-sensitivity question as open rather than implying it was checked.

## Finding 2 (Notes): spec.md's stated convergence timestamps didn't match the data

`spec.md` had already been corrected before this response was written — the "Averaging
interval used" section now states the period first reaches its converged value (5.927 s)
at the zero-crossing **t = 97.18 s** (not 91.25 s), with the preceding cycle at t = 91.25 s
correctly described as one significant figure short (5.928 s), and the `Cl` peak amplitude
reaches its converged value (0.3112) at the peak **t = 110.52 s** (not ~92.7 s), with the
preceding peak at t = 92.74 s correctly described as one significant figure short
(0.3108). These now match review-3's independent recomputation from the raw
`forceCoeffs.dat` data exactly. No other numbers in spec.md changed: the settled point
(t ≈ 115 s), the six-cycle averaging window (t = 114.9627–150.5241 s), and the reported
`Cd_mean = 1.3799` / `St = 0.1687` were already correct and are untouched by this
correction — as review-3 itself notes, this was a documentation-accuracy issue in the
narrative timestamps, not an error in the numbers that were actually computed and
reported.

## Disposition

No case files, dictionaries, or results were changed. `spec.md`'s narrative was already
corrected for Finding 2 prior to this response (verified above). Finding 1 remains an open
methodological caveat on the reported numbers, not a resolved one: `Cd_mean = 1.3799` and
`St = 0.1687` are reported as-is, on the basis of well-resolved shedding and tight
per-step convergence, with the Co≈2-vs-Co≤1 sensitivity explicitly flagged as untested
rather than settled.
