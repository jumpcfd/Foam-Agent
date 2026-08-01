"""FastMCP-based OpenFOAM Agent Server.

The server holds no model and no API key. Its tools measure the machine, run OpenFOAM and
read what happened; the reasoning belongs to the harness that calls them.

The one exception is the independent audit: request_review and request_report start a
model of the user's own harness in a separate process, with read-only tools, to check a
case against what was asked for. See foamagent.review.
"""

from typing import Optional

from fastmcp import FastMCP

from foamagent.config import Config
from foamagent.logger import get_logger
from foamagent.mcp import audit, deterministic, sandbox

logger = get_logger(__name__)


# Global configuration
_config: Optional[Config] = None


def get_config() -> Config:
    """Return the server's Config, built on first use.

    Building it at import made a bare `import` of this module read the environment and
    emit its resolution log, which is the wrong time for either.
    """
    global _config
    if _config is None:
        _config = Config()
    return _config


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
that spec before building anything, write the case, validate_case it, run_start it, follow
run_tail_log, and when it fails call classify_errors, which names the failure rather than
making you parse a stack trace. Fix and run again. When the run is complete,
request_review of the results, then request_report and show the user what it returns.
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
    the tools that build and run cases. The sandbox profile registers one tool; that the
    others are absent is enforced here rather than by the allowlist the review is started
    with, so both would have to be wrong for the review to reach them.
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
    return server


# The server as an MCP client gets it: `python -m foamagent.mcp.fastmcp_server`.
mcp = build_server()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FastMCP OpenFOAM Agent Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="http",
        help="Transport method (default: http)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7860,
        help="Port for HTTP transport (default: 7860)"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Host for HTTP transport (default: localhost)"
    )

    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        # Configure uvicorn with correct websockets setting
        uvicorn_config = {"ws": "websockets"}
        mcp.run("http", host=args.host, port=args.port, uvicorn_config=uvicorn_config)


# run the server:
# python -m foamagent.mcp.fastmcp_server --transport http --host 0.0.0.0 --port 7860
