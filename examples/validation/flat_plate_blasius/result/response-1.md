# Response to spec review round 1

## Finding 1: top boundary blockage contradicts "neither disturbs the layer" — FIXED

Agreed, and the reviewer's quantification (+3.76% edge-velocity acceleration at the trailing
edge under the original H = 0.15 m) is right — that's not negligible next to the effects being
measured. Raised the domain height to H = 0.55 m (from 0.15 m). Recomputed numerically
(not by hand, since the review also caught a hand-arithmetic slip — see Finding 2):

- Blockage ratio δ*/H now ≤1.0% everywhere on the plate (0.31% at x=0.1 m, rising to 0.99% at
  the trailing edge), down from 3.6% at the trailing edge before.
- Mesh cost stays trivial: y-direction cell count goes from 60 to 74 (same ≈10%/cell grading,
  same ≈0.048 mm first cell at the wall), total mesh 200×74×1 = 14,800 cells, up from 12,000.
  x-direction mesh and all buffer lengths are unchanged.
- Did not additionally switch the top patch to `freestream`: the reviewer offered it as an
  alternative/addable fix, but since raising H alone already brings blockage under 1%, adding a
  BC type this case doesn't otherwise need would be extra configuration risk (freestream needs
  matched `freestreamVelocity`/`freestreamPressure` sub-entries) for no established additional
  benefit. `slip` remains, consistent with the T3A reference tutorial this case's dictionaries
  are otherwise modelled on.

spec.md §Geometry and §Mesh are updated with the new height, grading, cell counts, and a
recomputed cells-within-δ99 table.

## Finding 2: off-by-one in the cells-within-δ99 table — FIXED

Agreed. The table was recomputed with a script (cumulative geometric-series height vs. Blasius
δ99(x), not hand arithmetic) and now reads 26 / 34 / 38 cells at x = 0.1 / 0.5 / 1.0 m for the
revised (H = 0.55 m, 74-cell) mesh. Also added the blockage-ratio column to the same table so
both review findings are visible together.

## Purpose/output scope (flagged as excess, not a defect)

Left as is — the reviewer noted this is a minor, expected byproduct of the velocity-field
sampling already needed for the boundary-layer-thickness comparison the request asked for, and
did not ask for a change.
