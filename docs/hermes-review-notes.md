# Notes: Hermes Agent as the review command

This is the debugging history and rationale behind `setup_hermes_review()`
(`src/foamagent/harness/__init__.py`) and the `hermes-agent` profile in
`HARNESS_PROFILES` (`src/foamagent/review/settings.py`). The README only documents how
to run the setup and confirm it works; this document is for anyone changing that setup,
hand-rolling it instead of running `foamagent install hermes-agent --with-review`, or
debugging a review that isn't behaving as expected.

## Why a dedicated profile at all

Claude Code's isolation is a flag: `--strict-mcp-config` hands one review its own
throwaway MCP server and hides everything else configured, including the `foamagent`
server the worker itself is using (`run_start`, `run_stop` and the rest). Hermes has no
per-invocation equivalent — its MCP servers are global (`~/.hermes/config.yaml`) — so
isolation has to come from *which Hermes profile* runs the review instead of a flag.
`foamagent-review` is that profile: an isolated Hermes identity with no MCP servers and
no bundled skills, never the user's main one.

## Confirmed pitfalls (in the order they were found)

**Routing `terminal.backend` through Docker breaks `file` reads.** An early version set
`terminal.backend: docker` to sandbox the review. That rerouted the `file` toolset's
reads through a container-mounted `/workspace` that did not reliably reflect the host
directory's actual content on WSL2 (confirmed: the host directory had real files, the
mounted view was empty).

**Writing `terminal.backend` at all breaks `file` toolset exposure — even to `host`,
Hermes's own default.** The "fix" for the above was setting `terminal.backend: host`
explicitly. That was also wrong, and more subtly: confirmed by isolating the change on
a series of throwaway profiles, changing exactly one setting at a time, that merely
calling `hermes config set terminal.backend host` — with no other change — makes
Hermes silently stop exposing `file` (and `terminal`) toolset functions to the model at
all. This does not clear by writing a different value afterward; only a profile whose
config.yaml never had `terminal.backend` written into it was seen to recover. The
isolation that actually holds is disabling the `terminal` toolset by name
(`hermes tools disable ... terminal ...`), which is unaffected by this bug.
`setup_hermes_review()` must never call `config set terminal.*`, in any form.

**The per-invocation `--toolsets` flag makes the `file` toolset stop working.**
Confirmed directly against `hermes -z --toolsets file,web` (and `-t file` alone) with
two different models: the model could no longer read a file that was actually there,
either with a flat refusal or a confident wrong answer with no tool call at all — while
the identical prompt with no `--toolsets` restriction read correctly every time. This is
why `HARNESS_PROFILES["hermes-agent"]["allow_tools_flag"]` is `""`: isolation for `file`
comes entirely from `review.copy_case_dir` (below) plus the persistent, profile-level
`hermes tools disable`, never from a per-call flag.

**Hermes's MCP client-side timeout defaults to 300s, shorter than a review's own
1800s.** Hermes's own `tools/mcp_tool.py` (`_DEFAULT_TOOL_TIMEOUT`) cuts off a single
MCP tool call at 300s by default. A real review that legitimately took longer than
300s but well under `review.timeout_seconds`'s own 1800s default was cut off
client-side with "MCP TimeoutError" while the server-side subprocess, still well
within its own budget, kept running and eventually produced a real result the worker
never got to see. `install_hermes_agent()` now writes `timeout: 1800` into the MCP
server's config entry (in `foamagent-hermes.yaml`) to match, which also benefits the
worker's own long-polling `run_status` calls.

**`hermes mcp add` has no non-interactive flag.** It always stops for an "Enable all
N tools? [Y/n/select]" prompt with nothing to skip it, so it cannot be scripted or run
unattended. Merging `foamagent-hermes.yaml`'s `mcp_servers` entry into
`~/.hermes/config.yaml` by hand is the only non-interactive path, and is what the
installer's own note recommends first.

**Hermes's own installer can hang on its Chromium download.** `hermes` itself becomes
usable as soon as the installer's main work finishes; a later step downloads a
Chromium build for the `browser` toolset and has been observed to stall indefinitely
partway through on a slow or filtered network, with `hermes` already working while it
does. Neither the worker's use of Hermes nor `foamagent-review` needs the `browser`
toolset (`--with-review` disables it explicitly), so it is safe to interrupt just that
download if it hangs.

## The remaining gap: `file` bundles read and write

Hermes's `file` toolset has no read-without-write split, so there is no way to grant
"can read the case" without also granting "can write it" — confirmed by asking a review
to write a probe file with only `web` enabled: no file appeared, but the model still
reported success anyway, so a silent decline and a silent failure look the same from
the outside. `hermes-agent`'s `copy_case_dir: true` is how this stays safe regardless:
the review is handed a throwaway copy of the case, never the case itself, so it does
not matter whether it can write. `foamagent doctor --review`'s "Review: cannot write"
check passes because of this copy, not because Hermes was made incapable of writing —
worth knowing before trusting the same approach for a harness that is not this one.

## What Foam-Agent deliberately does not do

`setup_hermes_review()` does not touch model, provider, or credentials. An earlier
version copied `model.default`/`model.provider` from the user's default Hermes profile
and, to make the review actually authenticate (Hermes hands the review subprocess a
stripped environment with no ambient credentials — see `hermes_cli`'s own
`_build_safe_env`, whose docstring says this is deliberate), wrote a real API key into
`foamagent-hermes.yaml`. Both are gone: this package's "no API key on this server" rule
(`channel.py`'s module docstring) holds for the review profile with no exception. Model
and authentication are the user's own `foamagent-review config` to run, the same as for
any other Hermes profile.

## The exact manual command sequence

`foamagent install hermes-agent --with-review` runs exactly:

```bash
hermes profile create foamagent-review --no-skills   # skipped if the profile exists
hermes profile alias foamagent-review
hermes -p foamagent-review tools disable <every toolset the profile does not need>
foamagent config set review.harness hermes-agent
```

See `HERMES_REVIEW_DISABLED_TOOLSETS` in `src/foamagent/harness/__init__.py` for the
exact toolset list. Deliberately absent: any `hermes -p foamagent-review config set
terminal.*` call (see above), and any `config set model.*` or credential-related call
(see above). Every step but the profile creation itself is idempotent, so running the
whole sequence — or `foamagent install hermes-agent --with-review` — twice does not
double up anything.

Confirm it actually works with `foamagent doctor --review`.
