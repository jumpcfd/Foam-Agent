# Response to spec review round 2

This is the final spec-review round (rounds_left was 0 after this), so all three findings are
fixed directly rather than deferred.

## Finding 1: boundary-conditions table still listed the old top height — FIXED

Stale editing miss from the round-1 revision: the table row read `top (y = 0.15)` even though
every other part of the document had already moved to H = 0.55 m. Changed to
`top (y = 0.55)` so the document is internally consistent; no numerical content changed, since
0.55 m was already the height used everywhere else (§Geometry, §Mesh, §Assumptions).

## Finding 2: initial internal field never stated — FIXED

Added assumption 10: `0/U` initialized uniform to the free-stream value `(1 0 0)`, `0/p`
initialized uniform `0`, everywhere in the domain. Chosen because starting SIMPLE from the free
stream (rather than from rest) is closer to the converged state and shortens the iteration count
needed — relevant since it's also the value used for the `inlet` and `symmetry`-adjacent regions
already.

## Finding 3: off-by-one in cells-within-δ99 table — FIXED

Recomputed and corrected to 25 / 33 / 37 (from 26 / 34 / 38) at x = 0.1 / 0.5 / 1.0 m, matching
the reviewer's independent recount. Does not change the conclusion (the profile is still
resolved by >30 points near the trailing edge).
