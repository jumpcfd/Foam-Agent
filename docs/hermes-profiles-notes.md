# Notes: the two Hermes profiles (`foamhermes` / `foamhermes-review`)

This is the debugging history and rationale behind `install_hermes_agent()`
(`src/foamagent/harness/__init__.py`) and the Hermes plugin it installs
(`src/foamagent/harness/hermes_plugin/`). The README only documents how to run
the setup; this document is for anyone changing that setup, hand-rolling it, or
debugging a Hermes install that is not behaving as expected. Everything below
was confirmed against a live Hermes Agent install (v0.20.6) before being
written down here, mostly by reading `hermes_cli/plugins.py` directly (fetched
via `gh api` from `NousResearch/hermes-agent`) rather than trusting the docs
site's own summaries, which turned out to be thinner than the real API in
places that mattered.

## Why two profiles, and why this is not the profile dropped in `44a6487`

An earlier design (`foamagent-review`, added in `328b54f`/`f223ce4`, dropped in
`44a6487` on 2026-08-20) used a second Hermes profile to isolate the
*reviewer's own tool access* -- narrowing `terminal`/`file`/`browser` toolsets,
routing `terminal.backend` through Docker. That broke more real tool calls
than it caught (see git history for the pre-removal commits: routing through
Docker broke `file` reads on WSL2; merely setting `terminal.backend` at all,
to any value, silently stopped Hermes exposing `file`/`terminal` to the model
at all; the `--toolsets` flag broke reading even with `file` in the list) and
was eventually abandoned outright: "the isolated profile still needed
terminal execution permission granted anyway, defeating the point of
splitting it from the worker's own profile."

This design's motivation is different, and does not repeat that mistake:

1. **Hooks and plugins are configured in a profile's own `config.yaml`, which
   is global to every session run under that profile** -- unlike Claude
   Code's `.claude/settings.json`, which is scoped to the project directory.
   Writing the task-ledger plugin into the user's own default profile would
   fire it on every Hermes session, CFD or not. `foamhermes` exists purely to
   contain that.
2. **`foamhermes-review` should not see the user's own skills or the
   worker's own `foamagent` MCP server** (`run_start`/`run_stop` and the
   rest), the same isolation Claude Code's reviewer gets for free from
   `--strict-mcp-config`, which Hermes has no per-invocation equivalent of.

Neither of these needs restricting what `foamhermes`/`foamhermes-review`
themselves are *allowed to do* with their own built-in tools. This design
never sets `terminal.backend`, never passes `--toolsets`, and never calls
`hermes tools disable` -- the exact three things that broke real usage last
time. `foamhermes-review` gets isolation by simply having nothing of ours in
it (`--no-skills` at creation, no MCP server, no plugin), not by having its
own tools narrowed.

## Confirmed mechanism

- **`hermes profile create <name> [--no-skills]`** creates
  `$HERMES_HOME/profiles/<name>/` (same layout as `$HERMES_HOME` itself:
  `config.yaml` written lazily on first use, `skills/`, `plugins/`, `.env`,
  `SOUL.md`, ...) and, unprompted, a wrapper script on `PATH` (confirmed at
  `~/.local/bin/<name>`, next to wherever the `hermes` binary itself lives)
  that is exactly `exec <hermes> -p <name> "$@"`. Re-running it on an
  existing profile exits 1 with `Error: Profile '<name>' already exists at
  ...` **printed to stdout, not stderr** -- confirmed the hard way: an
  earlier version of `_ensure_hermes_profile` checked stderr only and
  mis-reported an already-existing profile as a failed create.
- **`hermes -p <name> ...`** runs any subcommand against a specific profile
  without touching the sticky default (`hermes profile use`). It is not
  listed by `hermes --help` (parsed before the main argparse setup) but is
  exactly what the wrapper script above does, and works for `config`,
  `plugins`, `mcp`, and `-z` alike.
- **Profile isolation is real and mechanism-level, not a convention.**
  `hermes_cli/plugins.py`'s own comment on `_plugin_home_key()`: "A long-lived
  process can temporarily switch Hermes home ... while serving another
  profile ... A process-wide single-slot cache leaks one profile's
  plugin/context-engine state into another." User plugins are discovered
  from `get_hermes_home() / "plugins"`, and `get_hermes_home()` resolves to
  the active profile's own home when `-p <name>` is in effect. Confirmed
  directly: a plugin dropped under `foamhermes/plugins/<name>/` shows up in
  `hermes -p foamhermes plugins list` and is absent from plain
  `hermes plugins list` (the default profile), both before and after
  enabling it; the same holds for an `mcp_servers` entry written into
  `foamhermes/config.yaml` and `hermes mcp list` / `hermes -p foamhermes mcp
  list`.
- **`hermes mcp add` still has no non-interactive flag** ("Save config
  anyway (you can test later)? [y/N]" on a failed connection, confirmed with
  stdin redirected from `/dev/null` -- it does not hang, it just defaults to
  not saving). Writing `mcp_servers` directly into the profile's
  `config.yaml` is the only non-interactive path, same conclusion as the
  design this replaced. `plugins.enabled` can be written directly the same
  way -- `hermes plugins enable <name>` interactively, additionally, asks
  "Allow this plugin to replace built-in tools?" (a *different* capability,
  `allow_tool_override`, that this plugin does not need and does not
  request); writing `plugins.enabled: [<name>]` straight into `config.yaml`
  skips that prompt entirely and the plugin loads and fires correctly
  either way -- confirmed.
- **A fresh profile has no credentials of its own** and does not usefully
  inherit any (`HTTP 400: No models provided` until a model/provider is
  configured). `foamhermes setup` / `foamhermes-review setup` is a step the
  user runs once per profile; `install_hermes_agent()` deliberately does not
  touch model, provider or credentials, same rule as the design this
  replaces.
