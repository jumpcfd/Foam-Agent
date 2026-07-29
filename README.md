# Foam-Agent    <a href="https://arxiv.org/abs/2505.04997"><img src="https://img.shields.io/badge/arXiv-2505.04997-b31b1b.svg" alt="Paper"></a>

<p align="center">
  <b>English</b> | <a href="README_ja.md">日本語</a>
</p>

Foam-Agent lets an AI agent do CFD work in OpenFOAM. It gives a harness — an AI coding tool such as Claude Code — an OpenFOAM environment and a tutorial library, as an MCP server. You ask for a simulation in chat, and the agent creates the case, runs it, and repairs what fails.

The reasoning happens in the harness's model, so Foam-Agent needs no API key of its own.

This repository is a fork of [csml-rpi/Foam-Agent](https://github.com/csml-rpi/Foam-Agent). It differs from upstream in treating the harness as the main path, and in building its reference material by measuring the OpenFOAM you actually have. The upstream path, where Foam-Agent calls a model itself (`direct_api`), is still here; the appendix at the end covers it.

## Key features

| Feature | What it means |
|---|---|
| Runs in the AI tool you already use | `foamagent install claude-code` writes the MCP configuration and an OpenFOAM skill, so setup is that one command |
| Grounded in your OpenFOAM | `foamagent index build` measures the installation you have — fork, version, solver list, tutorials — and writes the catalogue the agent reads |
| Asynchronous runs | Start a solver, poll its status, tail its log, stop it. A run that takes an hour does not hold a connection open for an hour |
| Checks that need no reasoning | `validate_case` catches missing dictionaries, uninstalled solvers and patch-name mismatches before a run, and `classify_errors` names what a failed log means |
| Tells ESI and Foundation apart | It measures which one is installed and reports that to the agent, which absorbs the naming differences (`physicalProperties` versus `transportProperties`, and so on). On ESI v2406, detection and catalogue building (578 cases) are verified; running solvers there is not |

## What you need

| Item | Notes |
|---|---|
| OpenFOAM | Either installed on the host or available as a container image. Verified on Foundation v10 |
| [uv](https://docs.astral.sh/uv/) | Used for dependency management |
| A harness | Claude Code, Codex CLI, Cursor, Cline or Kilo Code |

## Quick start

### 1. Install Foam-Agent

```bash
git clone https://github.com/jumpcfd/Foam-Agent.git
cd Foam-Agent
uv tool install --from . foamagent
```

To also use `visualize`, which renders images of the result, make the last line `uv tool install --from '.[viz]' foamagent`. That pulls in PyVista as well.

`uv tool install` puts the `foamagent` command in `~/.local/bin`, so it runs from any directory. If `~/.local/bin` is not on your PATH, run `uv tool update-shell`.

`uv sync` works too if you only ever use Foam-Agent from inside the repository, but then the command exists only in `.venv/bin`. In that case prefix every command below with `uv run` and run it from the repository directory, for example `uv run foamagent install claude-code`.

### 2. Make OpenFOAM available

To use an OpenFOAM installed on the host, source its bashrc.

```bash
source /opt/openfoam10/etc/bashrc
echo $WM_PROJECT_DIR      # prints e.g. /opt/openfoam10
```

If you have no host installation, pull an OpenFOAM container image instead. Nothing needs to be installed on the host.

```bash
docker pull openfoam/openfoam10-paraview56
export FOAMAGENT_OPENFOAM_RUNTIME=docker
```

That image is the default, so `FOAMAGENT_OPENFOAM_RUNTIME` is the only setting required. For another image, set the image name and the path to the bashrc inside it as well. The images verified so far are below.

| Image | OpenFOAM detected | bashrc inside the image |
|---|---|---|
| `openfoam/openfoam10-paraview56` | foundation 10, 187 commands | `/opt/openfoam10/etc/bashrc` |
| `opencfd/openfoam-default:2406` | esi v2406, 287 commands | `/usr/lib/openfoam/openfoam2406/etc/bashrc` |

For the ESI image:

```bash
docker pull opencfd/openfoam-default:2406
export FOAMAGENT_OPENFOAM_RUNTIME=docker
export FOAMAGENT_OPENFOAM_IMAGE=opencfd/openfoam-default:2406
export FOAMAGENT_OPENFOAM_BASHRC=/usr/lib/openfoam/openfoam2406/etc/bashrc
```

An `export` lasts until you close that shell, so run steps 3 and 4 in the same shell. If you open a new terminal, start again from the `export`. To avoid setting it every time, put the lines in `~/.bashrc`.

### 3. Make a working directory and write the harness configuration

```bash
mkdir ~/cfd && cd ~/cfd
foamagent install claude-code
```

This directory is where you will talk to the agent from now on. Two files are written.

| File | Role |
|---|---|
| `.mcp.json` | How to start Foam-Agent's MCP server |
| `.claude/skills/openfoam-cfd/SKILL.md` | The instructions that tell the agent how to handle OpenFOAM |

No API key is written. The only thing carried into `.mcp.json` is the OpenFOAM environment variables you set in step 2.

For a harness other than Claude Code, replace `claude-code` with `codex-cli`, `cursor`, `cline`, `kilo-code` or `generic`. Those tools pick up configuration files differently, so follow the instructions the command prints.

### 4. Build the tutorial catalogue

```bash
foamagent index build
```

This reads the tutorials of the installed OpenFOAM and writes the material the agent consults. Run it once per OpenFOAM installation. It took 6 seconds for the 248 cases of Foundation v10, and 13 seconds for the 578 cases of ESI v2406.

The output goes to `~/.cache/foamagent/indexes/<fork>-<version>/`. That is outside the repository, so `git pull` or a reinstall will not remove it.

### 5. Confirm the setup

Start Claude Code in the working directory.

```bash
cd ~/cfd
claude
```

On the first start it asks whether to trust the `.mcp.json` in this directory; allow it. Then check two things.

1. `/mcp` lists `foamagent` as connected
2. `/openfoam-cfd` appears in the list of slash commands

If `foamagent` does not appear under `/mcp`, see [Troubleshooting](#troubleshooting).

### 6. Ask for something

From here you write in ordinary English (or Japanese).

```
Simulate lid-driven cavity flow at Re=1000
```

The agent works in this order.

1. `describe_environment` tells it which OpenFOAM is available and which solvers actually exist
2. It picks a close tutorial from `catalog.md` and reads that case's files
3. It writes the case files and checks them with `validate_case` before running
4. It runs with `run_start` and follows progress with `run_status` and `run_tail_log`
5. On failure it classifies the cause with `classify_errors`, edits the files and runs again

## How it works

### MCP tools

Foam-Agent exposes the twelve tools below, none of which calls a model. Choosing the solver, deciding what goes in the dictionaries, and deciding what to change after a failure are all done by the agent in the harness.

| Tool | What it does |
|---|---|
| `describe_environment` | Which OpenFOAM is installed, which solvers exist, and where the catalogue is |
| `search_tutorials` | Searches the catalogue by word match |
| `list_case` | Lists the files of a case |
| `read_case` | Reads one file of a case |
| `write_case` | Writes one file of a case, marking `Allrun` executable |
| `validate_case` | Catches missing dictionaries, uninstalled solvers and mesh/field patch-name mismatches before a run |
| `run_start` | Starts `Allrun` and returns immediately |
| `run_status` | Reports the state of a run, returning at once even while it is running |
| `run_tail_log` | Returns the tail of the log |
| `run_stop` | Stops a run, including the container when one is used |
| `classify_errors` | Classifies a failure in the log and returns the lines and what they mean |
| `visualize` | Renders results with PyVista, using deterministic templates only |

`read_case` and `write_case` refuse paths outside the case directory.

### The reference library

What `foamagent index build` writes is below. The agent reads the first four directly, with no semantic search in between.

| Output | Contents | Size (Foundation v10) |
|---|---|---|
| `catalog.md` | An index of every tutorial: case name, solver, domain, category, location, and what was excluded | one row per case for 248 cases, about 34 kB |
| `by-solver.md` | The same content grouped by solver | about 25 kB |
| `cases/` | The files of each tutorial | 4706 files, 6.8 MB |
| `commands/` | The `-help` output of each command | 187 files |
| `raw/` | The corpus the appendix's `direct_api` path searches. The harness path does not read it | 5.1 MB |

`cases/` excludes geometry, mesh payloads, binaries, and anything over 100 kB. On Foundation v10 that is 100 files and 74.4 MB. Each row of `catalog.md` names what was excluded from that case, so the agent can decide whether to go and look at the original tutorial.

## Configuration

The settings live in `src/foamagent/config.py`, and every one of them can be overridden by an environment variable.

### How OpenFOAM is run

| Environment variable | Purpose | Default |
|---|---|---|
| `FOAMAGENT_OPENFOAM_RUNTIME` | `native` sources the host installation; `docker` runs inside an image | `native` |
| `FOAMAGENT_OPENFOAM_IMAGE` | The image the `docker` runtime uses | `openfoam/openfoam10-paraview56` |
| `FOAMAGENT_OPENFOAM_BASHRC` | Path to the OpenFOAM bashrc inside that image | `/opt/openfoam10/etc/bashrc` |

The `docker` runtime mounts the case directory at the same absolute path inside the container, so the paths in the logs mean the same thing on both sides. It passes your UID and GID, so the generated files are not left owned by root.

### Index and catalogue

| Environment variable | Purpose | Default |
|---|---|---|
| `FOAMAGENT_INDEX_DIR` | Where built indexes are kept | `~/.cache/foamagent/indexes` |
| `FOAMAGENT_INDEX_MAX_FILE_KB` | Tutorial files larger than this are recorded but their contents are not stored | `100` |

`foamagent index list` shows what has been built.

`foamagent index build` does not create embeddings (FAISS) by default. What the harness reads is the text above, and only the appendix's `direct_api` path needs embeddings. To build them too, pass `--with-faiss` and install the `rag-local` extra.

### About the OpenFOAM fork

The fork (Foundation or ESI) and the version are measured, so normally there is nothing to set. The result appears in what `describe_environment` returns and in the name of the index directory (`foundation-10`, `esi-v2406`, and so on).

Setting `FOAMAGENT_OPENFOAM_FORK` overrides the measurement. Use it when you want them to disagree on purpose, such as getting Foundation-style output on a machine that has ESI installed. A disagreement between the setting and the measurement is logged as a warning.

### Other

| Environment variable | Purpose | Default |
|---|---|---|
| `FOAMAGENT_LOG_LEVEL` | Log verbosity. Logs go to stderr; stdout carries only MCP traffic | `INFO` |
| `FOAMAGENT_ROOT` | Where `database/` and `runs/` are looked up | the repository root |

The number of seconds before a solver run is cut off is not an environment variable: it is the `timeout` argument of `run_start`, which defaults to 3600 seconds.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `foamagent: command not found` | After `uv tool install`, check that `~/.local/bin` is on your PATH (`uv tool update-shell` sets it up). After `uv sync`, run commands as `uv run foamagent ...` |
| The wrong `foamagent` starts | Run `which foamagent` to see which one it is. If an older Foam-Agent is installed in another environment such as conda, that one can take precedence |
| `No OpenFOAM environment could be detected` | For a host OpenFOAM, source the bashrc and check that `echo $WM_PROJECT_DIR` prints something. For a container, check that `echo $FOAMAGENT_OPENFOAM_RUNTIME` prints `docker`. Note that a new terminal has lost the `export` from step 2 |
| `foamagent` is missing from `/mcp` | Check that you started in the directory holding `.mcp.json`. If you declined the trust prompt at startup, restart `claude` and allow it |
| `library` comes back empty from `describe_environment` | `foamagent index build` has not been run yet. It is needed once per OpenFOAM installation |
| The agent reaches for a solver that does not exist | Nudge it to call `describe_environment` first. The skill says so as a step, but the step gets skipped as a conversation grows long |
| A run never finishes | `run_status` reports the state and `run_stop` ends it. A run that hits `run_start`'s `timeout` (3600 seconds by default) is cut off automatically |
| Visualization fails | It needs the `viz` extra (PyVista). Reinstall from the repository directory with `uv tool install --force --from '.[viz]' foamagent` |

## Appendix: reasoning inside the process (`direct_api`)

<p align="center">
  <img src="overview.png" alt="Foam-Agent System Architecture" width="800">
</p>

This is the path inherited from upstream, where Foam-Agent calls a model itself. You write the requirement to a file, and a single command goes from planning to execution. It is kept for unattended runs and for reproducing the published benchmark.

Compared with the harness path, it needs an API key to manage, and the tutorials it can consult are limited to what was indexed. For a new user, the harness path is the one to start with.

### Enabling and running it

```bash
export FOAMAGENT_ALLOW_DIRECT_API=1     # without this, in-process inference refuses to start
export FOAMAGENT_MODEL_PROVIDER=openai
export OPENAI_API_KEY=sk-...

uv sync --extra direct-api --extra rag-local
uv run python -m foamagent.main \
  --prompt_path ./user_requirement.txt \
  --output_dir ./output
```

The requirement goes in a plain text file such as `user_requirement.txt`. An example:

```text
do a Reynolds-Averaged Simulation (RAS) pitzdaily simulation. Use PIMPLE algorithm.
The domain is a 2D millimeter-scale channel geometry. Boundary conditions specify a
fixed velocity of 10m/s at the inlet (left), zero gradient pressure at the outlet
(right), and no-slip conditions for walls. Use timestep of 0.0001 and output every
0.01. Finaltime is 0.3. use nu value of 1e-5.
```

To bring in an external Gmsh mesh (ASCII 2.2 format), add `--custom_mesh_path ./tandem_wing.msh` and describe the boundary conditions in the requirement file.

`foambench_main.py` is a thin wrapper that calls the command above; it is used to run the benchmark.

### Settings

| Environment variable | Purpose | Allowed values |
|---|---|---|
| `FOAMAGENT_ALLOW_DIRECT_API` | Permission for in-process inference | `1` allows it. Unset, startup is refused |
| `FOAMAGENT_MODEL_PROVIDER` | LLM backend (default `openai`) | `openai`, `anthropic`, `bedrock`, `ollama` |
| `FOAMAGENT_MODEL_VERSION` | Model identifier (default `gpt-5-mini`) | e.g. `gpt-5-mini`, `claude-opus-4-6` |
| `FOAMAGENT_OPENAI_BASE_URL` | OpenAI-compatible endpoint (OpenRouter, vLLM, LiteLLM, ...) | a base URL; empty means the official OpenAI endpoint |
| `FOAMAGENT_MAX_LOOP` | Maximum error-correction iterations | default `25` |
| `FOAMAGENT_MAX_TIME_LIMIT` | Seconds before a solver run is terminated | default `3600` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / AWS credentials | Authentication for the corresponding provider | |

The `openai-codex` provider has been removed. It read the login token the Codex CLI had saved to disk and replayed it against ChatGPT's backend, which is a credential another tool obtained for its own use. To use Codex CLI, run it as the harness with `foamagent install codex-cli`.

### Retrieval over the reference material

This path does not use the harness path's catalogue. It consults the tutorials through embeddings or word matching instead.

| Environment variable | Purpose | Default |
|---|---|---|
| `FOAMAGENT_RETRIEVAL_BACKEND` | `faiss` (embeddings) or `grep` (word matching, no torch) | `faiss` |
| `FOAMAGENT_EMBEDDING_PROVIDER` | Embedding backend | `huggingface` |
| `FOAMAGENT_EMBEDDING_MODEL` | Embedding model | `Qwen/Qwen3-Embedding-0.6B` |

For `faiss`, build the embeddings with `foamagent index build --with-faiss`. Without them, the Foundation v10 index bundled in the repository is used. That bundled index is stored in Git LFS, so it needs `git lfs install --local && git lfs pull`. Skip that step and the files stay as ~130-byte pointers, failing with `Index type 0x73726576 ("vers") not recognized`.

If you are not building embeddings, set `FOAMAGENT_RETRIEVAL_BACKEND=grep`. It searches the same corpus by word overlap, so there is no model to download.

### Translation to ESI

This path generates in Foundation v10 conventions. With `FOAMAGENT_OPENFOAM_FORK=esi`, the generated files are translated to ESI (`openfoam.com`) naming and dictionary conventions on a best-effort basis before being returned. Verify the run-and-repair loop per case.

The harness path does not use this translation. There the agent reads the result of `describe_environment` and writes in ESI conventions from the start.

### Docker image

Upstream publishes an image containing OpenFOAM v10, Python and all dependencies.

```bash
docker run -it --name foamagent leoyue123/foamagent
```

That image is built by upstream and does not contain this fork's changes. To run this fork in a container, build the image from source.

```bash
docker build -f docker/Dockerfile -t foamagent:latest .
docker run -it -e FOAMAGENT_SKIP_UPDATE=1 foamagent:latest
```

The container fetches the latest code from GitHub on every start, overwriting the code baked into the image. To run the code as it was at build time, set `FOAMAGENT_SKIP_UPDATE=1` as above. `FOAMAGENT_REPO` changes where it fetches from.

To expose the MCP server over HTTP, open the port and start the server.

```bash
docker run -it -p 7860:7860 foamagent:latest \
  foamagent-mcp --transport http --host 0.0.0.0 --port 7860
```

The client configuration for that:

```json
{
  "mcpServers": {
    "foamagent": {
      "url": "http://localhost:7860/mcp"
    }
  }
}
```

### Benchmark results

The numbers below were measured by upstream on the `direct_api` path, evaluated on [FoamBench](https://arxiv.org/abs/2509.20374) with its 110 simulation tasks. They are not numbers for the harness path.

| Framework | Model | Basic | Advanced |
|---|---|---:|---:|
| FoamAgent 2.0.0 (10 loops) | Opus 4.6 | 85.45% | 100% |
| FoamAgent 2.0.0 (25 loops) | Opus 4.6 | 100% | 100% |
| FoamAgent 2.0.0 (25 loops) | Sonnet 4.6 | 87.88% | 75.00% |
| FoamAgent 2.0.0 (25 loops) | Haiku 4.6 | 54.55% | 37.50% |
| FoamAgent 2.0.0 (25 loops) | gpt-5.4 | 45.45% | 75.00% |
| FoamAgent 2.0.0 (25 loops) | gpt-5.3-codex | 54.55% | 62.50% |

## Development

```bash
uv sync                          # core and dev tools
uv run pytest -m "not integration" -q
uv run ruff check .
```

The unit tests need no API credentials, no network, no Docker, no Git LFS content and no torch. That constraint is what keeps `import foamagent` free of side effects, so please keep new unit tests within it. Tests that need the bundled database are marked `integration` and are excluded by default.

CI runs lint, the unit tests on Python 3.10 and 3.12, and a wheel build on every push and pull request. It checks out without Git LFS content on purpose.

The extras are below. The core install deliberately leaves out anything heavy.

| Extra | Provides | Needed when |
|---|---|---|
| `viz` | PyVista | Rendering results |
| `rag-local` | FAISS, sentence-transformers, torch (CPU) | Embedding-based retrieval on the `direct_api` path |
| `direct-api` | langchain-openai, langchain-anthropic, openai, anthropic | Using the `direct_api` path |
| `web` | FastAPI, uvicorn | The `app.py` web UI |
| `hpc` | boto3 | SLURM/HPC submission |
| `ollama`, `bedrock` | Provider SDKs | Those providers |
| `all` | Everything above | |

## Acknowledgements

The skill's design draws on the OpenFOAM skill in [sim-plugin-openfoam](https://github.com/svd-ai-lab/sim-plugin-openfoam) (Apache-2.0).

## Citation

If you use Foam-Agent in your research, please cite our paper:

```bibtex
@article{yue2025foam,
  title={Foam-Agent: Towards Automated Intelligent CFD Workflows},
  author={Yue, Ling and Somasekharan, Nithin and Zhang, Tingwen and Cao, Yadi and Chen, Zhangze and Di, Shimin and Pan, Shaowu},
  journal={arXiv preprint arXiv:2505.04997},
  year={2025}
}

@article{somasekharan2026cfdllmbench,
    title={CFDLLMBench: A Benchmark Suite for Evaluating Large Language Models in Computational Fluid Dynamics},
    author={Somasekharan, Nithin and Yue, Ling and Cao, Yadi and Li, Weichao and Emami, Patrick and Bhargav, Pochinapeddi Sai and Acharya, Anurag and Xie, Xingyu and Pan, Shaowu},
    journal={Journal of Data-centric Machine Learning Research},
    year={2026},
    url={https://openreview.net/forum?id=kTcH1MnkjY},
    note={}
}
```

## Community

Chinese-speaking users can join upstream's WeChat community by adding the volunteer's WeChat account ZDSJTUCFD. The volunteer will invite you to the group.
