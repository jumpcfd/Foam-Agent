"""Who runs the model.

Foam-Agent used to answer that with "this process, using the user's API key". That made a
CFD tool into an LLM client: a key to obtain, a provider to choose, a bill to watch, and
a model the user could not see the prompts of.

There are three answers now:

- ``host_delegate`` (default) -- nobody here. The MCP server exposes only tools that
  measure and run things, and the agent calling them supplies all the judgement. No key,
  no provider, no second model.
- ``host_sampling`` -- the MCP client's model, reached through ``sampling/createMessage``.
  For clients that implement it, this keeps the in-process pipeline working without a key.
- ``direct_api`` -- this process, as before. Retained for unattended runs and for
  comparison against the published benchmark, and gated behind an explicit opt-in.

The gate is not ceremony. An API key in a server's environment is a credential the user
cannot audit per call, and a default that quietly spends money is worse than one that
stops and explains itself.
"""

from __future__ import annotations

import os
from typing import Any, Optional, Protocol, runtime_checkable

from foamagent.logger import get_logger

logger = get_logger(__name__)

HOST_DELEGATE = "host_delegate"
HOST_SAMPLING = "host_sampling"
DIRECT_API = "direct_api"

BACKENDS = (HOST_DELEGATE, HOST_SAMPLING, DIRECT_API)
DEFAULT_BACKEND = HOST_DELEGATE

ALLOW_DIRECT_API_ENV = "FOAMAGENT_ALLOW_DIRECT_API"
BACKEND_ENV = "FOAMAGENT_INFERENCE_BACKEND"

DIRECT_API_REFUSAL = (
    "direct_api runs the model inside Foam-Agent, which needs a provider API key in this "
    "process's environment. That is no longer the default: the supported arrangement is "
    "host_delegate, where the AI harness you are already using (Claude Code, Codex CLI, "
    "Cursor, ...) does the reasoning and Foam-Agent only runs OpenFOAM.\n"
    "\n"
    "  * To use a harness: register the MCP server and let it drive the tools.\n"
    f"  * To use an API key anyway: set {ALLOW_DIRECT_API_ENV}=1.\n"
)


@runtime_checkable
class InferenceBackend(Protocol):
    """Anything that can answer a prompt.

    Deliberately the signature `LLMService.invoke` already had: the services call it in
    dozens of places, and a backend swap that rewrites those call sites is a swap nobody
    will make.
    """

    def invoke(
        self, user_prompt: str, system_prompt: Optional[str] = None, pydantic_obj: Any = None
    ) -> Any:
        ...


def direct_api_allowed() -> bool:
    """Whether the user has opted into running the model in this process."""
    value = (os.getenv(ALLOW_DIRECT_API_ENV) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def selected_backend() -> str:
    """Which backend the environment asks for."""
    name = (os.getenv(BACKEND_ENV) or "").strip().lower()
    if name in BACKENDS:
        return name
    if name:
        logger.warning("Unknown %s=%r; using %s.", BACKEND_ENV, name, DEFAULT_BACKEND)
    return DEFAULT_BACKEND


class DirectApiRefused(RuntimeError):
    """Raised when in-process inference is requested without the opt-in."""


def require_direct_api(purpose: str = "") -> None:
    """Raise unless the user has opted into in-process inference."""
    if direct_api_allowed():
        return

    detail = f"{purpose}\n\n" if purpose else ""
    raise DirectApiRefused(detail + DIRECT_API_REFUSAL)


__all__ = [
    "ALLOW_DIRECT_API_ENV",
    "BACKENDS",
    "BACKEND_ENV",
    "DEFAULT_BACKEND",
    "DIRECT_API",
    "DIRECT_API_REFUSAL",
    "DirectApiRefused",
    "HOST_DELEGATE",
    "HOST_SAMPLING",
    "InferenceBackend",
    "direct_api_allowed",
    "require_direct_api",
    "selected_backend",
]
