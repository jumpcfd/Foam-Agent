# AGENTS.md

> This file helps AI agents (Codex, Cursor, Claude Code, Copilot, etc.) understand and work with this codebase.

## What is Foam-Agent?

Foam-Agent automates CFD (Computational Fluid Dynamics) simulations in OpenFOAM from natural language.

There is one arrangement: the MCP server exposes tools that measure, run and check, and the AI harness calling them (Claude Code, Codex CLI, Cursor, …) supplies all the reasoning. No API key. `foamagent install <harness>` writes the configuration and an OpenFOAM skill.

Three roles do the work, and the split is by information rather than by process stage:

- **Worker** — the harness session the user talks to. Dialogue, specification, case, run, fixes.
- **Reviewer** — a separate non-interactive harness session, started by the server, which sees the case documents but not the conversation behind them. Checks the specification before anything is built, and the result after it runs.
- **Judge** — another such session, which reads the whole exchange and writes the report the user is shown.

Reviewer and Judge get read-only tools plus web search. They are `foamagent.review`, driven by `~/.config/foamagent/config.yaml`.

> **OpenFOAM version:** whatever is installed. `foamagent index build` indexes the tutorials of that installation, and `describe_environment` reports fork, version and the applications actually present. ESI (openfoam.com) is detected and indexed; running solvers there is not yet validated end to end. `translation/` converts a Foundation-style case to ESI conventions on request.

## Build and Run

```bash
uv sync

# Configure the harness, build the catalogue, then work in the harness
uv run foamagent install claude-code   # also codex-cli, cursor, cline, generic
uv run foamagent index build
uv run foamagent index list

# Settings and diagnosis
uv run foamagent config                # interactive; writes ~/.config/foamagent/config.yaml
uv run foamagent config show           # every setting, its value, and where that value came from
uv run foamagent doctor                # checks OpenFOAM, catalogue, review command, sandbox, .mcp.json

# Start the MCP server by hand (the harness config starts it for you)
uv run foamagent-mcp --transport http --host 0.0.0.0 --port 7860

# Tests. Unit tests need no credentials, network, Docker or model.
uv run pytest -m "not integration" -q
uv run ruff check .

# End-to-end regression: a real harness session against a real OpenFOAM. Run by hand.
scripts/manual/e2e_cavity.sh
```

Requires OpenFOAM at runtime. Either source it natively (`$WM_PROJECT_DIR` must be set) or set `openfoam.runtime` to `docker` (`foamagent config set openfoam.runtime docker`, or the `FOAMAGENT_OPENFOAM_RUNTIME` environment variable) to run solvers inside a container. Which fork and version that is, which solvers it has, and where its tutorials live are all detected at runtime; when the probe cannot run, detection degrades to Foundation v10.

## Architecture

### How a case goes

```
user ⇄ Worker
  agree conditions            → spec.md (contains the request verbatim)
  request_review "spec"       → review-<n>.md; fix; response-<n>.md     (max 2 rounds)
  build → validate_case → run_start → fix mechanical failures until it completes
  request_review "result"     → review-<n>.md; fix; response-<n>.md     (max 2 rounds)
  request_report              → report.md, shown to the user unchanged
```

Round limits are enforced by the server in `<case_dir>/.foamagent/state.json`, not requested of anyone.

### Directory Structure

