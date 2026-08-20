---
name: openfoam-cfd
description: Use when the user asks for a CFD simulation in OpenFOAM — setting up a case, running a solver, diagnosing why one failed, or post-processing a result. Drives the Foam-Agent MCP server, which provides the OpenFOAM installation, its tutorials, and an independent review of the result.
---

# OpenFOAM through Foam-Agent

You are the one doing the CFD. Foam-Agent's tools measure this machine, check a case before
it runs, render a picture of a finished one, and put the work through review. Running the
case, reading the logs, and everything else -- solver choice, dictionary contents, what to
change after a failure -- are yours, with your own tools.

The shape of a job:

```
agree the conditions with the user  →  spec.md
request_review (stage="spec")       →  review_status until done → findings; fix them;
                                       write response-<n>.md
build the case, run it, fix failures until it completes
request_review (stage="result")     →  review_status until done → findings; fix them;
                                       write response-<n>.md
request_report                      →  report_status until done → show the user what
                                       it returns, unchanged, and tell them where the
                                       case directory is
```

`request_review` and `request_report` return at once with an id; a review can take tens of
minutes, so poll `review_status`/`report_status` (with `wait_seconds`, a few minutes at a
time) until `state` is `"done"`.

## First, look

Call `describe_environment`. It answers three questions you would otherwise guess at:

1. **Which OpenFOAM is here** — fork (foundation or esi) and version. Their dictionary
   names differ (`physicalProperties` vs `transportProperties`,
   `momentumTransport` vs `turbulenceProperties`), so this decides the syntax you write.
2. **Which solvers exist** — the real contents of `$FOAM_APPBIN`. Never name one that is
   not in that list.
3. **Where the tutorial catalogue is** — `library.catalog`, if one has been built.

If `library` is empty, tell the user to run `foamagent index build` once. Everything below
is much weaker without it.

## Work from a tutorial, not from memory

`catalog.md` is a table of every tutorial this installation ships: case, solver, domain,
category, and the directory holding it. It is around 35 kB — read all of it.

Pick the case closest to what is being asked for and read its files. They are a working,
version-correct answer, which beats recalling OpenFOAM syntax from training data. Prefer
matching on **physics first, geometry second**: a lid-driven cavity is a better starting
point for any laminar incompressible box than a differently shaped case with the wrong
solver.

`by-solver.md` inverts the table when the solver is already decided.
`commands/<name>.txt` holds each application's `-help` output.

## Classify before you write

Fix these five before touching a file, because together they determine the solver, the
field set and the dictionaries:

| Question | Consequence |
|---|---|
| Steady or transient? | `simpleFoam` family vs `pimpleFoam`/`icoFoam` family; `controlDict` timing |
| Compressible? | `p` in m²/s² vs `p` in Pa; which thermophysical dictionary is needed |
| How many phases? | single-phase vs `interFoam` and an `alpha` field |
| Laminar or turbulent? | whether `k`/`epsilon`/`omega`/`nut` exist at all |
| Heat or buoyancy? | `p` vs `p_rgh`; whether an energy equation is solved |

## Write spec.md before you write a case

Once the conditions are agreed, record them in `spec.md` in the case directory. It has two
parts, and the first one is not optional:

1. **The request, verbatim.** Quote what the user actually wrote, word for word, in a
   blockquote. Not your summary of it — the words they used. Everything downstream is
   checked against this quotation, so a tidied-up paraphrase quietly removes the thing
   being checked. If the requirement arrived across several messages, quote each one.
2. **The conditions.** Purpose (what the user wants to know), physics and turbulence
   treatment, geometry, boundary and initial conditions, material properties and the
   dimensionless numbers they imply, steady or transient and the stopping criterion, and
   the outputs asked for. State plainly which values the user gave and which you assumed.

Then call `request_review` with `stage="spec"`, before building anything. It returns at
once; poll `review_status` (with `wait_seconds`) until it reports `state="done"` and read
`review` for the findings on whether the specification answers the question that was asked.
Work through them: fix what is wrong, ask the user where the answer is theirs to give, and
write your answer to every point into the file the tool names (`respond_to`,
`response-<n>.md`). Say what you changed, or why the point does not hold. That file is read
later when the report is written, and a finding with no answer beside it reads as one you
had nothing to say to.

