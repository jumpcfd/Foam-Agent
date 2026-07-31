# Foam-Agent    <a href="https://arxiv.org/abs/2505.04997"><img src="https://img.shields.io/badge/arXiv-2505.04997-b31b1b.svg" alt="Paper"></a>

<p align="center">
  <b>English</b> | <a href="README_ja.md">日本語</a>
</p>

Foam-Agent lets an AI agent do CFD work in OpenFOAM. It gives a harness — an AI coding tool such as Claude Code — an OpenFOAM environment and a tutorial library, as an MCP server. You ask for a simulation in chat, and the agent agrees the conditions with you, creates the case, runs it, repairs what fails, and has the work reviewed before reporting back.

The reasoning happens in the harness's model, so Foam-Agent needs no API key of its own.

This repository is a fork of [csml-rpi/Foam-Agent](https://github.com/csml-rpi/Foam-Agent). It differs from upstream in treating the harness as the only path, in building its reference material by measuring the OpenFOAM you actually have, and in reviewing a case independently of whoever built it. The upstream path, where Foam-Agent calls a model itself (`direct_api`), has been removed.

## Key features

| Feature | What it means |
|---|---|
| Runs in the AI tool you already use | `foamagent install claude-code` writes the MCP configuration and an OpenFOAM skill, so setup is that one command |
| Grounded in your OpenFOAM | `foamagent index build` measures the installation you have — fork, version, solver list, tutorials — and writes the catalogue the agent reads |
| Reviewed, not just run | The specification is checked against your own words before anything is built, the finished result is checked against the specification, and the report you read is written by neither of them. See [Review](#review) |
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
2. It asks about anything your request left open, and writes the agreed conditions — with your request quoted word for word — to `spec.md`
3. `request_review` checks that specification against your words, before anything is built
4. It picks a close tutorial from `catalog.md` and reads that case's files
5. It writes the case files and checks them with `validate_case` before running
6. It runs with `run_start` and follows progress with `run_status` and `run_tail_log`
7. On failure it classifies the cause with `classify_errors`, edits the files and runs again
8. Once the run completes, `request_review` checks the result, and `request_report` produces what you read

## How it works

### MCP tools

Foam-Agent exposes the fourteen tools below. Choosing the solver, deciding what goes in the dictionaries, and deciding what to change after a failure are all done by the agent in the harness; the twelve deterministic tools measure, run and check. The last two are the exception, and are described under [Review](#review).

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
| `request_review` | Has the specification, or the finished result, checked independently |
| `request_report` | Produces the report you are shown |

`read_case` and `write_case` refuse paths outside the case directory.

### Review

A case built by one agent and checked by the same agent has been checked by whoever decided it was right. So the check runs somewhere else: `request_review` and `request_report` start a fresh, non-interactive session of the harness you already run — a separate process, with no access to the conversation that produced the case, and with read-only tools. It can open the case files and search the web; it cannot change anything.

Three roles, then. The agent you talk to (**Worker**) does the CFD: the dialogue, the specification, the case, the run, the fixes. The **Reviewer** sees documents only and looks for what is wrong with them. The **Judge** reads the whole exchange and writes your report, ruling on each disputed point rather than splitting the difference.

The exchange is entirely on paper, and the paper stays in the case directory:

| File | Written by | Contents |
|---|---|---|
| `spec.md` | Worker | The conditions agreed with you, and your request quoted verbatim. The quotation is what the specification is checked against |
| `review-<n>.md` | Reviewer | The findings of one round |
| `response-<n>.md` | Worker | What was changed, or why the finding does not hold |
| `report.md` | Judge | What was asked, what was run, the result, a ruling per disputed point, and what the calculation does not establish |
| `review-work/` | Reviewer, Judge | The Python they computed their numbers with, one directory per document |

Two rounds per stage, enforced by the server. Past that an argument stops converging, and neither party is the right one to decide when to stop.

The Reviewer can also calculate. A residual history checked by eye and a mass balance asserted rather than summed are how a plausible result passes review, so the review is given a Python interpreter: it writes a script, and Foam-Agent runs it in a throwaway container with the case mounted **read-only** and no network. That mount is what makes "may read the case, may not change it" a property of the kernel rather than a list of tool names we hope covers everything — and the scripts stay in the case, so the arithmetic behind a finding can be checked afterwards, by the Judge or by you. It needs Docker; without it the review still runs and is told to say which checks it could not make.

Two consequences worth knowing. The review costs whatever your harness charges for the extra sessions — it is your subscription, not an API key of ours. And a machine with no configured review command still runs cases: the tools return a document saying no independent check was made, and the agent is instructed to tell you so rather than absorb it.

The prompts the review works from are Markdown files in the package. To change what is checked, drop a file of the same name into `~/.config/foamagent/templates/`:

| Template | Used for |
|---|---|
| `reviewer-spec.md` | Checking the specification against your request |
| `reviewer-result.md` | Checking a completed result |
| `judge-report.md` | Writing the report |

### The reference library

What `foamagent index build` writes is below. The agent reads all of it directly, with no semantic search in between.

| Output | Contents | Size (Foundation v10) |
|---|---|---|
| `catalog.md` | An index of every tutorial: case name, solver, domain, category, location, and what was excluded | one row per case for 248 cases, about 34 kB |
| `by-solver.md` | The same content grouped by solver | about 25 kB |
| `cases/` | The files of each tutorial | 4706 files, 6.8 MB |
| `commands/` | The `-help` output of each command | 187 files |

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

### Review settings

These are not environment variables. They live in `~/.config/foamagent/config.yaml`, because a command line with its own argument list does not fit in one:

```yaml
review:
  command: [claude, -p]                                    # the harness session to start
  allowed_tools: [Read, Grep, Glob, WebSearch, WebFetch]   # read-only, plus the web
  allow_tools_flag: --allowed-tools                        # how that list is passed
  prompt_separator: "--"                                   # ends option parsing
  timeout_seconds: 1800
  sandbox:
    runtime: docker            # 'none' takes the review's ability to calculate away
    image: python:3.12-slim    # fetched once, on first use
    timeout_seconds: 300       # per script, not per review
```

Every key has the default shown, so the file is only needed to change something — to point at a different harness, or to take the web away. Tools that could modify the case (`Bash`, `Write`, `Edit` and their like) are dropped from the list with a warning whatever the file says: a reviewer that can rewrite the case is not a reviewer. The same applies to tools served by other MCP servers: only Foam-Agent's own `run_script` survives, and the review session is started with `--strict-mcp-config` so it sees that server and nothing else you have configured.

The container's memory, CPU and process limits are not settings. A limit that a file can raise is a limit that gets raised instead of the script being fixed.

`FOAMAGENT_CONFIG_HOME` moves the whole directory (settings and templates); `FOAMAGENT_CONFIG_FILE` and `FOAMAGENT_TEMPLATES_DIR` move one of them.

### About the OpenFOAM fork

The fork (Foundation or ESI) and the version are measured, so normally there is nothing to set. The result appears in what `describe_environment` returns and in the name of the index directory (`foundation-10`, `esi-v2406`, and so on).

Setting `FOAMAGENT_OPENFOAM_FORK` overrides the measurement. Use it when you want them to disagree on purpose, such as getting Foundation-style output on a machine that has ESI installed. A disagreement between the setting and the measurement is logged as a warning.

### Other

| Environment variable | Purpose | Default |
|---|---|---|
| `FOAMAGENT_LOG_LEVEL` | Log verbosity. Logs go to stderr; stdout carries only MCP traffic | `INFO` |
| `FOAMAGENT_ROOT` | Where `runs/` is looked up | the repository root |

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
| The report says no independent check was made | The review command is not on this machine's PATH. Install the harness CLI, or point `review.command` in `~/.config/foamagent/config.yaml` at one you have |
| The review says it could not run a calculation | Its scripts run in a container and Docker is not available. Install Docker, or accept the reduced review — it will say which checks it could not make |

## Running in a container

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

## Development

```bash
uv sync                          # core and dev tools
uv run pytest -m "not integration" -q
uv run ruff check .
```

The unit tests need no API credentials, no network, no Docker and no model. No test starts a review session: what they check is the command line one would be started with, the round limits, and the documents that land in the case directory. That constraint is what keeps `import foamagent` free of side effects, so please keep new unit tests within it. Tests that need a real OpenFOAM are marked `integration` and are excluded by default.

The end-to-end regression is `scripts/manual/e2e_cavity.sh`, which drives a real harness session against a real OpenFOAM. It is run by hand at each phase's acceptance check, not in CI.

CI runs lint, the unit tests on Python 3.10 and 3.12, and a wheel build on every push and pull request.

The extras are below. The core install deliberately leaves out anything heavy.

| Extra | Provides | Needed when |
|---|---|---|
| `viz` | PyVista | Rendering results |
| `web` | FastAPI, uvicorn | The `app.py` web UI |
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