- **No hard permission wall was hit in testing**, with or without `--yolo`,
  for ordinary file/terminal use on a freshly created profile -- the
  `--yolo` flag (skip all dangerous-command approval prompts) exists
  specifically for headless use and is what `review.command` sets for
  `foamhermes-review`, matching Claude Code's own
  `--dangerously-skip-permissions` on `DEFAULT_COMMAND`. This is *not* an
  exhaustive adversarial test of Hermes's own approval gate for a genuinely
  dangerous command; if a real review session ever does hang on one despite
  `--yolo`, that is the next thing to investigate here.

## The three things the plugin registers, and why each is shaped the way it is

`src/foamagent/harness/hermes_plugin/__init__.py` runs inside Hermes's own
Python process (its own venv, not foamagent's -- `import foamagent.tasks`
would fail), so it talks to `foamagent tasks` as a subprocess.

- **`register_system_prompt_section("foamagent-tasks", callable)`** --
  `plugins.py`'s own docstring: "frozen into each new session prompt." This
  is *not* a hook that re-fires on context compaction (no such CLI-facing
  event exists -- `VALID_HOOKS` in `plugins.py` has no `session:compress` or
  equivalent; that only exists as a Gateway Hook, a separate Python-handler
  mechanism this design does not use). It does not need one: a system-prompt
  section is not part of the conversation history a compaction summarises,
  so once rendered it survives a compaction that would erase a
  hook-injected message. Confirmed directly: asked a live `foamhermes`
  session what its system prompt said about foamagent tasks, and it echoed
  the real `foamagent tasks status` output verbatim, including the real
  repo path, branch, and task ledger contents of a scratch repo set up for
  the test. Trade-off, accepted: the rendered text is fixed at session
  start, so a `task_done` mid-session does not update it -- no worse than
  Claude Code's own SessionStart, which only re-fires at three points
  (startup/resume/compact) rather than on every ledger change either.
- **`register_hook("pre_verify", callback)`** -- `VALID_HOOKS`'s own comment
  in `plugins.py`, verbatim: "The Claude-Code Stop shape
  `{"decision": "block", "reason": "..."}` (block the stop == keep going) is
  accepted too." `foamagent tasks stop-check` already prints exactly that
  shape, so the callback is a subprocess call and a `json.loads`, nothing
  more -- no new CLI flag needed. Bounded by `agent.max_verify_nudges`
  (default 3), Hermes's own equivalent of Claude Code's `stop_hook_active`
  single-shot guard. Confirmed directly: asked a live session to create a
  file and declare itself done, with an open task and uncommitted changes in
  the scratch repo; it got nudged, investigated, and correctly reported the
  task as still open with the real task id, path and uncommitted-change
  count from `stop-check`'s real output -- instead of declaring victory.
  **Pitfall found and fixed while confirming this**: the subprocess call
  must pass `stdin=subprocess.DEVNULL`. `foamagent tasks stop-check` reads
  stdin when it is not a tty (Claude Code's Stop hook always pipes it real
  JSON there); left unredirected, the child inherits Hermes's own stdin,
  which is open but silent in this context, and `json.load(sys.stdin)`
  blocks until the subprocess timeout. Reproduced directly (a bare
  `foamagent tasks stop-check` run from an interactive-looking-but-not-tty
  shell hung for the full 2-minute test timeout); `stdin=subprocess.DEVNULL`
  makes the read hit EOF immediately, `json.JSONDecodeError` is caught, and
  the command proceeds as if no `stop_hook_active` flag were set (correct,
  since Hermes has no such flag to forward -- its own `max_verify_nudges`
  cap is what prevents an infinite nudge loop instead).
- **`register_hook("pre_tool_call", callback)`** -- returns
  `{"action": "block", "message": "..."}` when `tool_name == "terminal"` and
  the command's shlex-tokenised form contains both `"git"` and `"commit"` as
  separate tokens. Confirmed directly: a live session told to run
  `git commit -m test` in a repo with a staged file got the block message
  back verbatim and made no commit (`git log`/`git status` checked
  afterward). This is a token match rather than a fixed-prefix match, so it
  also catches `git -C x commit`, which Claude Code's own
  `Bash(git commit:*)` deny pattern does not (documented as a known gap on
  that pattern's own `ponytail:` comment) -- not by design intent, just a
  side effect of tokenising instead of matching a prefix.

## What this design deliberately does not do

- Does not touch `terminal.backend`, `--toolsets`, or `hermes tools
  disable` -- see "Why two profiles" above.
- Does not touch model, provider, or credentials for either profile --
  `foamhermes setup` / `foamhermes-review setup` is the user's own step, the
  same rule the design before this one followed.
- Does not give `foamhermes-review` an MCP server of any kind, paraview
  included -- it does not use one.
- Does not attempt to keep a `register_system_prompt_section` fresh across a
  long session's `task_done` calls -- see the trade-off note above.

## The exact command sequence, for hand-debugging

`foamagent init hermes-agent` runs, in order:

```bash
hermes profile create foamhermes                    # skipped if it exists
hermes profile create foamhermes-review --no-skills  # skipped if it exists
```

then writes `mcp_servers` and `plugins.enabled` directly into
`~/.hermes/profiles/foamhermes/config.yaml` (or `$HERMES_HOME/...`), copies
the skill into `.../foamhermes/skills/cfd/openfoam-cfd/`, and copies the
plugin into `.../foamhermes/plugins/foamagent-tasks/`. Nothing is written
into `foamhermes-review`'s own directory. Confirm the result with
`hermes -p foamhermes mcp list`, `hermes -p foamhermes plugins list`, and
`hermes plugins list` / `hermes mcp list` (the default profile) to see that
the latter two show neither.
