# AGENTS.md

This file is the working guide for coding agents (Codex, Cursor, Claude Code, Copilot,
Hermes Agent, and similar tools) working in this repository.

## Project overview

Foam-Agent connects an AI harness to OpenFOAM. The package contains no model runtime and
does not need its own API key. The harness supplies the reasoning and its native file and
shell tools; the Foam-Agent MCP server measures the OpenFOAM installation, validates cases,
renders results, and starts the independent audit.

The supported harnesses are Claude Code and Hermes Agent. `foamagent init <harness>` writes
the harness configuration and the OpenFOAM skill. Other MCP clients are not configured by
this project.

The main package is under `src/foamagent`. FoamBench is deliberately not part of the
installed package: its checkout-local scripts live under `scripts/bench` and depend on the
external FoamBench dataset and evaluator.

## Working rules

- Read the relevant files and trace definitions/usages before editing. Check `git status` and
  the current branch before relying on repository state.
- Work on a branch or worktree, never on `main` or `master`.
- Register a project task with `task_add` before starting a piece of work. Register a case
  immediately after creating its directory with `case_register`.
- Finish repository work with `task_done`, passing the task id and the paths changed. Do not
  run a bare `git commit`; `task_done` creates the commit containing the task file and the
  declared paths. Merging into `main` is the user's job.
- Do not read, print, or commit credentials, `.env` files, API keys, or other secrets.
- Keep changes focused. Do not rewrite downstream projects or unrelated case files unless
  the user explicitly asks for it.
- Library code must not write to stdout: stdout is the MCP stdio channel. Use the package
  logger (stderr) instead. CLI and checkout-local validation/bench scripts are the explicit
  exceptions because they report to a person.
- Preserve the `foamagent.validation.check` import path. Existing case-local checkers use it
  as a downstream API.

## Build, run, and verify

```bash
uv sync

# Configure a harness and build the catalogue for the OpenFOAM installation
uv run foamagent init claude-code       # or: hermes-agent
uv run foamagent index build
uv run foamagent index list

# Inspect settings and diagnose the installation
uv run foamagent config
uv run foamagent config show
uv run foamagent doctor

# Start the MCP server by hand (harness configuration normally starts it)
uv run foamagent-mcp --transport http --host 0.0.0.0 --port 7860

# Unit and source checks
uv run pytest -m "not integration" -q
uv run ruff check .
uv build

# Real harness/OpenFOAM regression; run manually, not in ordinary unit-test runs
scripts/manual/e2e_cavity.sh
```

Unit tests do not need model credentials, Docker, or a live OpenFOAM installation. Tests
marked `integration` may need OpenFOAM or Docker. The manual E2E script starts a real
harness session and is intentionally not a CI/unit-test substitute.

OpenFOAM must be reachable for indexing and solver execution. The native runtime requires
`WM_PROJECT_DIR` to be set, normally by sourcing the installation's `etc/bashrc`. The Docker
runtime uses the configured image and bashrc path:

```bash
foamagent config set openfoam.runtime docker
```

The detected fork, version, solver list, and tutorial path belong to the installation that
is actually reachable. Do not assume a solver or dictionary spelling from another fork or
version.

## Architecture

### Project and case lifecycle

The project is a git repository. The project ledger is one JSON file per task under
`.foamagent/tasks/`. A task is complete only when `task_done` commits it together with the
declared changes. One file per task lets independent worktrees add tasks without sharing a
single ledger file.

A CFD case is identified by `.foamagent/state.json`, not by a central path registry.
`case_register` writes that state and a case `.gitignore` which keeps generated time
directories, meshes, processor directories, and logs out of git while retaining the case
definition and audit documents.

The normal case workflow is:

```
user <-> Worker
  agree conditions                         -> spec.md (request recorded verbatim)
  request_review(stage="spec")            -> review_status until done
  fix findings                             -> response-N.md
  build case with harness tools
  validate_case, run Allrun, inspect logs, fix failures
  request_review(stage="result")           -> review_status until done
  fix findings                             -> response-N.md
  request_report                           -> report_status until done -> report.md
```

Reviews and reports run asynchronously because a harness session may take many minutes.
The review stages have a server-enforced limit of two rounds each. A skipped or unavailable
review still writes a document explaining that it was not performed.

### Worker, Reviewer, and Judge