```
src/foamagent/          # the importable package (`import foamagent`)
  cli.py               # the `foamagent` command (index / install / config / doctor)
  harness/             # `foamagent install <harness>`: MCP config + the OpenFOAM skill
  settings.py          # Where a setting comes from: env > project file > user file > default
  config.py            # Config dataclass, resolved through settings.py. No model settings here
  diagnostics.py       # What `foamagent doctor` checks, separately from how it prints
  utils.py             # Time directories and log errors, for the run services
  case_state.py        # <case_dir>/.foamagent/state.json: case facts and review rounds
  execution.py         # ExecutionBackend: native (source bashrc) or docker
  environment.py       # Detects fork, version, solvers and tutorials of the installation
  logger.py            # One stderr handler for the whole package
  indexing/            # Builds the reference library from the installation's tutorials
  review/              # The independent review
    settings.py        # The review section: command, per-role model, allowed tools, timeout
    channel.py         # Starting the review session; what to say when it cannot start
    templates.py       # Prompt lookup: packaged, overridden by ~/.config/foamagent/templates
    documents.py       # spec/review/response/report files and the round limits
    sandbox.py         # docker run for a review's scripts: case read-only, no network
    templates/*.md     # The prompts themselves, editable
  services/            # Deterministic services behind the tools
    run_async.py       # run_start/run_status/run_tail_log/run_stop for the MCP tools
    validate.py        # Pre-run checks: dictionaries, solver, patch names
    diagnose.py        # Classifying OpenFOAM failures by regular expression
    visualization.py   # PyVista screenshot from a fixed template
  translation/         # Foundation → ESI naming and dictionary conventions
  paths.py             # Resolves runs/ (FOAMAGENT_ROOT overrides)
  mcp/                 # FastMCP server
    deterministic.py   # The twelve tools that measure, run and check
    audit.py           # request_review and request_report
    sandbox.py         # run_script, served only under `--profile sandbox`
tests/                 # unit tests: no credentials, network, Docker or model
scripts/manual/        # end-to-end scripts that DO start a model; run by hand
docker/                # Dockerfile for containerized deployment
```

### Key Abstractions

- **`Config`** (`src/foamagent/config.py`): where OpenFOAM runs and which fork to write for. Deliberately holds nothing about models.
- **`Settings`** (`src/foamagent/settings.py`): the one place a setting is resolved from, in the order environment variable, project file (`foamagent.yaml`, searched upward to a `.git`), user file (`~/.config/foamagent/config.yaml`), default. Every resolved value carries its origin, which is what `foamagent config show` prints. A setting added to `CONFIG_KEYS` or `REVIEW_KEYS` appears in `config show` and in `config set` without being listed anywhere else.
- **`CaseState`** (`src/foamagent/case_state.py`): what is known about a case (solver, domain, category, iteration count, review rounds spent), persisted to `<case_dir>/.foamagent/state.json`. Rounds are counted here rather than from the files on disk, so deleting a review document cannot buy another round.
- **`ExecutionBackend`** (`src/foamagent/execution.py`): every OpenFOAM command goes through `plan()` / `run()`, so the native and docker runtimes differ in one place. Backends with the same `identity()` reach the same installation.
- **`OpenFOAMEnvironment`** (`src/foamagent/environment.py`): fork, version, `$FOAM_APPBIN` contents and `$FOAM_TUTORIALS`, measured by running a probe through the backend and cached per backend identity.
- **`ChannelSettings`** (`src/foamagent/review/settings.py`): the command line a review is started with. `argv()` builds it; tool names that could modify the case are dropped whatever the settings file says, as is any server tool other than `run_script`.
- **The review sandbox** (`src/foamagent/review/sandbox.py`): a review writes Python and this runs it, in a throwaway container with the case mounted read-only and no network. `docker_argv()` is where the boundary is; the scripts stay in `review-work/` inside the case, so a computed finding can be rechecked.

### Design Patterns

1. **No model in this process.** Every tool either measures, runs, checks, or starts a session of the user's own harness. A server that ran a model of its own would be inference the user cannot see, configure or pay for knowingly.
2. **Split by information, not by stage.** The Worker keeps one context for the whole job, because a fix needs the intent behind the case. The Reviewer exists precisely because it does *not* have that context.
3. **Documents are the interface.** Worker and Reviewer never converse; they exchange files that stay in the case directory. That is also what makes the run auditable afterwards.
4. **Prompts are data.** The review checklists are Markdown in `review/templates/`, replaceable per user. Changing what gets checked is not a code change.
5. **Boundaries the kernel enforces.** A reviewer may read a case and not change it. That is a read-only bind mount, checked by the process that builds the command line, rather than a list of tool names we hope is complete.

## Settings

Each row below can be written in the settings file under the dotted key, or set with the
environment variable, which wins. `foamagent config show` prints both the value and which
of the two (or which file) it came from.