Two rounds. After that the tool returns a closing note and you carry on.

## Offer a completion guarantee before building

Most users run this interactively. Once the conditions in `spec.md` are agreed, state
plainly what a finished result must show — including anything a self-report cannot stand in
for on its own (a claimed convergence study whose directories turn out empty is the kind of
mistake this line exists to catch). Then say:

    If this looks right, run `/goal <the criteria just stated>` to have this session hold
    itself open, refusing to declare completion, until they are met.

`/goal` is a CLI feature, not a tool this skill calls — only the user typing it turns it on,
so ask rather than assume. A session run without it is not wrong, just unsupervised.

## Then build it

1. **Mesh** — `blockMeshDict` for block geometry, `snappyHexMeshDict` for imported
   surfaces. The tutorial you picked has a working one.
2. **Fields** in `0/` — one file per field the solver needs, and every patch in the mesh
   named in every field's `boundaryField`.
3. **Properties** in `constant/` — transport, turbulence, thermophysical as applicable.
4. **Numerics** in `system/` — `controlDict`, `fvSchemes`, `fvSolution`. Start
   conservative (upwind, small time step, tight relaxation); loosen once it runs.
5. **`Allrun`** — the sequence of commands, mirroring the tutorial's own.

Write files with your own tools.

## Check, run, read

`validate_case` first -- it costs milliseconds, and a mistake it would have caught costs
minutes of solver time instead. Then run `Allrun` yourself, with your own shell tool (in the
background if it supports that: a solve can take a long time, and nothing here runs it for
you). Watch the log as it goes rather than waiting blind.

**Finish the run you started.** A turn that ends before the solver does leaves a case
nobody has looked at and a log cut off wherever it had got to. This matters most when there
is no user to notice: a session run non-interactively has nobody to say "and how did it
go?".

**Show convergence, don't just claim it.** "Ran until it converged" is a claim a log can
support or contradict; make sure one can. A steady run's residual history in `log.<solver>`
already does this. A statistic that must stop changing in time instead of a residual doing
so — a running mean, a friction velocity, a bulk quantity — needs its own monitor set up
before the run (a `probes` or `fieldAverage` functionObject writing to `postProcessing/`),
not one reconstructed from memory afterward. When `spec.md` or the report states the run
converged, point at that trend rather than asserting it.

## What to ask the user

Ask before generating, not after failing, when the requirement leaves out something that
changes the answer: fluid properties (viscosity, density), inlet and outlet conditions,
whether the flow is turbulent, the domain size, or the physical duration. A CFD case with
invented numbers looks exactly like one with correct numbers, which is what makes guessing
here worse than asking.

This holds even when a defensible number exists. "Re=100 is the textbook cavity case" is a
guess about which case was wanted, not a fact about this one, and running it spends minutes
of solver time on a question one sentence would have settled. Ask, and end the turn there:
a reply that is only a question is a finished piece of work. Announcing the assumption
afterwards does not substitute for asking first.

## Offer a validation comparison, but don't block on it

Verification — does this run converge, is it mesh-independent, is it numerically sound — is
something this skill can always do on its own. Validation — does the result match reality —
needs an independent reference value it cannot invent. Once the physics is settled and
before building, ask once: "If you have an experimental or DNS reference for this flow,
share it now and I'll compare against it; if not, I'll verify what I can and say plainly
that the result hasn't been checked against independent data."

Unlike the questions in the previous section, this one does not block building — proceed
either way once asked. Record the answer in `spec.md`: either the reference value and its
source, or the fact that none was offered. If none was given, say so in as many words when
`request_report` asks what the calculation does not establish — a converged, mesh-independent
run is not the same claim as an accurate one, and the report should not blur the two.

## Guardrails

These are the mistakes that recur. They are cheap to avoid and expensive to debug.

- **Do not invent dictionary keys, patch types or solver names.** Every one comes from a
  closed vocabulary. Check the tutorial you are working from, or `commands/<name>.txt`.
- **Do not mix turbulence fields.** k-ε needs `k`, `epsilon`, `nut`; k-ω SST needs `k`,
  `omega`, `nut`; Spalart-Allmaras needs `nuTilda`, `nut`. A mismatched set aborts at
  startup.
