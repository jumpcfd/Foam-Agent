# Foam-Agent MCP Server

OpenFOAM as tools your AI coding assistant can use: describe the installation, read its
tutorials, write a case, run it, read what happened — and have the work reviewed by a
session that did not write it.

**No API key.** The tools do not call a model of ours. Your assistant is the model — it
chooses the solver, writes the dictionaries and decides what to change after a failure, and
this server gives it the OpenFOAM. The review tools start another session of your own
harness, which is your subscription rather than our key.

> **OpenFOAM version:** whatever you have. `describe_environment` reports the fork
> (foundation or esi), the version, and the applications actually installed;
> `foamagent index build` indexes that installation's own tutorials. The workflow is best
> validated on Foundation v10.

## Quick Start

### 1. Install

```bash
git clone https://github.com/jumpcfd/Foam-Agent.git
cd Foam-Agent
uv sync
```

### 2. Configure your harness

```bash
uv run foamagent install claude-code     # or codex-cli, cursor, cline, generic
```

This writes the MCP server entry (`.mcp.json` for Claude Code) and an OpenFOAM skill that
tells the agent how to work: look at the environment first, start from a tutorial, agree
the conditions before building, check before running, and what each failure category means.

To do it by hand instead:

```bash
claude mcp add foamagent -- foamagent-mcp --transport stdio
```

### 3. Build the reference catalogue

```bash
uv run foamagent index build
```

Reads the tutorials of the OpenFOAM you have and writes, under
`~/.cache/foamagent/indexes/<fork>-<version>/`:

| File | What it is |
|---|---|
| `catalog.md` | One line per tutorial: case, solver, domain, path, files, what was left out |
| `by-solver.md` | The same cases grouped by solver |
| `cases/` | The tutorials themselves, minus geometry, mesh payloads and anything over 100 kB |
| `commands/` | Each application's `-help` output |

The catalogue is around 35 kB for a full installation, small enough for an agent to read
whole and then open only the case it needs.

## Tools

| Tool | What it does |
|---|---|
| `describe_environment` | Fork, version, installed solvers, tutorial paths, where the catalogue is |
| `search_tutorials` | Word-match over the catalogue, for clients that cannot read files |
| `list_case` / `read_case` / `write_case` | Case files, for the same reason |
| `validate_case` | Missing dictionaries, uninstalled solver, patch names that disagree with the mesh |
| `run_start` | Start `Allrun`; returns a run_id immediately |
| `run_status` | running / succeeded / failed / timed_out, plus the errors found |
| `run_tail_log` | The tail of any log; `latest` follows the one being written |
| `run_stop` | Kill the run (and its container, under the docker runtime) |
| `classify_errors` | Name the failures in the logs: category, the line, and what it means |
| `visualize` | A screenshot of the result, from a fixed PyVista template |
| `request_review` | Have the specification (before building) or the result (after the run) checked |
| `request_report` | The report the user is shown |

### The review tools

`request_review` and `request_report` start a fresh, non-interactive session of the
harness — a separate process with no sight of the conversation that produced the case, and
with read-only tools. It can open the case files and search the web; it cannot change
anything.

The exchange stays in the case directory: `spec.md` (the conditions, and the user's request
quoted verbatim), `review-<n>.md` (findings), `response-<n>.md` (the answer to them) and
`report.md`. Two rounds per stage, enforced by the server.

Settings live in `~/.config/foamagent/config.yaml`:

```yaml
review:
  command: [claude, -p]
  allowed_tools: [Read, Grep, Glob, WebSearch, WebFetch]
  prompt_separator: "--"
  timeout_seconds: 1800
```

Those are the defaults, so the file is only needed to change something. Tools that could
modify the case are dropped from the list whatever it says. The prompts themselves are
Markdown in the package; a same-named file under `~/.config/foamagent/templates/` replaces
one (`reviewer-spec.md`, `reviewer-result.md`, `judge-report.md`).

Without a review command on PATH, both tools return a document saying no independent check
was made, and the case still runs.

## Typical session

> "Simulate lid-driven cavity flow at Re=1000"

The assistant calls `describe_environment`, agrees the conditions and writes `spec.md`,
calls `request_review` on it, reads `catalog.md`, opens the `cavity` tutorial, writes a case
from it, calls `validate_case`, `run_start`, follows `run_tail_log`, and — if the run fails
— `classify_errors`, then fixes and runs again. When it completes: `request_review` on the
result, then `request_report`.

## Prerequisites

- **Python 3.10+**
- **OpenFOAM**, sourced natively or reachable with `FOAMAGENT_OPENFOAM_RUNTIME=docker`
- An AI harness that speaks MCP. No LLM API key.

## Architecture

```
AI harness (Claude Code / Codex CLI / Cursor ...)   <- the model lives here
    ↓ MCP protocol (stdio or HTTP)
foamagent-mcp (this server)                          <- no model of its own
    ↓                        ↓
Execution backend            A separate harness session, read-only,
+ the built catalogue        for review and reporting
    ↓
OpenFOAM
```

## Configuration

| Environment Variable | Purpose | Default |
|---------------------|---------|---------|
| `FOAMAGENT_OPENFOAM_RUNTIME` | Where solvers run: `native` or `docker` | `native` |
| `FOAMAGENT_OPENFOAM_IMAGE` / `_BASHRC` | Image and bashrc path for the docker runtime | `openfoam/openfoam10-paraview56` |
| `FOAMAGENT_OPENFOAM_FORK` | Target fork for generated files: `foundation` or `esi` | whichever is installed |
| `FOAMAGENT_INDEX_DIR` | Where built catalogues live | `~/.cache/foamagent/indexes` |
| `FOAMAGENT_INDEX_MAX_FILE_KB` | Size above which a tutorial file is recorded, not kept | `100` |
| `FOAMAGENT_CONFIG_HOME` | Where the review settings and templates live | `~/.config/foamagent` |

## Troubleshooting

**Import errors:** run `uv sync` from the repo root.

**"No reference library has been built":** run `foamagent index build`. Without it the agent
has no catalogue and falls back to whatever it remembers about OpenFOAM.

**"not carried out" in place of a review:** the command in `review.command` is not on PATH.

**OpenFOAM not found:** source it, or set `FOAMAGENT_OPENFOAM_RUNTIME=docker` with an image
that has it:

```bash
docker build -f docker/Dockerfile -t foamagent:latest .
```

**A run seems stuck:** `run_status` reports elapsed seconds; `run_tail_log` shows the live
log; `run_stop` ends it.