- **Worker:** the interactive harness session. It discusses the request, writes the case,
  runs it, repairs failures, and presents the report.
- **Reviewer:** a fresh non-interactive harness session that sees the case documents but not
  the Worker's conversation. It checks the specification before construction and the result
  after the run.
- **Judge:** a fresh session that reads the exchange and audit documents and writes the
  report shown to the user.

Reviewer and Judge are ordinary trusted subprocesses of the configured harness; they are not
made safe by a guessed list of tool names. Their case arithmetic is a separate `run_script`
MCP service. `review/sandbox.py` mounts the case read-only, gives the script a writable
`review-work` directory, disables network access, drops capabilities, and applies fixed
resource limits. Do not add a writable case mount, caller-controlled image/path, or settings
that weaken these limits.

Claude Code reviews receive a strict MCP configuration containing only the Foam-Agent sandbox
server, plus the optional ParaView server when configured. Hermes uses a separate dedicated
review profile. This separation keeps the Worker's MCP server, skills, and task-ledger plugin
out of the review session; it is not a general-purpose tool allowlist.

## Repository layout

```
src/foamagent/
  __init__.py             package metadata
  cli.py                  `foamagent` terminal command
  config.py               OpenFOAM/index/ParaView settings facade
  settings.py             settings-file and environment precedence
  diagnostics.py          checks used by `foamagent doctor`
  environment.py          detects fork, version, solvers, and tutorials
  execution.py            native and Docker OpenFOAM execution backends
  paths.py                run-directory resolution
  locking.py              case/workspace locks
  case_state.py           per-case `.foamagent/state.json`
  tasks.py                git-backed project task ledger
  utils.py                time-directory and log utilities
  logger.py               package logging setup

  mcp/
    cli.py                 `foamagent-mcp` entry point and transport options
    fastmcp_server.py      assembles the full or sandbox FastMCP profile
    deterministic.py       environment, tutorial search, case validation, visualization
    audit.py               request/poll review and report jobs
    tasks.py               MCP wrappers for tasks and case registration
    sandbox.py             `run_script`, available only in the sandbox profile

  harness/
    __init__.py            Claude Code/Hermes configuration and skill installation
    hermes_plugin/          Hermes task-ledger hooks/plugin shipped by `init`
    skill/                  packaged instructions for the harness

  indexing/
    tutorials.py           discovers and extracts tutorial cases
    library.py             writes catalogue, cases, solver index, and help pages
    build.py               builds a library from the live installation

  review/
    settings.py             review command, mode, timeout, and sandbox settings
    channel.py              starts the configured harness subprocess
    registry.py             background review/report job registry
    documents.py            review numbers, documents, rounds, and case state updates
    templates.py             packaged/user-overridable prompt lookup
    templates/*.md           audit prompts
    sandbox.py              read-only case arithmetic container

  services/
    validate.py             deterministic pre-run dictionary/solver/patch checks
    visualization.py        fixed PyVista rendering service

  validation/
    check.py                built-in profile/boundary-layer/range comparisons; compatibility facade
    checker_cli.py           common CLI adapter for case-local checkers
    primitives.py            reusable case readers and numeric helpers
    run.py                  validation showcase/E2E runner
```

Other important directories:

```
tests/                    unit and integration tests
scripts/manual/            real model/OpenFOAM E2E scripts
scripts/bench/             checkout-local FoamBench tools, not installed package code
examples/validation/       published validation inputs and showcase outputs
foambench-basic/           Docker image for the FoamBench Basic split
docker/                    general Foam-Agent container image
src/foamagent/knowledge/    source Markdown for OpenFOAM know-how
plan_docs/                repository plans and design decisions
```

## Module responsibilities

### Configuration and execution

`settings.py` is the single resolver for environment variables, project YAML, user YAML,
and defaults. `config.py` exposes the OpenFOAM-facing dataclass and setting descriptions.
Neither config module contains model settings except that review settings are resolved by
`review/settings.py`.

`execution.py` defines the `ExecutionBackend` contract. `NativeBackend` sources an
OpenFOAM bashrc on the host; `DockerBackend` runs the same command in a container and mounts
the working directory at the same absolute path. All OpenFOAM commands should go through
this abstraction so native and Docker behavior do not diverge.

`environment.py` probes the reachable installation and caches measurements per backend
identity. `indexing/` copies the installation's tutorials, scans them, collects application
help, and writes the reference library used by the harness. There is no shipped tutorial
fallback: a catalogue must describe the installation that will run the case.

