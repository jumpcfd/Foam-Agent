---
name: openfoam-cfd
description: Use when the user asks for a CFD simulation in OpenFOAM — setting up a case, running a solver, diagnosing why one failed, or post-processing a result. Drives the Foam-Agent MCP server, which provides the OpenFOAM installation, its tutorials, and an independent review of the result.
version: 3.6.1
---

# OpenFOAM through Foam-Agent

You are the one doing the CFD. Foam-Agent's tools measure this machine, check a case before
it runs, render a picture of a finished one, and put the work through review. Running the
case, reading the logs, and everything else -- solver choice, dictionary contents, what to
change after a failure -- are yours, with your own tools.

This document has four parts: how the work is tracked across a whole project, the loop one
job goes through, and then two chapters of detail -- looking before building, and building
and running a case -- for the parts of that loop this skill actually drives.

## The project is a git repository, and the work is tasks

A real job is more than one case: research, several cases, a report that merges them, a
change of plan halfway. That is tracked as tasks in the project's git repository, and a
task is done only by the commit `task_done` makes. This is how the user sees where things
stand without holding it all in their head, so it is not optional.

- **Start the harness in the project directory** — the git repository the ledger lives in.
  Outside git the task tools refuse and tell you to `git init`.
- **`task_list` first**, at the start of a session. It shows the tasks, which are ready
  (dependencies done), every case directory, and what is uncommitted.
- **`task_add` before starting a piece of work** you cannot find in the list. The id is a
  short ASCII slug (`duct-v2-run`); the title can be in any language. Name dependencies.
  The line: does this need to survive as a decision or a deliverable someone comes back to,
  or does it only matter until the current turn is done? The former is a task; the latter is
  your own internal to-do list.

  | Example | Where it goes |
  |---|---|
  | "Survey and pick a duct-flow benchmark to validate against" | A Foam-Agent task -- the choice is a decision worth recording, and later work depends on it. |
  | "Search arXiv for the keyword 'duct flow'" | Your own internal to-do list -- one step toward the task above, not a result anyone needs to find again. |

  Typically, one cycle of work breaks into three tasks -- a default shape, not a rule every
  job must follow (see "The bigger loop a job sits in", below, for the same caveat):

  | Unit | Covers |
  |---|---|
  | Prior research | Information-gathering and decisions made before a case exists -- literature, choosing a benchmark. |
  | Case execution | Building the case through `request_review` -- one cycle of build, run, review. |
  | Post-hoc user review | Showing the result to the user and folding their feedback back into the plan. |

  `task_add` also covers work that only turns out to be needed partway through --
  mid-calculation feedback from the user that calls for another literature search or a
  validation case, say. Add it as its own task when it happens, and if an existing task
  should now wait on it (or an existing dependency no longer applies), use `task_amend` to
  change that task's `depends_on` rather than cancelling and re-adding it.
- **`case_register` the moment you create a case directory**, inside the repository. It
  marks the directory (`.foamagent/state.json`, so the mark survives a move) and writes a
  `.gitignore` that keeps time directories, meshes, decomposed domains and logs out of git.
  The case definition, `spec.md`, `report.md` and the review documents stay in. Use `note`
  to say what a case is, or later what replaced it.
- **`task_done` when a task is finished**, with the paths you changed and a message. Only
  those paths and the ledger are committed; the result lists what is still uncommitted, so
  check it for anything you forgot. A task whose dependencies are open is refused.
- **`task_amend` when a plan change leaves the task itself still worth doing** -- new
  dependencies, a title that no longer fits. It stays open; only `depends_on`/`title`
  change, and it commits like everything else here.
- **`task_cancel` when a task is no longer needed**, not when it merely changed shape --
  that is `task_amend`. Dropping one is history too, so it commits.
- **Never `git commit` yourself, and never work on `main`.** Work on a branch named
  `work/<name>` (`git switch -c work/<name>`). Parallel work goes in its own worktree:
  `git worktree add ../<name> -b work/<name>`, and start the harness inside it. The ledger
  is one file per task, so branches merge cleanly. Merging into `main` is the user's call.
- Run data is only where the case was run; what git carries is the definition and the
  documents. Commit `.mcp.json` and `.claude/settings.json` too, if your harness keeps its
  configuration in the project directory (Claude Code does). Hermes keeps it in the profile
  instead, outside the repository, so there is nothing to commit for it.

## The bigger loop a job sits in

A request is rarely just "build and run a case." In practice it tends to look like:

```
set the objective  →  look before building  →  build and run a case  →  read the result  →  change course
```

The two stages below -- looking before building, and building and running a case -- are the
detailed, tool-driven sequence this skill mostly covers. The other stages are real work,
not overhead: agreeing what is actually being asked before a dictionary gets written, and
deciding -- once a result is in -- whether it answers the question or means trying something
else. A well-built case that answers the wrong question is not progress, and a result can
send you back to any earlier stage rather than forward.

