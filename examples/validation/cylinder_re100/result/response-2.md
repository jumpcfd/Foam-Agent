# Response to review-2.md

## Finding 1 (Medium): Aref was a formula, not a number

Agreed, and fixed. spec.md now states the literal z-extent (z from −0.05 m to 0.05 m,
thickness 0.1 m) in the Geometry section, and the Outputs section states `Aref = 0.1`
literally. `blockMeshDict` and `system/forceCoeffs` will be built to match these numbers
exactly (D = 1 m × 0.1 m thickness = 0.1 m²).

## Note: symmetry-breaking box overlaps the cylinder for x ≲ 0.5D

Correct, and as the review notes this has no functional effect since `setFields` only
acts on existing (fluid) cells — the solid cylinder region is simply skipped. Added a
clarifying paragraph to spec.md so the box's extent is described accurately rather than
implying it starts entirely clear of the cylinder.

This was the second and final review round for the spec stage; proceeding to build the
case.