- **Do not use `p` where the solver wants `p_rgh`.** Buoyant and VOF solvers use `p_rgh`;
  pure incompressible solvers use `p`.
- **Do not put central differencing on a VOF `alpha` field.** It is unbounded; use
  `vanLeer` or the interface-compression family.
- **Do not assume `0/` exists.** Many tutorials ship `0.orig/` and copy it in `Allrun`.
- **Do not run more MPI ranks than `numberOfSubdomains` in `decomposeParDict`.**
- **Do not treat `checkMesh` warnings as noise when the run is diverging.** Most early
  divergence is mesh quality.
- **Do not raise the time step to finish faster.** Watch the Courant number instead.

## When it fails

Work from the first error, not the last. Read the log yourself rather than summarising the
last few lines -- these are the signatures worth recognising on sight:

| Signature | What it means | Usual fix |
|---|---|---|
| `keyword <x> is undefined in dictionary <y>` | A dictionary lacks an entry the solver reads | Add it; the message names both |
| `Cannot find file "points" in directory "polyMesh"` | No `constant/polyMesh/points` | The mesher never ran, or ran into an error of its own |
| A patch named in a field file or the mesh, but not both | Field files and mesh disagree on patch names | `validate_case` prints both lists |
| `boundary face ... already belongs to some other patch` | A face is in two patches in `blockMeshDict` | Remove it from one |
| `Unknown <x> type <y>` | A type name this build does not have | The message lists the valid ones |
| A residual or handler actually firing: `Foam::sigFpe::sigHandler`, `Floating point exception (core dumped)`, `solution diverged`, or a `nan`/`inf` residual | The solution blew up | Reduce the time step or relaxation, or start from upwind schemes |
| A `dimensions` mismatch between two fields | Incompatible units | Check the `dimensions` line of the fields named |

Every OpenFOAM log opens with `sigFpe : Enabling floating point exception trapping
(FOAM_SIGFPE).` -- that line by itself is not divergence, only the handler actually firing
(a stack trace, `core dumped`, or a NaN/inf in a residual) is. Treating the startup banner
as a crash is the single most common misdiagnosis here.

After a fix, rerun from the failing step rather than from scratch when the mesh is
unchanged.

A case that keeps failing is yours to fix. The result review below is for a run that
finished: it asks whether the answer can be believed, which is not a question a crashed
case poses yet.

## When it has run

Call `request_review` with `stage="result"`, then poll `review_status` until it reports
`state="done"`. `review` then holds findings on conformance to `spec.md`, convergence,
conservation, discretisation, physical plausibility and comparison with published values.

Handle them the same way as before: fix what is wrong — rerun if a fix changes the answer —
and write `response-<n>.md` for every round, saying what you changed or why the point does
not hold. Two rounds here as well.

## Reporting back

Call `request_report`, then poll `report_status` until it reports `state="done"`. `report`
then holds the report for the user: what was asked, what was run, the result, a ruling on
each disputed point, what the calculation does not establish, and the references used.

**Show it to the user unchanged.** Do not summarise it, do not drop the section on limits,
and do not soften a conclusion you would have phrased more gently. If you disagree with
something in it, say so in your own words *after* presenting it, and let the user see both.

**Say where the case is.** Give the absolute path of the case directory with the report,
and say that the OpenFOAM case, the solver logs, the time directories and the review
documents are all inside it. The report says what the answer is and never says where the
files are, and that path is what the user needs to do anything further with the result —
open it in ParaView, rerun it by hand, hand it to someone else. Do not make them ask.

If `review_status` or `report_status` reports `available=false` — the review is unavailable
because no review command is configured on this machine — say so to the user in as many
words: the case has had no independent check, and that changes how much the result is
worth. Do not quietly present your own account of the run as though it had been through one.

---

The classification checklist, the guardrail list and the failure table follow the structure
of `svd-ai-lab/sim-plugin-openfoam` (Apache-2.0), whose OpenFOAM skill is the closest prior
art for this shape of document. Its knowledge targets ESI OpenFOAM; the environment- and
version-specific answers here come from `describe_environment` and the built catalogue
instead.