Field work does not always fit this neatly, so treat it as what to reach for, not a
checklist every job must complete in order: a request can start mid-loop (objective and
reference case both given up front), skip a stage (nothing to research when the physics is
unambiguous), or go around more than once.

## Look before building

### First, look

Call `describe_environment`. It answers three questions you would otherwise guess at:

1. **Which OpenFOAM is here** — fork (foundation or esi) and version. Their dictionary
   names differ (`physicalProperties` vs `transportProperties`,
   `momentumTransport` vs `turbulenceProperties`), so this decides the syntax you write.
2. **Which solvers exist** — the real contents of `$FOAM_APPBIN`. Never name one that is
   not in that list.
3. **Where the tutorial catalogue is** — `library.catalog`, if one has been built.

If `library` is empty, tell the user to run `foamagent index build` once. Everything below
is much weaker without it.

### Read the knowledge that applies

`describe_environment` also returns `knowledge`: a list of files and what each one is for,
in `knowledge_dir`. Read the ones that bear on the case before writing anything — how to
classify a problem and build a case in order, the mistakes that recur, what a failing log
line means. They are the user's to edit and extend; whatever is in that directory is what
applies here.

### Work from a tutorial, not from memory

`catalog.md` is a table of every tutorial this installation ships: case, solver, domain,
category, and the directory holding it. It is around 35 kB — read all of it.

Pick the case closest to what is being asked for and read its files with your own tools,
directly. The directory `catalog.md` names holds the real files already extracted onto this
machine -- not a claim about where OpenFOAM itself runs (which may well be a container),
and not just an index -- so reading them needs nothing beyond a plain file read. They are a
working, version-correct answer, which beats recalling OpenFOAM syntax from training data.

`by-solver.md` inverts the table when the solver is already decided.
`commands/<name>.txt` holds each application's `-help` output.

### Check the literature before guessing

Training-data memory and a plausible-sounding assumption are not the same as a published
source. When the case needs a value the tutorials and the knowledge files don't supply --
a canonical Reynolds number for a named benchmark, a fluid's properties, an inlet profile,
a geometry from a specific study -- a paper or public dataset with exactly that number is
often one search away, and grounding the case in it does more for the eventual result's
credibility than either a guess or an unexamined default.

Ask before spending time on it, the way you would before assuming anything else: "I can
look for a published reference for this before building -- do you want me to?" A yes that
turns into an actual survey (picking a benchmark, finding its parameters) is usually worth
its own task rather than a side errand (see the task-granularity table above); a no means
proceed on stated assumptions, and say so in `spec.md`.

## Build and run a case

The shape of that stage:

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

### What to ask the user

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

### Write spec.md before you write a case

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

### Offer a completion guarantee before building

Most users run this interactively. Once the conditions in `spec.md` are agreed, state
plainly what a finished result must show — including anything a self-report cannot stand in
for on its own (a claimed convergence study whose directories turn out empty is the kind of
mistake this line exists to catch). Then say:

    If this looks right, run `/goal <the criteria just stated>` to have this session hold
    itself open, refusing to declare completion, until they are met.

`/goal` is a CLI feature, not a tool this skill calls — only the user typing it turns it on,
so ask rather than assume. A session run without it is not wrong, just unsupervised.

### Offer a validation comparison, but don't block on it

Verification — does this run converge, is it mesh-independent, is it numerically sound — is
something this skill can always do on its own. Validation — does the result match reality —
needs an independent reference value it cannot invent. Once the physics is settled and
before building, ask once: "If you have an experimental or DNS reference for this flow,
share it now and I'll compare against it; if not, I'll verify what I can and say plainly
that the result hasn't been checked against independent data."

Unlike the question in the previous section, this one does not block building — proceed
either way once asked. Record the answer in `spec.md`: either the reference value and its
source, or the fact that none was offered. If none was given, say so in as many words when
`request_report` asks what the calculation does not establish — a converged, mesh-independent
run is not the same claim as an accurate one, and the report should not blur the two.

### Check, run, read

Build the case with your own tools, then `validate_case` -- it costs milliseconds, and a
mistake it would have caught costs minutes of solver time instead. Then run `Allrun`
yourself, with your own shell tool (in the background if it supports that: a solve can take
a long time, and nothing here runs it for you). Watch the log as it goes rather than waiting
blind.

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

### When it fails

Work from the first error, not the last. Read the log yourself rather than summarising the
last few lines.

After a fix, rerun from the failing step rather than from scratch when the mesh is
unchanged.

A case that keeps failing is yours to fix. The result review below is for a run that
finished: it asks whether the answer can be believed, which is not a question a crashed
case poses yet.

### When it has run

Call `request_review` with `stage="result"`, then poll `review_status` until it reports
`state="done"`. `review` then holds findings on conformance to `spec.md`, convergence,
conservation, discretisation, physical plausibility and comparison with published values.

Handle them the same way as before: fix what is wrong — rerun if a fix changes the answer —
and write `response-<n>.md` for every round, saying what you changed or why the point does
not hold. Two rounds here as well.

### Reporting back

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
