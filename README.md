# Foam-Agent    <a href="https://arxiv.org/abs/2505.04997"><img src="https://img.shields.io/badge/arXiv-2505.04997-b31b1b.svg" alt="Paper"></a>

<p align="center">
  <b>English</b> | <a href="README_ja.md">日本語</a>
</p>

Foam-Agent lets an AI agent do CFD work in OpenFOAM. It gives a harness — Claude Code or Hermes Agent, the two this fork supports — an OpenFOAM environment and a tutorial library, as an MCP server. You ask for a simulation in chat, and the agent agrees the conditions with you, creates the case, runs it, repairs what fails, and has the work reviewed before reporting back.

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
| A harness | Claude Code (`npm install -g @anthropic-ai/claude-code`) or Hermes Agent (`curl -fsSL https://hermes-agent.nousresearch.com/install.sh \| bash`) — see [Harness support](#harness-support) |

### Harness support

**Foam-Agent supports two harnesses: Claude Code and Hermes Agent.** `foamagent install` only writes configuration for these two; no other client is offered or tested.

**Claude Code** is verified end to end — the installer, the review path (`review.command`'s default, `claude -p`, is its spelling), and the manual regression in `scripts/manual/e2e_cavity.sh` have all been exercised with it.

**Hermes Agent** is verified both as the worker and as the review command. As the worker: a real case has been run through its MCP connection and the `openfoam-cfd` skill, start to finish. As the review command: the `hermes-agent` profile (`review.harness: hermes-agent`) has passed `foamagent doctor --review`'s two checks for real. `foamagent install hermes-agent` sets `review.harness` to `hermes-agent` itself, so no separate step is needed to use it as the review command too.

Installing Hermes Agent itself is `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`. **Note:** a later step in that installer downloads a Chromium build and has been observed to hang indefinitely on a slow or filtered network, even though `hermes` itself is already usable by that point. Neither the worker's use of Hermes nor the review needs the `browser` toolset, so it is safe to interrupt just that download if it hangs.

Every other client that speaks MCP — Codex CLI, Cursor, Cline, Kilo Code, and the rest — is out of scope for this fork. `foamagent install` does not offer them, and none of the review or regression path has been exercised against them.

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
foamagent config set openfoam.runtime docker
```

That image is the default, so `openfoam.runtime` is the only setting required. It is written to `~/.config/foamagent/config.yaml` and stays set, so a new terminal needs nothing repeated. For another image, set the image name and the path to the bashrc inside it as well. The images verified so far are below.

| Image | OpenFOAM detected | bashrc inside the image |
|---|---|---|
| `openfoam/openfoam10-paraview56` | foundation 10, 187 commands | `/opt/openfoam10/etc/bashrc` |
| `opencfd/openfoam-default:2406` | esi v2406, 287 commands | `/usr/lib/openfoam/openfoam2406/etc/bashrc` |

For the ESI image:

```bash
docker pull opencfd/openfoam-default:2406
foamagent config set openfoam.runtime docker
foamagent config set openfoam.image opencfd/openfoam-default:2406
foamagent config set openfoam.bashrc /usr/lib/openfoam/openfoam2406/etc/bashrc
```

`foamagent config` asks all of this as questions instead, and `foamagent config show` prints what is in effect. The matching environment variables (`FOAMAGENT_OPENFOAM_RUNTIME` and its siblings) still work and still win over the file; see [Configuration](#configuration).

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

The command also accepts `hermes-agent` in place of `claude-code`. See [Harness support](#harness-support) for what is and is not verified on that path, and [Wiring Hermes Agent up to the MCP server](#wiring-hermes-agent-up-to-the-mcp-server) right below for the one manual step it needs that Claude Code does not.

### Wiring Hermes Agent up to the MCP server

Unlike Claude Code's `.mcp.json`, Hermes has no per-project MCP config — only the global `~/.hermes/config.yaml`. So `foamagent install hermes-agent` writes `foamagent-hermes.yaml` in the working directory instead, and you merge it into `~/.hermes/config.yaml` by hand, once:

1. Open Hermes's config: `hermes config edit` (or edit `~/.hermes/config.yaml` directly).
2. If it has no top-level `mcp_servers:` key yet, paste `foamagent-hermes.yaml`'s entire contents in.
3. If it already has one (from another MCP server you use with Hermes), add `foamagent-hermes.yaml`'s `foamagent:` entry as a new line under the *existing* `mcp_servers:` key instead — **do not** paste a second `mcp_servers:` block. YAML does not merge two top-level keys with the same name; the second one silently wins, and whatever was registered under the first one is gone.

For example, `foamagent-hermes.yaml` looks like this (yours will have a different `command` path):

```yaml
mcp_servers:
  foamagent:
    command: "/home/you/.local/bin/foamagent-mcp"
    args:
      - "--transport"
      - "stdio"
    timeout: 1800
    enabled: true
```

If `~/.hermes/config.yaml` already has, say, a `some-other-server` entry, the result after merging should look like this — `foamagent` added as a *sibling* of `some-other-server`, both still under one `mcp_servers:` key:

```yaml
mcp_servers:
  some-other-server:
    command: ...
  foamagent:
    command: "/home/you/.local/bin/foamagent-mcp"
    args:
      - "--transport"
      - "stdio"
    timeout: 1800
    enabled: true
```

Confirm it worked with `hermes mcp list` — `foamagent` should show up `enabled`.

### Bringing your own skills

Set `skills.dir` (or `FOAMAGENT_SKILLS_DIR`) to a directory before running `foamagent install`, and it copies your own skills alongside the bundled one. A skill is a directory directly under `skills.dir` containing a `SKILL.md`; anything else there is ignored.

```bash
foamagent config set skills.dir ~/my-openfoam-skills
foamagent install claude-code
```

For Claude Code, each one lands at `.claude/skills/<name>/`, the same place the bundled `openfoam-cfd` skill goes. For Hermes Agent, each lands at `~/.hermes/skills/cfd/<name>/` — global, like the bundled skill, since Hermes has no project-local skill directory. Either way, a skill named `openfoam-cfd` replaces the bundled one rather than sitting beside it.

There is no compatibility check between a skill and the Foam-Agent version installed; note the version it was written against in the skill's frontmatter instead.

### 4. Build the tutorial catalogue

```bash
foamagent index build
```

This reads the tutorials of the installed OpenFOAM and writes the material the agent consults. Run it once per OpenFOAM installation. It took 6 seconds for the 248 cases of Foundation v10, and 13 seconds for the 578 cases of ESI v2406.

The output goes to `~/.cache/foamagent/indexes/<fork>-<version>/`. That is outside the repository, so `git pull` or a reinstall will not remove it.

### 5. Confirm the setup

```bash
foamagent doctor
```

This checks the things that otherwise fail later, inside the harness: whether OpenFOAM can be reached, whether the catalogue has been built for it, whether the command that runs an independent review is installed, whether a review could compute, and whether the `.mcp.json` here still agrees with your settings. It changes nothing, and each failure comes with the command that fixes it.

```
  [ok  ] OpenFOAM: foundation 10, 187 applications (docker runtime)
  [ok  ] Reference library: /home/you/.cache/foamagent/indexes/foundation-10
  [ok  ] Review command: /home/you/.local/bin/claude; reviewer on claude-sonnet-5, judge on claude-sonnet-5
  [ok  ] Review sandbox: docker, image python:3.12-slim, 300s per script
  [ok  ] Harness configuration: /home/you/cfd/.mcp.json
```

Add `--review` to also start the configured review command for real — against scratch directories nothing depends on — and check that it follows an instruction and that it can use the sandbox. This is the fastest way to find out whether a harness other than Claude Code actually works as `review.command`: it takes tens of seconds rather than the ten-plus minutes an actual review does, and it fails the same way an actual review would if a flag is spelled wrong for that harness.

```bash
foamagent doctor --review
```

Then start Claude Code in the working directory.

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
3. `request_review` starts a check of that specification against your words, before anything is built, and `review_status` is polled until it is done
4. It picks a close tutorial from `catalog.md` and reads that case's files
5. It writes the case files and checks them with `validate_case` before running
6. It runs with `run_start` and follows progress with `run_status` and `run_tail_log`
7. On failure it classifies the cause with `classify_errors`, edits the files and runs again
8. Once the run completes, `request_review`/`review_status` checks the result, and `request_report`/`report_status` produces what you read

### Where your files end up

Everything a run produces goes into one place — the **case directory** — created under the directory you started the harness in and named after what you asked for.

```
~/cfd/                                 # the directory you started the harness in
├── .mcp.json
├── .claude/skills/openfoam-cfd/SKILL.md
└── cavity/                            # ← the case directory: everything is in here
    ├── 0/  constant/  system/         the OpenFOAM case itself
    ├── Allrun                         the command sequence run_start executes
    ├── log.blockMesh  log.icoFoam     one log per command
    ├── 0.5/  1/  …  10/               the time directories the solver wrote: your results
    ├── visualization.png  cavity.foam written by visualize; open the .foam file in ParaView
    ├── spec.md                        the conditions, with your request quoted verbatim
    ├── review-1.md  response-1.md     the review and the answer to it, one pair per round
    ├── report.md                      what you are shown at the end
    ├── review-work/                   the Python the review computed its numbers with
    └── .foamagent/                    run bookkeeping; nothing you need to open
```

Foam-Agent does not choose that directory — the agent does, from your request, so the name varies with what you asked for. To fix it yourself, say so in the request: *"put the case in /data/cavity"*.

The results are an ordinary OpenFOAM case, so the usual tools work on it unchanged: `paraFoam -case ~/cfd/cavity`, or open `cavity.foam` in ParaView.

The only thing written outside the case directory is the tutorial catalogue from step 4, which lives in `~/.cache/foamagent/indexes/` and is shared by every case.

## How it works

### MCP tools

Foam-Agent exposes the sixteen tools below. Choosing the solver, deciding what goes in the dictionaries, and deciding what to change after a failure are all done by the agent in the harness; the twelve deterministic tools measure, run and check. The last four are the exception, and are described under [Review](#review).

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
| `request_review` | Starts an independent check of the specification, or the finished result, and returns at once |
| `review_status` | Reports the state of a review, returning at once even while it is running |
| `request_report` | Starts the report you are shown and returns at once |
| `report_status` | Reports the state of a report, returning at once even while it is running |

`read_case` and `write_case` refuse paths outside the case directory.

### Review

A case built by one agent and checked by the same agent has been checked by whoever decided it was right. So the check runs somewhere else: `request_review` and `request_report` start a fresh, non-interactive session of the harness you already run — a separate process, with no access to the conversation that produced the case. A review can take tens of minutes, and no MCP client's timeout survives a tool call left open that long, so both tools return an identifier at once; `review_status`/`report_status` are polled (with `wait_seconds`, a few minutes at a time) until the state is `done` — the same shape `run_start`/`run_status` already use for a solver run.

Three roles, then. The agent you talk to (**Worker**) does the CFD: the dialogue, the specification, the case, the run, the fixes. The **Reviewer** reads the case and looks for what is wrong with it. The **Judge** reads the whole exchange and writes your report, ruling on each disputed point rather than splitting the difference.

The Reviewer and the Judge are ordinary, trusted sessions of your harness, told their role by the prompt alone — not sandboxed away from the case by a restricted tool list. An earlier version denied write tools by name and, for a harness with no way to grant read without also granting write, ran the review against a throwaway copy of the case instead of the real one; both broke real tools more often than they caught anything, so neither is done any more. On Claude Code, `--strict-mcp-config` is still a hard boundary, not a prompt-level request: the Reviewer and Judge never see the Worker's own `foamagent` server — the one with `run_start` and the other case-mutating tools — only the read-only `run_script` sandbox described below. Hermes has no per-invocation equivalent of that flag; an earlier version worked around it with a second, isolated Hermes profile that had no MCP servers of its own, but that isolation broke more real tool calls than it caught (see [Harness support](#harness-support)) and was dropped, so on Hermes the Reviewer and Judge do see the Worker's `foamagent` server, the same as every other tool. If that boundary matters to you, run the whole `hermes` process inside a container rather than relying on a second profile.

The exchange is entirely on paper, and the paper stays in the [case directory](#where-your-files-end-up):

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

Every setting has the same four places it can come from, and they win in this order:

| Priority | Where | Set it with |
|---|---|---|
| 1 | An environment variable | `export FOAMAGENT_OPENFOAM_RUNTIME=docker` |
| 2 | The project settings file — `foamagent.yaml` in the working directory or above it, up to a `.git` | `foamagent config set --project openfoam.image ...` |
| 3 | The user settings file — `~/.config/foamagent/config.yaml` | `foamagent config set openfoam.image ...` |
| 4 | The default in the code | — |

```bash
foamagent config                     # asks the questions, writes the answers
foamagent config show                # every setting, its value, and which of the four it came from
foamagent config set review.judge.model claude-opus-5
foamagent config unset openfoam.image   # back to the default
foamagent config edit                # open the file in $EDITOR, comments kept
foamagent config path                # which files are being read
```

The environment stays on top so that anything already written into a `.mcp.json`, a CI job or a script keeps working. That also means a stale `export` beats the file you just edited — `foamagent config show` names the origin of every value, and `foamagent doctor` reports a `.mcp.json` whose baked-in environment disagrees with your settings.

The project file is what makes a setting travel with the work: a directory of cases that needs a particular OpenFOAM image says so in `foamagent.yaml` next to them, rather than in whichever shell happens to start the server.

### How OpenFOAM is run

| Setting | Environment variable | Purpose | Default |
|---|---|---|---|
| `openfoam.runtime` | `FOAMAGENT_OPENFOAM_RUNTIME` | `native` sources the host installation; `docker` runs inside an image | `native` |
| `openfoam.image` | `FOAMAGENT_OPENFOAM_IMAGE` | The image the `docker` runtime uses | `openfoam/openfoam10-paraview56` |
| `openfoam.bashrc` | `FOAMAGENT_OPENFOAM_BASHRC` | Path to the OpenFOAM bashrc inside that image | `/opt/openfoam10/etc/bashrc` |
| `openfoam.fork` | `FOAMAGENT_OPENFOAM_FORK` | Which fork's conventions to generate for | whichever is installed |

The `docker` runtime mounts the case directory at the same absolute path inside the container, so the paths in the logs mean the same thing on both sides. It passes your UID and GID, so the generated files are not left owned by root.

### Index and catalogue

| Setting | Environment variable | Purpose | Default |
|---|---|---|---|
| `index.dir` | `FOAMAGENT_INDEX_DIR` | Where built indexes are kept | `~/.cache/foamagent/indexes` |
| `index.max_file_kb` | `FOAMAGENT_INDEX_MAX_FILE_KB` | Tutorial files larger than this are recorded but their contents are not stored | `100` |
| `skills.dir` | `FOAMAGENT_SKILLS_DIR` | Where `foamagent install` reads your own skills from; see [Bringing your own skills](#bringing-your-own-skills) | unset |

`foamagent index list` shows what has been built.

### Review settings

These have no environment variables, because a command line with its own argument list does not fit in one. They live in the same settings file as everything else:

```yaml
review:
  harness: claude-code                                     # named bundle of the 6 keys below
  command: [claude, -p]                                    # the harness session to start
  model: claude-sonnet-5                                   # the model every role uses
  reviewer:
    model: claude-sonnet-5                                 # the model that checks the case
  judge:
    model:                                                 # unset by default: inherits review.model above (so claude-sonnet-5); set to claude-opus-5 to give the ruling a stronger model than the checking
  model_flag: --model                                      # how that name is passed
  skip_permissions_flag: --dangerously-skip-permissions    # how full tool access is granted
  prompt_separator: "--"                                   # ends option parsing
  timeout_seconds: 1800
  mode: full                                               # full / spec / off
  sandbox:
    runtime: docker            # 'none' takes the review's ability to calculate away
    image: python:3.12-slim    # fetched once, on first use
    timeout_seconds: 300       # per script, not per review
```

The model is written into the settings rather than left to the harness's own default because you should not have to guess what checked your result: the model is named on the command line, so the line the server logs when it starts a review says which one ran. Sonnet is the default — a review reads the case, does arithmetic and compares against published numbers — and any model name your harness accepts can go there instead. Set `model: ''` for a command that takes no `--model`; the harness then chooses, as it did before this setting existed.

`review.mode` says how much gets checked. `full`, the default, reviews the specification and the result and writes the report. `spec` keeps only the first check — the cheap one that catches a case answering the wrong question — and `off` runs none of them. A stage that is switched off returns a document saying so, exactly as an unconfigured machine does, so a case run this way is never mistaken for a checked one. The reason to reach for anything but `full` is work where the check is not the point: a benchmark, or a case being run for the twentieth time. Write it quoted (`mode: 'off'`) if you edit the file by hand — YAML reads a bare `off` as a boolean, which Foam-Agent then has to guess at.

`review.harness` picks a named bundle of the flag-shaped settings below it (`command` through `strict_mcp_config_flag`) instead of you rewriting each one by hand. Two profiles are shipped: `claude-code` (the default) and `hermes-agent` — both have had `foamagent doctor --review` run against them for real (see [Harness support](#harness-support)); an unknown name falls back to `claude-code` with a warning. Any individual key you do set still overrides what the profile says, so `harness: claude-code` with your own `model_flag` works as you would expect. Adding a profile for another harness belongs after `foamagent doctor --review` has actually been run against it — a flag spelling nobody has tried is a guess with a name on it. `hermes-agent` needs no separate setup: `foamagent install hermes-agent` sets `review.harness` to `hermes-agent` itself.

`review.model` sets all of it. The two roles can be named separately because they are not the same job: the reviewer reads and computes, and the judge rules on the exchange and writes what you are shown. `review.reviewer.model` and `review.judge.model` override the shared one for their own role, and `foamagent config show` prints which model each role will actually run on. Nothing else about a review depends on the role — the tool access and the time limit are the same for both, because what a review may do to a case must not depend on which one asked for it.

Every key has the default shown, so the file is only needed to change something — to point at a different harness, or to take the web away entirely by pointing `command` at a review harness with no network. `skip_permissions_flag` is what lets a headless (`-p`) session use any tool at all — without it Claude Code denies every tool call nobody pre-approved rather than hanging on a prompt nobody can answer, so the reviewer would be unable to even read the case. Set it to `''` for a harness that grants full access without one; `hermes-agent`'s own profile already does. On Claude Code, the Worker's own `foamagent` MCP server — the one with `run_start` and the other case-mutating tools — is kept away from the Reviewer and Judge by starting the review session with `--strict-mcp-config`, so only Foam-Agent's own `run_script` sandbox is visible to it. Hermes has no per-invocation equivalent, so on `hermes-agent` the Reviewer and Judge do see the Worker's `foamagent` server (see [Review](#review) above).

The container's memory, CPU and process limits are not settings. A limit that a file can raise is a limit that gets raised instead of the script being fixed.

### About the OpenFOAM fork

The fork (Foundation or ESI) and the version are measured, so normally there is nothing to set. The result appears in what `describe_environment` returns and in the name of the index directory (`foundation-10`, `esi-v2406`, and so on).

Setting `openfoam.fork` (or `FOAMAGENT_OPENFOAM_FORK`) overrides the measurement. Use it when you want them to disagree on purpose, such as getting Foundation-style output on a machine that has ESI installed. A disagreement between the setting and the measurement is logged as a warning.

### Other

| Environment variable | Purpose | Default |
|---|---|---|
| `FOAMAGENT_LOG_LEVEL` | Log verbosity. Logs go to stderr; stdout carries only MCP traffic | `INFO` |
| `FOAMAGENT_ROOT` | Where `runs/` is looked up. Left over from the upstream pipeline; cases do not go there — see [Where your files end up](#where-your-files-end-up) | the repository root |
| `FOAMAGENT_CONFIG_HOME` | Moves the settings file and the templates together | `~/.config/foamagent` |
| `FOAMAGENT_CONFIG_FILE` / `FOAMAGENT_TEMPLATES_DIR` | Moves one of them | — |
| `FOAMAGENT_PROJECT_CONFIG` | Names the project settings file outright. Naming one that does not exist means there is none | found by searching upward |

These four have no entry in the settings file, for the reason that they are how the settings file is found.

The number of seconds before a solver run is cut off is not a setting either: it is the `timeout` argument of `run_start`, which defaults to 3600 seconds.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `foamagent: command not found` | After `uv tool install`, check that `~/.local/bin` is on your PATH (`uv tool update-shell` sets it up). After `uv sync`, run commands as `uv run foamagent ...` |
| The wrong `foamagent` starts | Run `which foamagent` to see which one it is. If an older Foam-Agent is installed in another environment such as conda, that one can take precedence |
| Anything at all is not working | Run `foamagent doctor`. It names what is wrong and the command that fixes it |
| `No OpenFOAM environment could be detected` | For a host OpenFOAM, source the bashrc and check that `echo $WM_PROJECT_DIR` prints something. For a container, check that `foamagent config show` reports `openfoam.runtime docker` |
| A setting you changed has no effect | `foamagent config show` prints where each value came from. An environment variable left over in that shell beats the file |
| `foamagent` is missing from `/mcp` | Check that you started in the directory holding `.mcp.json`. If you declined the trust prompt at startup, restart `claude` and allow it |
| `library` comes back empty from `describe_environment` | `foamagent index build` has not been run yet. It is needed once per OpenFOAM installation |
| The agent reaches for a solver that does not exist | Nudge it to call `describe_environment` first. The skill says so as a step, but the step gets skipped as a conversation grows long |
| A run never finishes | `run_status` reports the state and `run_stop` ends it. A run that hits `run_start`'s `timeout` (3600 seconds by default) is cut off automatically |
| Visualization fails | It needs the `viz` extra (PyVista). Reinstall from the repository directory with `uv tool install --force --from '.[viz]' foamagent` |
| The report says no independent check was made | The review command is not on this machine's PATH. Install the harness CLI, or run `foamagent config set review.command '[your-cli, -p]'` |
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
