"""Service-layer wrappers shared by the LangGraph pipeline and the MCP server.

The LLM service is created on first use rather than at import. Building it eagerly made
`import foamagent.services` read credentials from disk, which meant a plain import failed
outright on a machine with no provider configured — including during test collection.

There is exactly one instance, so the usage statistics reported at the end of a run cover
every call, not just the ones made through the graph's own handle.
"""

from typing import Optional

from foamagent.config import Config
from foamagent.inference import HOST_SAMPLING, require_direct_api, selected_backend
from foamagent.inference.sampling import SamplingService
from foamagent.utils import LLMService

_llm_service: Optional[LLMService] = None


def get_llm_service(config: Optional[Config] = None) -> LLMService:
    """Return the shared inference backend, creating it on first call.

    Building an LLMService means reading a provider key out of the environment and spending
    the user's money on every call that follows, so the opt-in is checked here -- at the
    one place every caller passes through -- rather than trusted to each of them.
    """
    global _llm_service
    if _llm_service is None:
        backend = selected_backend()
        if backend == HOST_SAMPLING:
            _llm_service = SamplingService()
        else:
            require_direct_api(
                "This code path runs the model itself: the in-process pipeline "
                "(foamagent.main) and the MCP tools that generate or review files."
            )
            _llm_service = LLMService(config or Config())
    return _llm_service


def set_llm_service(service: Optional[LLMService]) -> None:
    """Install a specific instance (or None to reset). Used by the CLI and by tests."""
    global _llm_service
    _llm_service = service


__all__ = ["get_llm_service", "set_llm_service"]
