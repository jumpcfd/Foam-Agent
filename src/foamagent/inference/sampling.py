"""Inference through the MCP client's own model.

`sampling/createMessage` is the part of MCP built for exactly this: the server asks the
client to run a prompt, and the client decides which model answers and whether the user
sees it. No key reaches the server, and the user keeps the ability to refuse a request.

It is not the default because the clients do not all implement it. Claude Code does not, as
of 2026-07 (anthropics/claude-code#1785). Where it exists it is the cleanest arrangement
for the in-process pipeline; where it does not, host_delegate covers the same ground by
having the agent call the tools directly.

The service exposes `LLMService`'s interface so the pipeline cannot tell the difference.
The context that carries the request is per-call state, set by whichever tool is running.
"""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, List, Optional

from foamagent.logger import get_logger

logger = get_logger(__name__)

# A ContextVar rather than a global: concurrent tool calls each have their own client, and
# asyncio.to_thread copies the calling context, so the worker thread that runs the
# synchronous services sees the right one.
_context: ContextVar = ContextVar("foamagent_sampling_context", default=None)


@contextmanager
def sampling_context(ctx):
    """Make ``ctx`` the client this service asks, for the duration of a tool call."""
    token = _context.set(ctx)
    try:
        yield
    finally:
        _context.reset(token)


def current_context():
    return _context.get()


class SamplingUnavailable(RuntimeError):
    """The client cannot answer a sampling request."""


class SamplingService:
    """LLMService's interface, answered by the MCP client.

    Statistics are kept the same way LLMService keeps them, so a run through this backend
    reports its usage in the same shape -- except tokens, which the client does not have to
    disclose and which are therefore counted as zero rather than guessed.
    """

    def __init__(self) -> None:
        self.total_calls = 0
        self.failed_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.model_version = "client-selected"
        self.model_provider = "host_sampling"

    # -- the interface the services use ---------------------------------------------

    def invoke(self, user_prompt: str, system_prompt: Optional[str] = None, pydantic_obj=None):
        ctx = current_context()
        if ctx is None:
            raise SamplingUnavailable(
                "host_sampling needs an MCP client to ask, and this call is not inside a "
                "tool invocation. Use it through the MCP server, or choose another "
                "inference backend."
            )

        prompt = user_prompt
        if pydantic_obj is not None:
            prompt = f"{user_prompt}\n\n{_schema_instruction(pydantic_obj)}"

        text = _run(_ask(ctx, prompt, system_prompt))
        self.total_calls += 1

        if pydantic_obj is None:
            return text

        try:
            return pydantic_obj.model_validate(_extract_json(text))
        except Exception as exc:
            self.failed_calls += 1
            raise ValueError(
                f"The client's reply did not match {pydantic_obj.__name__}: {exc}"
            ) from exc

    def get_statistics(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "failed_calls": self.failed_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
        }

    def print_statistics(self) -> None:
        logger.info(
            "<LLM Service Statistics> host_sampling: %d call(s), %d failed. "
            "Token counts are the client's to report, not this server's.",
            self.total_calls,
            self.failed_calls,
        )


def _schema_instruction(pydantic_obj) -> str:
    schema = json.dumps(pydantic_obj.model_json_schema(), indent=2)
    return (
        "Reply with JSON only -- no prose, no code fence -- matching this schema:\n" + schema
    )


def _extract_json(text: str) -> Any:
    """Pull the JSON document out of a reply that may be wrapped in prose or a fence."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        return json.loads(candidate[start:end + 1])
    raise ValueError("no JSON object in the reply")


async def _ask(ctx, prompt: str, system_prompt: Optional[str]) -> str:
    """Send one sampling request and return the text of the reply."""
    try:
        result = await ctx.sample(prompt, system_prompt=system_prompt)
    except AttributeError as exc:  # a context predating sampling support
        raise SamplingUnavailable(f"This MCP client cannot sample: {exc}") from exc
    except Exception as exc:
        message = str(exc)
        if "sampling" in message.lower() or "not supported" in message.lower():
            raise SamplingUnavailable(
                "The MCP client refused or does not implement sampling/createMessage. "
                "Claude Code does not implement it as of 2026-07; use host_delegate there."
            ) from exc
        raise

    return _text_of(result)


def _text_of(result) -> str:
    """FastMCP hands back a content block, an object with .text, or a plain string."""
    if isinstance(result, str):
        return result
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text

    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = [getattr(item, "text", "") or "" for item in content]
        return "".join(parts)
    return str(result)


def _run(coroutine):
    """Await ``coroutine`` from synchronous service code.

    The services are synchronous and the tools run them in a worker thread, so there is no
    running loop here to await on; when there is one, this is being called from the event
    loop itself and asyncio.run would deadlock.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    raise SamplingUnavailable(
        "A sampling request cannot be made from the event loop thread. The tool should run "
        "the service in a worker thread (asyncio.to_thread)."
    )


__all__ = [
    "SamplingService",
    "SamplingUnavailable",
    "current_context",
    "sampling_context",
]
