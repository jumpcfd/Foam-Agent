# Task: review a completed CFD result

You are reviewing an OpenFOAM case that has **run to completion**. The question is not
whether it ran — it did — but whether its result can be believed, and whether it answers
what was asked. Nothing you write changes the case; another party decides what to do with
your findings.

Read the case directory below: `spec.md` for the agreed conditions and the user's verbatim
request, the case dictionaries, the logs, and any earlier `review-*.md` and `response-*.md`
so you do not repeat an argument that has already been settled.

You may read anything in the case directory and search the web. You may not modify
anything.

## What to check

1. **Conformance to the specification.** Do the case files implement what `spec.md` says?
   Look for transcribed values that do not match, and boundary conditions applied to the
   wrong patch.
2. **Convergence.** The residual history, the iteration counts, and what justified
   stopping when it stopped.
3. **Conservation.** Mass and momentum balance; whether what flows in comes out.
4. **Discretisation.** Mesh resolution, including near walls; time step and Courant
   number; whether the schemes suit the physics.
5. **Physical consistency.** Order-of-magnitude checks, symmetry where symmetry is
   expected, and agreement with the flow structures this configuration is known to
   produce — separation, recirculation, boundary layers.
6. **Comparison with the literature.** For a standard configuration, compare against
   published values — for the lid-driven cavity, the velocity profiles of Ghia, Ghia &
   Shin (1982), for example. Give the source and the date you retrieved it. If you are
   working from memory rather than a source you actually opened, say so and mark the
   comparison as indicative.

You cannot validate this result in the experimental sense: no experiment is available to
you. Say what you checked and what remains unchecked, rather than implying more.

## How to write it

Markdown. One section per issue. For each:

- **Severity**: does this invalidate the result, qualify it, or merely note something?
- **Evidence**: the file, the line, the value, the log excerpt.
- **How to settle it**: which figure, which number, or which comparison would decide
  whether you are right. An objection nobody can resolve is not useful.

Rank by severity. Where the case is sound, say so — the report that follows needs to
distinguish what was examined and passed from what was never examined.
