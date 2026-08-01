"""Deterministic services behind the MCP tools.

Every module here measures, runs or checks something; none of them calls a model. The
reasoning happens in the harness that drives the server (see foamagent.mcp), and the
independent audit runs the server starts live in foamagent.review.
"""

__all__: list = []
