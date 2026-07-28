# Foam-Agent MCP Server

Expose OpenFOAM CFD simulation as tools for any AI coding assistant via [MCP (Model Context Protocol)](https://modelcontextprotocol.io/).

> **OpenFOAM version:** This server targets **Foundation OpenFOAM v10** ([openfoam.org](https://openfoam.org)) by default. If `FOAMAGENT_OPENFOAM_FORK=esi` is set, generated input files are translated to ESI OpenFOAM ([openfoam.com](https://openfoam.com), e.g., v2312, v2406, v2512) naming and dictionary conventions on a best-effort basis. The run/review/fix workflow is still primarily validated with Foundation OpenFOAM v10.

## Quick Start

### 1. Install

```bash
# Clone and install. Dependencies are managed with uv.
git clone https://github.com/csml-rpi/Foam-Agent.git
cd Foam-Agent

# database/ is stored with Git LFS; without this the indices are pointer files
git lfs install --local && git lfs pull

# Core is lightweight. Add the extras you use: rag-local (retrieval), direct-api, viz.
uv sync --extra rag-local --extra direct-api --extra viz
```

### 2. Register with your AI tool (one command)

**Claude Code:**
```bash
claude mcp add foamagent -- foamagent-mcp
```

**Cursor:**
Add to `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "foamagent": {
      "command": "foamagent-mcp"
    }
  }
}
```

**Windsurf / Other MCP-compatible tools:**
```json
{
  "mcpServers": {
    "foamagent": {
      "command": "foamagent-mcp"
    }
  }
}
```

**HTTP mode** (for web clients or remote access):
```bash
foamagent-mcp --transport http --host 0.0.0.0 --port 7860
```

### 3. Configure LLM provider (optional)

Set environment variables to choose your LLM backend:

```bash
export FOAMAGENT_MODEL_PROVIDER=anthropic          # openai, anthropic, bedrock, ollama
export FOAMAGENT_MODEL_VERSION=claude-sonnet-4-6   # model identifier
export ANTHROPIC_API_KEY=sk-ant-...                # API key for your provider
```

## Available MCP Tools

Foam-Agent generates output following **Foundation OpenFOAM v10** conventions by default. If
`FOAMAGENT_OPENFOAM_FORK=esi` is set, generated input files are translated to ESI OpenFOAM
conventions on a best-effort basis before they are returned.

| Tool | Description |
|------|-------------|
| `plan` | Analyze user requirements and plan simulation structure (solver, domain, subtasks) using Foundation v10 references |
| `input_writer` | Generate OpenFOAM configuration files; optionally translate generated files when `FOAMAGENT_OPENFOAM_FORK=esi` |
| `run` | Execute Allrun script locally with error collection; primarily validated with Foundation OpenFOAM v10 |
| `review` | Analyze simulation errors and suggest fixes via LLM using Foundation v10 references |
| `apply_fixes` | Rewrite OpenFOAM files based on review analysis; ESI cases remain best-effort |
| `visualization` | Generate PyVista visualization of simulation results |

## Typical Workflow

Once registered, ask your AI assistant naturally:

> "Simulate lid-driven cavity flow at Re=1000"

The assistant will call the tools in sequence:
1. **plan** - Parse requirements, select solver, generate subtasks
2. **input_writer** - Generate all OpenFOAM files
3. **run** - Execute the simulation
4. **review + apply_fixes** - Fix errors if any (automatic retry loop)
5. **visualization** - Render results

## Prerequisites

- **Python 3.10+** with dependencies installed
- **OpenFOAM**, either sourced on this machine or reachable with `FOAMAGENT_OPENFOAM_RUNTIME=docker`. **Foundation v10** ([openfoam.org](https://openfoam.org)) is the fully validated path, since the shipped reference index is built from its tutorials. On ESI OpenFOAM (`openfoam.com`), run `foamagent index build` to index your own installation and set `FOAMAGENT_OPENFOAM_FORK=esi` for best-effort translation; execution and repair loops should be verified per case.
- An LLM API key (OpenAI, Anthropic, or local via Ollama)

## Architecture

```
AI Tool (Claude Code / Cursor / ...)
    ↓ MCP protocol (stdio or HTTP)
foamagent-mcp (this server)
    ↓
Service Layer (src/foamagent/services/*.py)
    ↓
OpenFOAM + LLM Services
```

## Advanced Configuration

| Environment Variable | Purpose | Default |
|---------------------|---------|---------|
| `FOAMAGENT_MODEL_PROVIDER` | LLM backend | `openai-codex` |
| `FOAMAGENT_MODEL_VERSION` | Model identifier | `gpt-5.3-codex` |
| `FOAMAGENT_EMBEDDING_PROVIDER` | Embedding backend | `huggingface` |
| `FOAMAGENT_EMBEDDING_MODEL` | Embedding model | `Qwen/Qwen3-Embedding-0.6B` |
| `FOAMAGENT_OPENFOAM_FORK` | OpenFOAM target fork for generated files: `foundation` or `esi` | `foundation` |
| `FOAMAGENT_OPENFOAM_RUNTIME` | Where solvers run: `native` or `docker` | `native` |
| `FOAMAGENT_RETRIEVAL_BACKEND` | `faiss` (embeddings) or `grep` (no embedding model) | `faiss` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |

## Troubleshooting

**Import errors:** Ensure you ran `uv sync` from the repo root.

**Database errors:** The indices ship pre-built in `database/`, stored with Git LFS. If they are ~130-byte pointer files, run `git lfs install --local && git lfs pull`. To build an index from your own OpenFOAM instead:
```bash
uv run foamagent index build
```

**OpenFOAM not found:** The default validated runtime path requires Foundation OpenFOAM v10 ([openfoam.org](https://openfoam.org)). If using ESI OpenFOAM, set `FOAMAGENT_OPENFOAM_FORK=esi` and verify the generated case against your local ESI installation. Install Foundation v10 or use the Docker image:
```bash
docker build -f docker/Dockerfile -t foamagent:latest .
docker run -it -p 7860:7860 foamagent:latest foamagent-mcp --transport http
```
