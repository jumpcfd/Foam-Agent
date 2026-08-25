"""FastMCP-based OpenFOAM Agent Server.

The server holds no model and no API key. Its tools measure the machine, run OpenFOAM and
read what happened; the reasoning belongs to the harness that calls them.

The one exception is the independent audit: request_review and request_report start a
model of the user's own harness in a separate, trusted process to check a case against what
was asked for, and return at once -- review_status/report_status are polled for the result.
See foamagent.review.
"""

from fastmcp import FastMCP

from foamagent.logger import get_logger
from foamagent.mcp import audit, deterministic, sandbox, tasks

logger = get_logger(__name__)


INSTRUCTIONS = """
Foam-Agent gives you OpenFOAM: the installation on this machine, the tutorials that ship
with it, and the ability to run cases and read what happened.

You do the thinking. The tools measure, run, check and report; none of them writes your
case for you. Choosing the solver, writing the dictionaries and deciding what to change
after a failure are yours.

Start with describe_environment. It names the solvers this OpenFOAM actually has -- do not
use one that is not listed -- and points at a catalogue of its tutorials. Read that
catalogue, pick the case closest to what is being asked for, and read that case's files
before writing your own: they are the working answer for this exact version, which is
worth more than any recollection of OpenFOAM's syntax.

Then: agree the conditions with the user and record them in spec.md, request_review of
that spec before building anything -- it returns at once, so poll review_status until it
reports done -- write the case with your own tools, validate_case it, then run its Allrun
yourself and watch it to completion: nobody else is following the solver, so a run you
stopped waiting on is a result nobody has. When it fails, read the log yourself rather than
guessing from the last few lines; fix and run again. When the run is complete, request_review
of the results (review_status again), then request_report (report_status) and show the user
what it returns.

The work is tracked as tasks in the project's git repository, and a task is done only by
the commit task_done makes. Start with task_list; task_add before beginning a piece of
work; case_register the moment you create a case directory; task_done with the paths you
changed when it is finished. Never run git commit yourself, and never commit on main.
"""

SANDBOX_INSTRUCTIONS = """
Foam-Agent gives you one tool here: run_script, which runs Python against the case you were
asked about. The case is mounted read-only, so nothing you run can change it.

Use it for the arithmetic. A balance you summed, a residual history you read out of the log,
a profile you interpolated and compared against published numbers, all beat the same claims
made by eye.
"""

FULL_PROFILE = "full"
SANDBOX_PROFILE = "sandbox"
PROFILES = (FULL_PROFILE, SANDBOX_PROFILE)


def build_server(profile: str = FULL_PROFILE) -> FastMCP:
    """Assemble a server.

    Two profiles, because the review is served by this same package and must not be handed
    the Worker's own tools. The sandbox profile registers one tool; that the others are
    absent is enforced here rather than by the allowlist the review is started with, so
    both would have to be wrong for the review to reach them.
    """
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile {profile!r}. Known: {', '.join(PROFILES)}.")

    if profile == SANDBOX_PROFILE:
        server = FastMCP(name="Foam-Agent", version="2.0.0", instructions=SANDBOX_INSTRUCTIONS)
        sandbox.register(server)
        return server

    server = FastMCP(name="Foam-Agent", version="2.0.0", instructions=INSTRUCTIONS)
    deterministic.register(server)
    audit.register(server)
    tasks.register(server)
    return server


# The full-profile server, for a client that wants an assembled one without calling
# build_server itself. `foamagent-mcp` (foamagent.mcp.cli) is how the server is started;
# it is the only entry point, so the transport flags live there and not here as well.
mcp = build_server()