| Setting | Environment variable | Purpose |
|---|---|---|
| `openfoam.runtime` | `FOAMAGENT_OPENFOAM_RUNTIME` | `native` (default) or `docker` |
| `openfoam.image` / `.bashrc` | `FOAMAGENT_OPENFOAM_IMAGE` / `_BASHRC` | Image and bashrc path for the `docker` runtime |
| `openfoam.fork` | `FOAMAGENT_OPENFOAM_FORK` | Pins the fork to generate for; unset means whichever one is installed |
| `run.max_time_limit` | `FOAMAGENT_MAX_TIME_LIMIT` | Seconds before a command is cut off (default 3600) |
| `index.dir` | `FOAMAGENT_INDEX_DIR` | Where built libraries live (default `~/.cache/foamagent/indexes`) |
| `index.max_file_kb` | `FOAMAGENT_INDEX_MAX_FILE_KB` | Size above which a tutorial file is recorded, not kept (default 100) |
| `review.*` | — | The audit: command, per-role model, tools, timeouts, sandbox. An argument list does not fit in an environment variable |

Environment variables with no settings-file equivalent, because they are how the settings
are found or how the process is wired:

| Variable | Purpose |
|----------|---------|
| `WM_PROJECT_DIR` | OpenFOAM installation path (required for `native` runtime) |
| `FOAMAGENT_CONFIG_HOME` | Settings file and templates (default `~/.config/foamagent`) |
| `FOAMAGENT_CONFIG_FILE` / `FOAMAGENT_TEMPLATES_DIR` | Move one of those without moving the other |
| `FOAMAGENT_PROJECT_CONFIG` | Names the project settings file outright; a path that does not exist means there is none |
| `FOAMAGENT_ROOT` | Overrides where `runs/` is looked up |
| `FOAMAGENT_LOG_LEVEL` | Log verbosity (default `INFO`). Logs go to stderr |

## Common Tasks

### Changing what a review checks
Edit `src/foamagent/review/templates/*.md`. A user does the same thing by dropping a same-named file into `~/.config/foamagent/templates/`; the code never needs to know which one it got.

### Adding an MCP tool
Deterministic ones go in `src/foamagent/mcp/deterministic.py` with their logic in `services/`, and are added to its `TOOLS` tuple. Anything that starts a model session belongs in `mcp/audit.py` instead, and must go through `foamagent.review.channel` so the read-only tool policy and the timeout apply to it too.

### Rebuilding the reference library
```bash
uv run foamagent index build
```
Once per OpenFOAM installation. There is no shipped fallback: a library for someone else's OpenFOAM would list cases this machine does not have.

## Things to Watch Out For

- **The library must be built** before the agent has anything to work from. `describe_environment` returns an empty `library` until it is, and the skill tells the agent to say so.
- **OpenFOAM must be reachable** for any simulation execution: either sourced natively (`$WM_PROJECT_DIR`) or via `openfoam.runtime: docker`. `foamagent doctor` says which of those is in effect and whether it worked.
- **Review rounds are capped at two per stage.** If you change that, change it in `review/documents.py`, where the reason is written down — not by making the tools more persuadable.
- **An allowlist widens; only a deny list narrows.** `--allowed-tools` is merged with whatever the user's own settings already permit, so leaving `Bash` out of it does not take `Bash` away — a review was observed shelling out through it. `review/settings.py` therefore also passes `DENIED_TOOLS` to `--disallowed-tools`, and that list is a constant, not a setting.
- **The review's container mounts the case read-only.** Nothing in `review/sandbox.py` should grow a code path that mounts it writable, takes limits from the caller, or lets a tool argument name the image or the directory. The whole value of the sandbox is that it cannot be talked into anything.
- **The harness is not told how reviews are produced.** `harness/skill/` describes the two tools and what to do with what they return, and a test asserts that words like "reviewer" and "subagent" do not appear there. Documentation for people (README) explains the whole arrangement; the point is to stop the Worker writing for an imagined audience, not to keep a secret.
- **stdout belongs to the MCP stdio channel.** Library code logs to stderr; `print` is a lint error outside `scripts/`, and the CLI routes its own output through `cli._emit`.