`case_state.py` owns facts about one case and review-round counts. `tasks.py` owns the
project-wide git ledger. Do not use one in place of the other.

### MCP server

`mcp/fastmcp_server.py` is the composition root. The full profile registers deterministic
tools, audit tools, and task tools. The sandbox profile registers only `run_script`.
`mcp/cli.py` is the only server process entry point; transport flags belong there.

Deterministic MCP tools live in `mcp/deterministic.py`, with reusable logic in `services/`.
They measure or check; they do not choose a solver, write case dictionaries, or replace the
harness's native shell/file tools. Work that starts a model session belongs in `mcp/audit.py`
and must use `review.channel` and `review.registry` so the request returns promptly and the
job is polled later.

### Harness and review

`harness/` writes the MCP configuration and the OpenFOAM skill for Claude Code or Hermes.
The skill explains how to use the tools; `knowledge/` contains editable OpenFOAM know-how.
Do not put review-generation details into the skill: the Worker should follow the contract,
not write for an imagined reviewer.

`review/channel.py` resolves and starts the configured command. `review/registry.py` runs
reviews and reports in background threads. `review/documents.py` is the authority for
document paths and the two-round limit. `review/templates/*.md` are data, so changing a
checklist normally requires editing a template rather than Python.

### Validation SDK and checker contract

The `validation` package is a small compatibility SDK for published validation cases and
downstream case-local checkers. It is not the main MCP execution pipeline.

`check.py` contains the built-in comparisons currently named `profile`, `boundary_layer`,
and `range`. It re-exports the helper functions from `primitives.py`, preserving existing
imports such as `from foamagent.validation.check import sample_line`.

`primitives.py` provides reusable OpenFOAM case readers and numeric helpers, including
`open_case`, `sample_line`, `integrate`, `wall_patch_names`, `find_leading_edge`,
`coefficients_from_history`, and `steady_window_mean`. These functions do not decide whether
a case agrees with a reference; case-specific code owns the physics and tolerances.

`checker_cli.py` provides the stable command adapter:

```python
from foamagent.validation.checker_cli import run_checker


def check(case_dir, reference):
    return {"metrics": {}, "agrees": True}


if __name__ == "__main__":
    raise SystemExit(run_checker(check))
```

The command receives a built case directory and `--reference reference.json`; `--out`
selects where `comparison.json` is written. A checker must return a JSON object containing a
boolean `agrees`. Other fields are case-specific. `caveats` is an optional list for human
context. `comparison.kind` is not interpreted by the shared adapter and remains a
case-specific value.

`run.py` is intentionally retained as the validation showcase/E2E runner, not as the name
of the checker adapter. It runs a harness session with reviews enabled, compares the built
case before collecting away its mesh, and stores reproducible inputs and audit documents in
`examples/validation`. A case-local `check.py` beside `request.md` and `reference.json`
overrides the built-in comparison and follows the same CLI contract.

### FoamBench

FoamBench is checkout-local research/evaluation tooling, not an importable `foamagent` module
and not part of the wheel. Use the modules under `scripts/bench`:

```bash
export FOAM_AGENT=/path/to/Foam-Agent
export PYTHONPATH="$FOAM_AGENT/src:$FOAM_AGENT${PYTHONPATH:+:$PYTHONPATH}"
python -m scripts.bench.foambench_unpack ...
python -m scripts.bench.foambench_reference ...
python -m scripts.bench.foambench_run ...
python -m scripts.bench.foambench_summary ...
```

The dataset and evaluator live outside this repository. `scripts/bench/README.md` documents
their layout, required evaluator-only dependencies, the scoring patch, and the reason runs
are built outside the dataset's reference directories.

`foambench-basic/Dockerfile` must be built from the repository root:

```bash
docker build -f foambench-basic/Dockerfile -t foambench-basic .
```

It copies the current checkout into the image, installs that checkout, sets
`FOAM_AGENT`/`PYTHONPATH` for the checkout-local scripts, and unpacks the bundled Basic
manifest. Do not make it clone the repository's remote default branch: that would make the
image depend on remote branch state and can select a layout different from the checkout
being built.

## Settings

Resolution order is:

