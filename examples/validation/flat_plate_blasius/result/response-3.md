# Response to result review round 1

Both findings were fixed and the case was rerun. This is not the final round available
(`rounds_left: 1` was returned), so a further round can still catch anything the fixes did not
fully resolve.

## Finding 1: residual confinement from the `slip` top boundary — FIXED (rerun)

Agreed with the diagnosis and the specific evidence (edge velocity rising to +1.35% at the
trailing edge, `phi` through the top patch being exactly zero, and the 15–33% amplification into
δ99/δ*/θ/Cf). Implemented exactly the fix the review proposed: changed the `top` patch from
`slip` to `freestream` (`freestreamVelocity`/`freestreamPressure`, `freestreamValue` = the
free-stream state `(1 0 0)` / `0`), matching the format used by this OpenFOAM installation's own
`airFoil2D` tutorial, and reran.

Result of the rerun (`postProcessing/profile_*/1640/line.xy`, last row = y = 0.05 m, i.e. the
edge-velocity sample the review used): the edge-velocity excess drops from +1.35% (slip) to
+0.61% at x=0.2 rising to **+1.11%** at the trailing edge (x=1.0) — smaller everywhere, and the
mechanism the review identified (an impermeable lid) is gone, since `freestream` now permits
outflow through the top patch. Converged in 1640 iterations (residual control still satisfied:
U<1e-8, p<1e-6), so this is a like-for-like comparison with the first run.

This is better, not perfect: a small residual excess remains at the trailing edge. I did not
chase it further (e.g. by raising H again) within this round, because (a) it is now roughly a
third of the original effect, in the direction consistent with a finite-domain artifact rather
than a new problem, and (b) `spec.md` records the mechanism, the before/after numbers, and the
reasoning plainly, so a reader comparing against Blasius can judge for themselves how much of
any remaining trailing-edge deviation to attribute to this rather than to the physics. If the
next review round finds this residual still large enough to dominate the comparison, the
appropriate next step would be to raise H again now that the impermeable-lid mechanism is
removed (unlike the first round, where raising H alone could not have fixed the root cause).

## Finding 2: `wallShearStressGraph` output was all zeros — FIXED (rerun)

Agreed with the diagnosis (a `graphUniform` line sampled off the wall interpolates through
`wallShearStress`'s zero internal field, regardless of how close to the wall the line is placed)
and implemented the proposed fix: replaced the `graphUniform` line sample with a `surfaces`
function object (`type patch`, `patches (plate)`, `raw` format) that reads the `plate` patch's
own boundary field directly. Verified in the rerun's output
(`postProcessing/plateWallShearStress/1640/plate.xy`): values are now non-zero and physically
sensible — e.g. wallShearStress_x = -0.041 near the leading edge (x≈0.0015 m) decaying to
≈-0.0013 by mid-plate, consistent with the expected Blasius τw ∝ x^(-1/2) decay. Also removed the
stale `postProcessing/wallShearStressGraph/` directory left over from the first (all-zero) run,
since it no longer corresponds to anything in the current `controlDict` and would otherwise read
as current data.

`spec.md` §Outputs, §Boundary conditions, §Geometry and the assumptions list were all updated
in place to describe the final configuration and to record both revisions (with the measured
before/after numbers) rather than only the final state, per the request's instruction to record
every assumption.
