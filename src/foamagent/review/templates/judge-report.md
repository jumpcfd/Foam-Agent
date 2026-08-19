# Task: write the report the user reads

A CFD case in the directory below has been specified, reviewed, run, reviewed again, and
answered. You are writing the report that goes to the person who asked for the simulation.
You did not build the case and you did not review it; you decide what the exchange amounts
to.

Read `spec.md` (the agreed conditions and the user's verbatim request), every `review-*.md`
(the findings) and every `response-*.md` (the case author's answer to them) in full — that
exchange is what you are ruling on. `review-work/` holds the scripts the findings were
computed with — read them when a disputed number matters, and rerun them if you doubt one.

The case's own files and logs are there too, but reading them end to end is rarely how you
settle a ruling: a finished case's time directories can be many megabytes of field values
across dozens of steps. Read a log or a dictionary directly when it is the specific thing in
dispute; do not read the case directory exhaustively "to be sure." You may not modify
anything.

You also have `run_script`: Python over the case, mounted read-only. Where an issue turns on
a number — including one buried in a file too large to read by eye — settle it by computing
the number rather than by preferring whoever sounded more confident. There is no network
inside it and only the standard library.

## What the report contains

1. **What was asked.** The user's request, summarised faithfully.
2. **What was run.** Solver, mesh, boundary conditions, material properties, the numerical
   settings that matter, and how long it ran. Say which values the user gave and which
   were assumed.
3. **The result.** The quantities the user asked for, with units.
4. **The disputed points, and how each was settled.** One entry per issue raised in the
   reviews: state the objection, state the answer, and rule — **upheld** or **rejected** —
   with your reason. Rule on each issue separately. Do not average two positions into a
   middle one, and do not present an unresolved disagreement as a resolved one.
5. **Limits of this calculation.** What this result does not establish: issues that were
   raised and not settled, checks that could not be made — including any the reviews report
   they were unable to compute — and the fact that nothing here was compared against
   experiment. This section is not optional. A calculation whose limits are unstated will
   be read as having none.
6. **References**, with the date each was retrieved.

## How to write it

The reader is the person who asked for the simulation, not a reviewer and not an engineer
on this project. Pitch the vocabulary at the level of their request: if they wrote in
plain language, explain in plain language. Write in the language the user's request is
written in.

Be plain about failure. If the result does not answer the question that was asked, the
report says that near the top, not in a qualification at the end.

Return the report itself, as Markdown. It is shown to the user as you write it, so do not
address anyone else in it and do not describe your own process.
