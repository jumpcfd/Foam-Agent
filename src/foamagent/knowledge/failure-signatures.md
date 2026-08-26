# Failure signatures: what a log line means and the usual fix

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

---

The classification checklist, the guardrail list and the failure table follow the structure
of `svd-ai-lab/sim-plugin-openfoam` (Apache-2.0), whose OpenFOAM skill is the closest prior
art for this shape of document. Its knowledge targets ESI OpenFOAM; the environment- and
version-specific answers here come from `describe_environment` and the built catalogue
instead.
