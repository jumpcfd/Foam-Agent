"""Unit tests for who runs the model.

The default is nobody: the harness reasons, and this process only measures and runs things.
These tests fix that default, and check that the two ways of overriding it behave.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from foamagent.inference import (
    ALLOW_DIRECT_API_ENV,
    BACKEND_ENV,
    DEFAULT_BACKEND,
    HOST_DELEGATE,
    HOST_SAMPLING,
    DirectApiRefused,
    direct_api_allowed,
    require_direct_api,
    selected_backend,
)
from foamagent.inference.sampling import (
    SamplingService,
    SamplingUnavailable,
    sampling_context,
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv(ALLOW_DIRECT_API_ENV, raising=False)
    monkeypatch.delenv(BACKEND_ENV, raising=False)


# ---------------------------------------------------------------------------
# The default and the gate
# ---------------------------------------------------------------------------


def test_nobody_runs_a_model_by_default():
    assert selected_backend() == HOST_DELEGATE == DEFAULT_BACKEND
    assert not direct_api_allowed()


def test_in_process_inference_is_refused_with_an_explanation():
    with pytest.raises(DirectApiRefused) as excinfo:
        require_direct_api()

    message = str(excinfo.value)
    assert "host_delegate" in message
    assert ALLOW_DIRECT_API_ENV in message


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_the_opt_in_is_taken_at_its_word(monkeypatch, value):
    monkeypatch.setenv(ALLOW_DIRECT_API_ENV, value)

    assert direct_api_allowed()
    require_direct_api()


@pytest.mark.parametrize("value", ["0", "false", "", "  "])
def test_anything_else_is_not_an_opt_in(monkeypatch, value):
    monkeypatch.setenv(ALLOW_DIRECT_API_ENV, value)

    assert not direct_api_allowed()


def test_an_unknown_backend_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(BACKEND_ENV, "carrier-pigeon")

    assert selected_backend() == HOST_DELEGATE


def test_sampling_can_be_selected(monkeypatch):
    monkeypatch.setenv(BACKEND_ENV, "host_sampling")

    assert selected_backend() == HOST_SAMPLING


def test_the_service_factory_refuses_without_the_opt_in(monkeypatch):
    from foamagent.services import get_llm_service, set_llm_service

    set_llm_service(None)
    try:
        with pytest.raises(DirectApiRefused):
            get_llm_service()
    finally:
        set_llm_service(None)


def test_the_service_factory_hands_out_the_sampling_backend(monkeypatch):
    from foamagent.services import get_llm_service, set_llm_service

    monkeypatch.setenv(BACKEND_ENV, "host_sampling")
    set_llm_service(None)
    try:
        assert isinstance(get_llm_service(), SamplingService)
    finally:
        set_llm_service(None)


# ---------------------------------------------------------------------------
# Asking the client's model
# ---------------------------------------------------------------------------


class FakeClient:
    """A context whose sample() answers with whatever the test set."""

    def __init__(self, reply="ok"):
        self.reply = reply
        self.prompts = []

    async def sample(self, prompt, system_prompt=None):
        self.prompts.append((prompt, system_prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class Answer(BaseModel):
    solver: str
    steps: int


def test_a_reply_comes_back_as_text():
    client = FakeClient("icoFoam")

    with sampling_context(client):
        assert SamplingService().invoke("which solver?", "you are helpful") == "icoFoam"

    assert client.prompts == [("which solver?", "you are helpful")]


def test_a_structured_reply_is_validated():
    client = FakeClient('{"solver": "icoFoam", "steps": 3}')

    with sampling_context(client):
        answer = SamplingService().invoke("plan it", pydantic_obj=Answer)

    assert answer.solver == "icoFoam"
    assert answer.steps == 3


def test_a_fenced_reply_is_still_json():
    client = FakeClient('Sure:\n```json\n{"solver": "simpleFoam", "steps": 1}\n```\n')

    with sampling_context(client):
        answer = SamplingService().invoke("plan it", pydantic_obj=Answer)

    assert answer.solver == "simpleFoam"


def test_the_schema_travels_with_the_prompt():
    client = FakeClient('{"solver": "icoFoam", "steps": 1}')

    with sampling_context(client):
        SamplingService().invoke("plan it", pydantic_obj=Answer)

    prompt, _ = client.prompts[0]
    assert "JSON" in prompt
    assert "solver" in prompt


def test_a_reply_that_does_not_match_is_an_error():
    client = FakeClient("no idea, sorry")
    service = SamplingService()

    with sampling_context(client), pytest.raises(ValueError):
        service.invoke("plan it", pydantic_obj=Answer)

    assert service.failed_calls == 1


def test_a_client_that_cannot_sample_says_so():
    class Old:
        pass

    with sampling_context(Old()), pytest.raises(SamplingUnavailable):
        SamplingService().invoke("anything")


def test_a_client_that_refuses_sampling_says_so():
    client = FakeClient(RuntimeError("sampling not supported by this client"))

    with sampling_context(client), pytest.raises(SamplingUnavailable):
        SamplingService().invoke("anything")


def test_without_a_client_there_is_nothing_to_ask():
    with pytest.raises(SamplingUnavailable):
        SamplingService().invoke("anything")


def test_calls_are_counted():
    client = FakeClient("fine")
    service = SamplingService()

    with sampling_context(client):
        service.invoke("one")
        service.invoke("two")

    assert service.get_statistics()["total_calls"] == 2


def test_the_context_is_visible_from_a_worker_thread():
    # The services are synchronous and the tools run them with asyncio.to_thread, which
    # copies the context; if that stopped being true, sampling would break there only.
    client = FakeClient("from the thread")

    async def main():
        with sampling_context(client):
            return await asyncio.to_thread(SamplingService().invoke, "hello")

    assert asyncio.run(main()) == "from the thread"
