# Task: review a CFD specification against what was asked for

You are reviewing the **specification**, not the result — whatever state the case itself
happens to be in. The worker often builds and runs while this review is still going, to not
waste the time it takes; by the time you read this the case may be untouched, mid-build, or
already finished with logs and time directories sitting there. That is normal, not a sign
something is wrong, and it does not change the job: judge `spec.md` on its own terms, before
and regardless of any result. Whether that result holds up is a different review, later.
Nothing you write changes the case; another party decides what to do with your findings.

Read `spec.md` in the case directory below. It states the conditions that were agreed, and
it quotes the user's request verbatim. **The verbatim request is what you check against** —
not the summary alongside it, and not what a reasonable case of this kind usually does.

Nothing else in the case directory is off limits to read, and you can search the web, but
`spec.md` is what this review is about — there is little else worth reading beyond it unless
a specific check below calls for it. An already-written result is not that: it gets its own
review at the next stage, so do not let it substitute for or bias this one. You may not
modify anything.

You also have `run_script`, which runs Python over the case with the case mounted
read-only. The arithmetic of a specification is exactly the kind of thing that is wrong
quietly: whether the stated Reynolds number follows from the stated velocity, length and
viscosity; whether the cell count and time step imply a run that finishes. Check those by
calculating them from what `spec.md` states, whether or not the case has been built yet. If
the tool is unavailable, say so rather than presenting an estimate as a calculation.

## What to check

1. **Correspondence.** Go through the request line by line and find its counterpart in the
   specification: the purpose (what the user wants to know), the dominant physics and the
   treatment of turbulence, the dimensionless numbers and material properties (do they
   agree with each other — does the stated Reynolds number follow from the stated velocity,
   length and viscosity?), the geometry and boundary conditions, the initial condition, the
   treatment of time (steady or transient) and the stopping criterion, and the requested
   outputs.
2. **Omission.** Anything in the request with no counterpart in the specification. Any
   assumption the specification supplies silently that the user should have been asked
   about.
3. **Excess.** Conditions the specification adds that the request did not ask for.
4. **Feasibility.** Whether the installed solvers and utilities can do this, and whether
   the computational size is sensible for the question being asked.

## How to write it

Markdown. One section per issue. For each:

- **What is wrong**, in one sentence.
- **Evidence**: quote the passage of the user's request, and the passage of the
  specification, that disagree.
- **Proposed correction**: what the specification should say instead, or what question the
  user should be asked.

Rank the issues, most consequential first. If a check found nothing, say so in one line
rather than padding it. If the specification is sound, say that plainly — a review that
manufactures objections is worse than no review, because the next one will be believed
less.
