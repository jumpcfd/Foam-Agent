# AGENTS.md

> This file helps AI agents (Codex, Cursor, Claude Code, Copilot, etc.) understand and work with this codebase.

## What is Foam-Agent?

Foam-Agent automates CFD (Computational Fluid Dynamics) simulations in OpenFOAM from natural language.

There are two arrangements, and they differ in who runs the model:

- **host_delegate (default)**: the MCP server exposes tools that measure, run and check; the AI harness calling them (Claude Code, Codex CLI, Cursor, …) supplies all the reasoning. No API key. `foamagent install <harness>` writes the configuration and an OpenFOAM skill.
- **direct_api (opt-in)**: the original LangGraph pipeline, running a model in-process via LangChain. Requires `FOAMAGENT_ALLOW_DIRECT_API=1` and a provider key. Kept for unattended runs and for comparison with the published benchmark.

> **Important:** The shipped reference index is built from **Foundation OpenFOAM v10** ([openfoam.org](https://openfoam.org)) tutorials, so that is what generation reproduces out of the box. ESI OpenFOAM (openfoam.com, e.g. v2312, v2406) is reached two ways: post-generation translation (`FOAMAGENT_OPENFOAM_FORK=esi`), and `foamagent index build`, which indexes the tutorials of whichever OpenFOAM is actually installed. Neither has been validated end to end on ESI yet.

## Build and Run

```bash
# Environment setup (uv). Core is intentionally lightweight; add the extras you need.
git lfs install --local && git lfs pull        # database/ is stored with Git LFS
uv sync

# host_delegate: configure the harness, build the catalogue, then work in the harness
uv run foamagent install claude-code   # also codex-cli, cursor, cline, generic
uv run foamagent index build           # --with-faiss also embeds it (needs rag-local)
uv run foamagent index list

# Start the MCP server by hand (the harness config starts it for you)
uv run python -m foamagent.mcp.fastmcp_server --transport http --host 0.0.0.0 --port 7860

# direct_api: the LangGraph pipeline, which runs a model in-process
uv sync --extra rag-local --extra direct-api --extra viz
export FOAMAGENT_ALLOW_DIRECT_API=1
uv run python foambench_main.py --output ./output --prompt_path ./user_requirement.txt
uv run python foambench_main.py --output ./output --prompt_path ./user_requirement.txt --custom_mesh_path ./mesh.msh

# Run tests. Unit tests need no credentials, network, Docker, or LFS content.
uv run pytest -m "not integration" -q
uv run ruff check .
```

Requires OpenFOAM at runtime. Either source it natively (`$WM_PROJECT_DIR` must be set) or set `FOAMAGENT_OPENFOAM_RUNTIME=docker` to run solvers inside a container. Which fork and version that is, which solvers it has, and where its tutorials live are all detected at runtime; when the probe cannot run, detection degrades to Foundation v10.

## Architecture

### Workflow Pipeline (LangGraph StateGraph)

Defined in `src/foamagent/main.py`:

```
PLANNER -> [mesh routing] -> MESHING (if needed) -> INPUT_WRITER -> [HPC/local routing]
-> RUNNER -> [error check] -> REVIEWER -> INPUT_WRITER (retry loop, max 25 iterations)
-> VISUALIZATION (if requested) -> END
```

All routing decisions (mesh type, HPC vs local, visualization) are LLM calls in `src/foamagent/router_func.py`.

### Directory Structure

```
src/foamagent/          # the importable package (`import foamagent`)
  main.py              # LangGraph workflow definition and entry point (direct_api only)
  cli.py               # the `foamagent` command (index build / index list / install)
  inference/           # Who runs the model: host_delegate (default), host_sampling, direct_api
  harness/             # `foamagent install <harness>`: MCP config + the OpenFOAM skill
  config.py            # Config dataclass with env var overrides
  utils.py             # GraphState (TypedDict), LLMService (unified LLM interface)
  models.py            # Pydantic models for generated files and plans
  case_state.py        # <case_dir>/.foamagent/state.json, shared by both entry points
  execution.py         # ExecutionBackend: native (source bashrc) or docker
  environment.py       # Detects fork, version, solvers and tutorials of the installation
  router_func.py       # LLM-based routing decisions
  logger.py            # Structured XML-tagged logging
  retrieval/           # Retriever interface: faiss (default) and grep (no embeddings)
  indexing/            # Builds an index from the detected installation's tutorials
  nodes/               # LangGraph node functions (thin wrappers calling services)
    planner_node.py
    input_writer_node.py
    meshing_node.py
    local_runner_node.py
    hpc_runner_node.py
    reviewer_node.py
    visualization_node.py
  services/            # Business logic (where the real work happens)
    plan.py            # Case planning and analysis (needs a model)
    input_writer.py    # OpenFOAM file generation via LLM + RAG (needs a model)
    mesh.py            # Mesh generation (blockMesh / Gmsh conversion)
    run_local.py       # Synchronous local execution, used by the LangGraph pipeline
    run_async.py       # run_start/run_status/run_tail_log/run_stop for the MCP tools
    validate.py        # Pre-run checks: dictionaries, solver, patch names (no model)
    diagnose.py        # Classifying OpenFOAM failures by regular expression (no model)
    run_hpc.py         # HPC job submission
    review.py          # Error diagnosis and fix planning (needs a model)
    visualization.py   # PyVista-based post-processing
  paths.py             # Resolves database/ and runs/ (FOAMAGENT_ROOT overrides)
  mcp/                 # FastMCP server exposing workflow as tools
database/
  faiss/               # Pre-built FAISS vector indices (do NOT regenerate unless necessary)
  raw/                 # Raw OpenFOAM tutorial data
tests/                 # unit tests: no credentials, network, Docker, or LFS content
scripts/manual/        # end-to-end scripts that DO need credentials; run by hand
docker/                # Dockerfile for containerized deployment
```

### Key Abstractions

- **`GraphState`** (`src/foamagent/utils.py`): TypedDict threaded through all workflow nodes. Contains user requirement, case metadata, generated files, error logs, loop count.
- **`LLMService`** (`src/foamagent/utils.py`): Unified LLM interface supporting OpenAI, Anthropic, Bedrock, Ollama. Provides `invoke()` and `structure_output()` (Pydantic-validated).
- **`Config`** (`src/foamagent/config.py`): Global config dataclass. Every field can be overridden via `FOAMAGENT_*` env vars.
- **Pydantic models** (`src/foamagent/models.py`): `FoamPydantic`/`FoamfilePydantic` for generated files, `RewritePlan` for error fixes, `CaseSummaryModel` for case metadata.
- **`CaseState`** (`src/foamagent/case_state.py`): what is known about a case (solver, domain, category, subtasks, iteration count), persisted to `<case_dir>/.foamagent/state.json`. The LangGraph nodes and the MCP tools read and write the same file, which is how an MCP client gets the real solver instead of a placeholder.
- **`ExecutionBackend`** (`src/foamagent/execution.py`): every OpenFOAM command goes through `plan()` / `run()`, so the native and docker runtimes differ in one place. Backends with the same `identity()` reach the same installation.
- **`OpenFOAMEnvironment`** (`src/foamagent/environment.py`): fork, version, `$FOAM_APPBIN` contents and `$FOAM_TUTORIALS`, measured by running a probe through the backend and cached per backend identity.
- **`Retriever`** (`src/foamagent/retrieval/`): `FaissRetriever` (default, needs the `rag-local` extra) and `GrepRetriever` (word matching over the raw corpus, no embeddings and no torch). Callers ask for references and never name a method.

### Design Patterns

1. **Service-oriented**: Nodes in `src/foamagent/nodes/` are thin orchestration wrappers. All logic lives in `src/foamagent/services/`.
2. **Error correction loop**: Runner detects errors -> Reviewer diagnoses via LLM -> Input Writer rewrites targeted files -> re-run (up to `max_loop` iterations).
3. **RAG retrieval**: indices built from OpenFOAM tutorials provide reference cases to the input writer, through the retriever interface rather than through FAISS directly.
4. **Two generation modes** (`config.input_writer_generation_mode`):
   - `sequential_dependency` (default): Files generated in order with cross-file context.
   - `parallel_no_context`: All files generated independently (faster, relies on retry loop).

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `FOAMAGENT_MODEL_PROVIDER` | LLM provider: `openai`, `anthropic`, `bedrock`, `ollama` (direct_api only) |
| `FOAMAGENT_MODEL_VERSION` | Model identifier (e.g., `claude-opus-4-6`, `gpt-5.3-codex`) |
| `FOAMAGENT_EMBEDDING_PROVIDER` | Embedding backend: `openai`, `huggingface`, `ollama` |
| `FOAMAGENT_EMBEDDING_MODEL` | Embedding model (default: `Qwen/Qwen3-Embedding-0.6B`) |
| `OPENAI_API_KEY` | Required for `openai` provider |
| `ANTHROPIC_API_KEY` | Required for `anthropic` provider |
| `WM_PROJECT_DIR` | OpenFOAM installation path (required for `native` runtime) |
| `FOAMAGENT_OPENFOAM_FORK` | Pins the fork to generate for; unset means whichever one is installed |
| `FOAMAGENT_OPENAI_BASE_URL` | OpenAI-compatible endpoint (OpenRouter, vLLM, LiteLLM, ...) |
| `FOAMAGENT_OPENFOAM_RUNTIME` | `native` (default) or `docker` |
| `FOAMAGENT_OPENFOAM_IMAGE` / `_BASHRC` | Image and bashrc path for the `docker` runtime |
| `FOAMAGENT_ROOT` | Overrides where `database/` and `runs/` are looked up |
| `FOAMAGENT_RETRIEVAL_BACKEND` | `faiss` (default) or `grep` (no embedding model needed) |
| `FOAMAGENT_INDEX_DIR` | Where built indices live (default `~/.cache/foamagent/indexes`) |
| `FOAMAGENT_INDEX_MAX_FILE_KB` | Size above which a tutorial file is recorded, not kept (default 100) |
| `FOAMAGENT_INFERENCE_BACKEND` | `host_delegate` (default), `host_sampling`, `direct_api` |
| `FOAMAGENT_ALLOW_DIRECT_API` | Required before anything runs a model in this process |
| `FOAMAGENT_LOG_LEVEL` | Log verbosity (default `INFO`). Logs go to stderr |

## Common Tasks

### Adding a new LLM provider
Extend `LLMService` in `src/foamagent/utils.py`. Follow the pattern of existing providers (each has an `if` branch in the constructor).

### Adding a new workflow node
1. Create service logic in `src/foamagent/services/`.
2. Create a thin node wrapper in `src/foamagent/nodes/`.
3. Wire it into the StateGraph in `src/foamagent/main.py`.

### Modifying file generation
The input writer logic is in `src/foamagent/services/input_writer.py`. It uses RAG context from FAISS indices and LLM calls to generate OpenFOAM configuration files.

### Rebuilding the reference index
```bash
uv run foamagent index build              # library + text corpus, into ~/.cache/foamagent
uv run foamagent index build --with-faiss # also embed the corpus (needs the rag-local extra)
```
A built index is preferred over the shipped one automatically, so nothing changes for a user who never builds. `init_database.py` still rebuilds `database/` in place for a natively sourced Foundation installation.

## Things to Watch Out For

- **The shipped index describes Foundation v10.** On any other installation, build one with `foamagent index build` rather than editing `database/`.
- **OpenFOAM must be reachable** for any simulation execution: either sourced natively (`$WM_PROJECT_DIR`) or via `FOAMAGENT_OPENFOAM_RUNTIME=docker`. Without either, the runner nodes fail.
- **The error correction loop** can run up to 25 iterations. When modifying the reviewer or input writer, consider the impact on convergence.
- **`GraphState` is mutable** and passed by reference through the entire pipeline. Be careful about unintended side effects when modifying state fields.