1. environment variable, when the setting has one;
2. project `foamagent.yaml`, `foamagent.yml`, or `.foamagent/config.yaml`, searched upward;
3. user `~/.config/foamagent/config.yaml`;
4. the code default.

`foamagent config show` prints the resolved value and its source. The main settings are:

| Setting | Environment variable | Purpose |
|---|---|---|
| `openfoam.runtime` | `FOAMAGENT_OPENFOAM_RUNTIME` | `native` or `docker` |
| `openfoam.image` | `FOAMAGENT_OPENFOAM_IMAGE` | Docker image containing OpenFOAM |
| `openfoam.bashrc` | `FOAMAGENT_OPENFOAM_BASHRC` | bashrc path inside the configured image |
| `openfoam.fork` | `FOAMAGENT_OPENFOAM_FORK` | Pin `foundation` or `esi`; empty means measured |
| `index.dir` | `FOAMAGENT_INDEX_DIR` | Reference-library cache directory |
| `index.max_file_kb` | `FOAMAGENT_INDEX_MAX_FILE_KB` | Tutorial-file content limit |
| `paraview.dir` | `FOAMAGENT_PARAVIEW_MCP_DIR` | Optional `paraview_mcp` checkout |
| `review.*` | none | Review command, mode, timeout, and sandbox settings |

Environment variables that locate or wire the process, rather than configure a dotted
setting, include:

| Variable | Purpose |
|---|---|
| `WM_PROJECT_DIR` | Native OpenFOAM installation |
| `FOAMAGENT_CONFIG_HOME` | User settings/templates directory |
| `FOAMAGENT_CONFIG_FILE` | Explicit user settings file |
| `FOAMAGENT_TEMPLATES_DIR` | User review-template override directory |
| `FOAMAGENT_PROJECT_CONFIG` | Explicit project settings file; a missing path means none |
| `FOAMAGENT_ROOT` | Override the Foam-Agent root used for run paths |
| `FOAMAGENT_RUN_DIRECTORY` | Override the `runs/` directory directly |
| `FOAMAGENT_LOG_LEVEL` | Package log level; logs go to stderr |

Review modes are `full`, `spec`, and `off`. `off` is appropriate for benchmark runs where
reviews are not part of the measured metric; it must not be silently used for the showcase
workflow.

## Common changes

### Change a review checklist

Edit the appropriate file in `src/foamagent/review/templates/`. A same-named file under
`~/.config/foamagent/templates/` overrides the packaged copy. No Python change is needed.

### Add a deterministic MCP tool

Put reusable logic in `src/foamagent/services/`, add the MCP-facing request/response and
function to `src/foamagent/mcp/deterministic.py`, and add it to `TOOLS`. Keep stdout free and
add unit tests. Do not duplicate the harness's file-editing or shell tools.

### Add an audit operation

Put it in `mcp/audit.py`, use `review.channel` to start the configured harness and
`review.registry` for background execution, and write the resulting document into the case.
Do not block an MCP request for the full lifetime of a model session.

### Rebuild the reference library

```bash
uv run foamagent index build
```

Build once for each OpenFOAM installation. The library is derived from that installation's
tutorials and command help; it is not a portable fallback for another fork/version.

### Update the deployed skill

`src/foamagent/harness/skill/SKILL.md` is packaged and copied by `init`/`sync`. Its frontmatter
version must match `[project].version` in `pyproject.toml`; tests and diagnostics use that
match to detect a stale deployment.

## Things to watch

- Call `describe_environment` first in a worker session. If the index is missing, build it
  before choosing a tutorial. If OpenFOAM cannot be probed, report that fact instead of
  treating the fallback description as a measurement.
- Run `validate_case` before `Allrun`, then inspect the complete solver log yourself. A run
  that was stopped while the solver was still active is not a completed result.
- Keep the review sandbox boundary kernel-enforced. Do not replace the read-only case mount
  with a tool-name denylist or a writable mount.
- Keep checker verdicts evidence-based. The shared contract requires only boolean `agrees`;
  do not add a registry or shared schema for case-specific physics unless a real downstream
  need justifies it.
- `scripts/bench` is source-tree code and is excluded from the normal wheel. Tests should
  verify both sides separately: installed `foamagent.validation` and checkout-local bench
  imports.
- The bundled skill and package version must be updated together.
- `uv run` may update the lockfile while resolving the environment. Do not include an
  incidental `uv.lock` change in a focused task without deciding to update the lockfile.