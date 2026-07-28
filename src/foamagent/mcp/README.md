# Foam-Agent MCP Server

OpenFOAM as tools your AI coding assistant can use: describe the installation, read its
tutorials, write a case, run it, and read what happened.

**No API key.** The tools do not call a model. Your assistant is the model — it chooses the
solver, writes the dictionaries and decides what to change after a failure, and this server
gives it the OpenFOAM.

> **OpenFOAM version:** whatever you have. `describe_environment` reports the fork
> (foundation or esi), the version, and the applications actually installed;
> `foamagent index build` indexes that installation's own tutorials. The workflow is best
> validated on Foundation v10, which is what the shipped fallback index was built from.

## Quick Start

### 1. Install

```bash
git clone https://github.com/csml-rpi/Foam-Agent.git
cd Foam-Agent
uv sync
```

### 2. Configure your harness

```bash
uv run foamagent install claude-code     # or codex-cli, cursor, cline, generic
```

This writes the MCP server entry (`.mcp.json` for Claude Code) and an OpenFOAM skill that
tells the agent how to work: look at the environment first, start from a tutorial, check
before running, and what each failure category means.

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

### Model-driven tools (opt-in)

`plan`, `input_writer`, `review`, `apply_fixes` and `visualization` run a model inside the
server. They are registered only when there is one to run:

```bash
export FOAMAGENT_ALLOW_DIRECT_API=1          # plus a provider key
# or
export FOAMAGENT_INFERENCE_BACKEND=host_sampling   # the client's own model, if it supports it
```

## Typical session

> "Simulate lid-driven cavity flow at Re=1000"

The assistant calls `describe_environment`, reads `catalog.md`, opens the `cavity` tutorial,
writes a case from it, calls `validate_case`, `run_start`, follows `run_tail_log`, and — if
the run fails — `classify_errors`, then fixes and runs again.

## Prerequisites

- **Python 3.10+**
- **OpenFOAM**, sourced natively or reachable with `FOAMAGENT_OPENFOAM_RUNTIME=docker`
- An AI harness that speaks MCP. No LLM API key.

## Architecture

```
AI harness (Claude Code / Codex CLI / Cursor ...)   <- the model lives here
    ↓ MCP protocol (stdio or HTTP)
foamagent-mcp (this server)                          <- no model
    ↓
Execution backend (native or docker) + the built catalogue
    ↓
OpenFOAM
```

## Configuration

| Environment Variable | Purpose | Default |
|---------------------|---------|---------|
| `FOAMAGENT_OPENFOAM_RUNTIME` | Where solvers run: `native` or `docker` | `native` |
| `FOAMAGENT_OPENFOAM_IMAGE` / `_BASHRC` | Image and bashrc path for the docker runtime | `foam-bench:latest` |
| `FOAMAGENT_OPENFOAM_FORK` | Target fork for generated files: `foundation` or `esi` | `foundation` |
| `FOAMAGENT_INDEX_DIR` | Where built catalogues live | `~/.cache/foamagent/indexes` |
| `FOAMAGENT_INDEX_MAX_FILE_KB` | Size above which a tutorial file is recorded, not kept | `100` |
| `FOAMAGENT_INFERENCE_BACKEND` | `host_delegate`, `host_sampling`, `direct_api` | `host_delegate` |
| `FOAMAGENT_ALLOW_DIRECT_API` | Required before anything runs a model in this process | unset |

## Troubleshooting

**Import errors:** run `uv sync` from the repo root.

**"No reference library has been built":** run `foamagent index build`. Without it the agent
has no catalogue and falls back to whatever it remembers about OpenFOAM.

**OpenFOAM not found:** source it, or set `FOAMAGENT_OPENFOAM_RUNTIME=docker` with an image
that has it:

```bash
docker build -f docker/Dockerfile -t foamagent:latest .
```

**A run seems stuck:** `run_status` reports elapsed seconds; `run_tail_log` shows the live
log; `run_stop` ends it.
