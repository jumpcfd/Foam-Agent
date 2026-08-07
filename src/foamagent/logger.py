# logger.py
"""Centralized logging for Foam-Agent.

Diagnostics go to **stderr** through the standard `logging` module. This matters beyond
tidiness: when the MCP server speaks stdio, stdout *is* the protocol channel, so anything
written there corrupts the session. `foamagent`'s own output to a person is the CLI's
business (see `cli._emit`), and `ruff`'s T201 keeps the rest of the package off stdout.

Usage:
    from foamagent.logger import get_logger

    logger = get_logger(__name__)
"""

import logging
import os
import sys
from typing import Optional

_ROOT_LOGGER_NAME = "foamagent"
_LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"


def _root_logger() -> logging.Logger:
    """Return the package logger, attaching a stderr handler on first use."""
    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    if not any(getattr(h, "_foamagent_stream", False) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        handler._foamagent_stream = True
        logger.addHandler(handler)
        logger.propagate = False
    level = os.getenv("FOAMAGENT_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a logger under the ``foamagent`` hierarchy.

    Pass ``__name__`` from a module inside the package; anything outside it is nested
    under ``foamagent.`` so a single handler covers every caller.
    """
    root = _root_logger()
    if not name or name == _ROOT_LOGGER_NAME:
        return root
    if name.startswith(_ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
