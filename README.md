# Foam-Agent    <a href="https://arxiv.org/abs/2505.04997"><img src="https://img.shields.io/badge/arXiv-2505.04997-b31b1b.svg" alt="Paper"></a>

<p align="center">
  <b>English</b> | <a href="README_ja.md">日本語</a>
</p>

Foam-Agent lets an AI agent do CFD work in OpenFOAM. It wires an OpenFOAM environment and tutorial library into your harness (Claude Code or Hermes Agent) as an MCP server. Ask for a simulation in chat; the agent agrees the conditions with you, builds the case, runs it, fixes what fails, and has the result reviewed independently before reporting back. The reasoning happens in the harness's own model, so Foam-Agent needs no API key of its own.

This is a fork of [csml-rpi/Foam-Agent](https://github.com/csml-rpi/Foam-Agent): harness-only (the upstream `direct_api` path is removed), grounded in the OpenFOAM you actually have, and reviewed by a session independent of whoever built the case.

## Quick start

1. **Install.**
   ```bash
   git clone https://github.com/jumpcfd/Foam-Agent.git && cd Foam-Agent
   uv tool install --from . foamagent   # use '.[viz]' instead of '.' to also get visualize
   ```
   Puts `foamagent` on your PATH via `~/.local/bin` (`uv tool update-shell` if that's not on PATH yet).
2. **Make OpenFOAM available.** Host install: `source /opt/openfoam10/etc/bashrc`. No host install:
   ```bash
   docker pull openfoam/openfoam10-paraview56
   ```
3. **Set up a config.**
   ```bash
   foamagent config
   ```
4. **Set up a project.**
   ```bash
   mkdir ~/cfd && cd ~/cfd
   foamagent init claude-code   # or: foamagent init hermes-agent
   ```
   Claude Code: writes `.mcp.json` and `.claude/skills/openfoam-cfd/SKILL.md` in this directory. Hermes Agent: sets up two dedicated Hermes profiles instead of touching your own — see [Hermes Agent setup](#hermes-agent-setup).
5. **Build the tutorial catalogue** once per OpenFOAM install: `foamagent index build`.
6. **Check it.** `foamagent doctor` reports what's wrong and the command that fixes it; add `--review` to also test-fire the review command against a scratch case.
7. **Start the harness** in `~/cfd` (`claude` or `foamhermes`) and confirm `foamagent` shows as connected and `/openfoam-cfd` is offered.
8. **Ask for something**, in English or Japanese: `Simulate lid-driven cavity flow at Re=1000`. The agent asks about anything left open, writes `spec.md`, builds the case from the closest tutorial, runs it, repairs failures itself, and has the result reviewed before reporting back.

### Where your files end up

Everything lands in one **case directory**, named from your request, under wherever you started the harness:

```
~/cfd/cavity/
├── 0/  constant/  system/          the OpenFOAM case
├── Allrun, log.*                   the run command and one log per step
├── spec.md, review-N.md, report.md the paper trail (see Review, below)
└── .foamagent/                     bookkeeping
```

Say "put the case in /data/cavity" to choose the location yourself. Results are an ordinary OpenFOAM case — `paraFoam` and ParaView work unchanged.

## Key features

| Feature | What it means |
|---|---|
| Runs in the AI tool you already use | `foamagent init claude-code` writes the MCP config and a skill — one command |
| Grounded in your OpenFOAM | `foamagent index build` measures your install and writes the catalogue the agent reads |
| Reviewed, not just run | A separate session checks the spec before building and the result after, then writes your report (see **How it works**) |
| Checks that need no reasoning | `validate_case` catches missing dictionaries, uninstalled solvers, and patch-name mismatches before a run |
| Tells ESI and Foundation apart | Detects which is installed and hands the agent the naming differences between them |

## Requirements

| Item | Notes |
|---|---|
| OpenFOAM | Host install or a container image. Verified on Foundation v10 |
| [uv](https://docs.astral.sh/uv/) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` — also fetches a compatible Python |
| A harness | Claude Code or Hermes Agent — see below |

| Harness | As worker | As review command |
|---|---|---|
| Claude Code (`npm install -g @anthropic-ai/claude-code`) | Verified end to end | Verified — `claude -p`, the default |
| Hermes Agent (`curl -fsSL https://hermes-agent.nousresearch.com/install.sh \| bash`) | Verified end to end, via a dedicated `foamhermes` profile | Verified — a dedicated `foamhermes-review` profile, written by `foamagent init hermes-agent` |

Every other MCP client (Codex CLI, Cursor, Cline, ...) is out of scope; `foamagent init` does not configure them. Hermes's installer can hang downloading Chromium on a slow network — safe to kill, neither the worker nor review needs it.

## Hermes Agent setup

Hermes has no per-project MCP config, and its hooks/plugins are configured per-profile, not per-project — writing them into your own default profile would fire them on every Hermes session, CFD or not. `foamagent init hermes-agent` instead creates two dedicated profiles and configures both automatically, no manual merge step: **`foamhermes`** (the worker — the MCP server, the skill, and a plugin that shows the task ledger and enforces `task_done`) and **`foamhermes-review`** (review — no MCP server, no skills, isolated from the worker and from your own). Neither touches your own default profile.

Run `foamhermes setup` (and `foamhermes-review setup`) once each to give them a model and API key — a freshly created profile starts with none of its own. Then do CFD work with `foamhermes chat` (installed on PATH by `hermes profile create`) instead of plain `hermes`; `request_review` already points at `foamhermes-review` for you. See `docs/hermes-profiles-notes.md` for how the isolation actually works and what was confirmed against a live install.

## How it works

**MCP tools.** `describe_environment`, `search_tutorials`, `validate_case` and `visualize` measure and check; running a case, editing files and reading logs are the harness's own native tools. `request_review`/`review_status` and `request_report`/`report_status` drive review below — asynchronously, since a review can take tens of minutes.

**Review.** Three roles. The **Worker** (your session) does the CFD. The **Reviewer** is a fresh, non-interactive harness session with no view of your conversation, and checks the case. The **Judge** reads the whole exchange and writes your report, ruling on each disputed point. Every document lands in the case directory (`spec.md`, `review-N.md`, `response-N.md`, `report.md`), and the Reviewer can run Python against the case — read-only, in a throwaway container — so a claim can be checked afterwards. No review command configured, or `review.mode: off`, and the tools say so plainly rather than staying silent about it; the case still runs.

**The skill and your knowledge.** `SKILL.md` (how to drive the tools) is part of Foam-Agent itself, so `init`/`sync` always overwrite it unconditionally. The OpenFOAM know-how it reads — how to classify a case, recurring failure signatures — is a separate concern: plain Markdown at `~/.config/foamagent/knowledge/`, seeded once and never touched again on its own. Edit it freely, or add your own `.md` file; `foamagent sync` is the only way to pull in an update to the built-in defaults, and it asks before overwriting anything you've changed.

**The reference library.** `foamagent index build` writes `catalog.md`, `by-solver.md`, tutorial `cases/`, and command `--help` text to `~/.cache/foamagent/indexes/`, shared by every case you build afterward.

**Extending it.** Drop another `SKILL.md` at `.claude/skills/<name>/` (Hermes: `~/.hermes/profiles/foamhermes/skills/cfd/<name>/`) — the harness discovers it on its own, no Foam-Agent step needed. Set `paraview.dir` to a [paraview_mcp](https://github.com/jumpcfd/paraview_mcp) checkout to give Worker, Reviewer and Judge a live ParaView to probe instead of guessing from text.

## Configuration

Settings come from, in priority order: an environment variable (`FOAMAGENT_*`) > a project `foamagent.yaml` > `~/.config/foamagent/config.yaml` > the code default. `foamagent config` asks interactively; `show`/`set`/`unset`/`edit`/`path` manage the file directly.

| Setting | Purpose | Default |
|---|---|---|
| `openfoam.runtime` | `native` (host) or `docker` | `native` |
| `openfoam.image` / `openfoam.bashrc` | Image and its bashrc path, for `docker` | `openfoam/openfoam10-paraview56` |
| `openfoam.fork` | Override fork detection | measured |
| `index.dir` | Where built indexes are kept | `~/.cache/foamagent/indexes` |
| `paraview.dir` | A paraview_mcp checkout (see **Extending it**, above) | unset |
| `review.mode` | `full` / `spec` (spec check only) / `off` | `full` |
| `review.command` | The whole review command line, model and permission flags included | `claude -p --model claude-sonnet-5 --dangerously-skip-permissions` |

## Troubleshooting

Run `foamagent doctor` first — it names what's wrong and the command that fixes it. A few common cases:

| Symptom | Fix |
|---|---|
| `foamagent: command not found` | `~/.local/bin` isn't on PATH (`uv tool update-shell`), or you're on `uv sync` — use `uv run foamagent ...` |
| `foamagent` missing from `/mcp` | Start the harness in the directory holding `.mcp.json`; allow the trust prompt on first launch |
| Stuck at `⏸ Pending approval` (non-interactive) | Write `.claude/settings.local.json`: `{"enabledMcpjsonServers": ["foamagent"]}` |
| Report says no independent check was made | Review command isn't on PATH, or `review.mode` is `off` |

## Running in a container

```bash
docker build -f docker/Dockerfile -t foamagent:latest .
docker run -it -e FOAMAGENT_SKIP_UPDATE=1 foamagent:latest
```

Fetches the latest code from GitHub on every start unless `FOAMAGENT_SKIP_UPDATE=1` pins it to what was baked in at build time.

## Development

```bash
uv sync
uv run pytest -m "not integration" -q
uv run ruff check .
```

Unit tests need no API credentials, network, Docker, or model. `scripts/manual/e2e_cavity.sh` is the real end-to-end regression, against a real harness and OpenFOAM — run by hand, not in CI. The `viz` extra pulls in PyVista, for `visualize`.

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
