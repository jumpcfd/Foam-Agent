"""Unit tests for deterministic helpers in foamagent.utils.

Everything here is offline: no network, no credentials, no docker, no real LLM call.
Fake LLM clients are hand-rolled objects presenting only the interface LLMService.invoke()
actually uses (get_num_tokens / with_structured_output / invoke).
"""

from __future__ import annotations

import json
import os

import pytest
from pydantic import BaseModel, ValidationError

from foamagent.config import Config
from foamagent.services import get_llm_service, set_llm_service
from foamagent.utils import (
    LLMService,
    _botocore_client_error,
    _lfs_pointer_reason,
)


# ---------------------------------------------------------------------------
# _lfs_pointer_reason
# ---------------------------------------------------------------------------


def test_lfs_pointer_reason_detects_pointer(tmp_path):
    pointer_file = tmp_path / "index.faiss"
    pointer_file.write_bytes(
        b"version https://git-lfs.github.com/spec/v1\n"
        b"oid sha256:" + b"a" * 64 + b"\n"
        b"size 1234\n"
    )

    reason = _lfs_pointer_reason(pointer_file)
    assert reason is not None
    assert "git lfs pull" in reason
    assert str(pointer_file) in reason


def test_lfs_pointer_reason_normal_binary_file(tmp_path):
    binary_file = tmp_path / "index.faiss"
    binary_file.write_bytes(bytes(range(256)) * 4)

    assert _lfs_pointer_reason(binary_file) is None


def test_lfs_pointer_reason_non_pointer_text_file(tmp_path):
    text_file = tmp_path / "notes.txt"
    text_file.write_text("just some ordinary text content\n", encoding="utf-8")

    assert _lfs_pointer_reason(text_file) is None


def test_lfs_pointer_reason_nonexistent_path(tmp_path):
    missing = tmp_path / "does-not-exist.faiss"
    assert _lfs_pointer_reason(missing) is None


# ---------------------------------------------------------------------------
# _botocore_client_error
# ---------------------------------------------------------------------------


def test_botocore_client_error_does_not_raise():
    result = _botocore_client_error()
    # Either botocore isn't installed (None) or its ClientError type is returned.
    assert result is None or isinstance(result, type)


# ---------------------------------------------------------------------------
# LLMService: laziness, error classification, statistics
# ---------------------------------------------------------------------------


def test_llm_service_construction_is_lazy(monkeypatch):
    # No credentials of any kind are set, and the provider name is bogus. Construction
    # must still succeed because the client is only built on first access to `.llm`.
    monkeypatch.delenv("FOAMAGENT_MODEL_PROVIDER", raising=False)
    cfg = Config(model_provider="totally-unsupported-provider")
    service = LLMService(cfg)

    assert service._llm is None  # nothing was built yet


def test_llm_service_llm_property_triggers_build_and_raises(monkeypatch):
    monkeypatch.delenv("FOAMAGENT_MODEL_PROVIDER", raising=False)
    cfg = Config(model_provider="totally-unsupported-provider")
    service = LLMService(cfg)

    # Construction succeeded above; the ValueError only happens on attribute access.
    with pytest.raises(ValueError, match="not a supported model_provider"):
        service.llm


def test_is_structured_output_error_validation_error():
    class Dummy(BaseModel):
        value: str

    service = LLMService(Config())
    try:
        Dummy.model_validate({})
    except ValidationError as exc:
        assert service._is_structured_output_error(exc) is True
    else:
        pytest.fail("expected ValidationError")


def test_is_structured_output_error_json_decode_error():
    service = LLMService(Config())
    try:
        json.loads("not json")
    except json.JSONDecodeError as exc:
        assert service._is_structured_output_error(exc) is True
    else:
        pytest.fail("expected JSONDecodeError")


def test_is_structured_output_error_false_for_plain_error():
    service = LLMService(Config())
    assert service._is_structured_output_error(RuntimeError("boom")) is False


def test_get_statistics_fresh_instance_has_no_zero_division():
    service = LLMService(Config())
    stats = service.get_statistics()

    assert stats["total_calls"] == 0
    assert stats["failed_calls"] == 0
    assert stats["retry_count"] == 0
    assert stats["total_prompt_tokens"] == 0
    assert stats["total_completion_tokens"] == 0
    assert stats["total_tokens"] == 0
    assert stats["average_prompt_tokens"] == 0
    assert stats["average_completion_tokens"] == 0
    assert stats["average_tokens"] == 0


class _DummyModel(BaseModel):
    value: str


class _FakeStructuredLLM:
    """Mimics `<llm>.with_structured_output(model)`'s return value.

    Fails validation on the first call, then succeeds -- matching what LLMService.invoke()
    expects from `structured_llm.invoke(messages)`.
    """

    def __init__(self, outer):
        self._outer = outer

    def invoke(self, messages):
        self._outer.attempts += 1
        if self._outer.attempts == 1:
            raise self._outer.validation_error
        return self._outer.valid_response


class _FakeLLM:
    """Mimics the minimal LangChain chat-model interface LLMService.invoke() relies on."""

    def __init__(self, validation_error, valid_response):
        self.attempts = 0
        self.validation_error = validation_error
        self.valid_response = valid_response

    def get_num_tokens(self, text):
        return len(text.split())

    def with_structured_output(self, pydantic_obj):
        return _FakeStructuredLLM(self)


def test_invoke_retries_once_on_structured_output_error():
    try:
        _DummyModel.model_validate({})
        validation_error = None
    except ValidationError as exc:
        validation_error = exc
    assert validation_error is not None

    valid_response = _DummyModel(value="ok")
    fake_llm = _FakeLLM(validation_error, valid_response)

    service = LLMService(Config())
    service.llm = fake_llm  # uses the property setter; bypasses _build_llm entirely

    result = service.invoke("please answer", pydantic_obj=_DummyModel)

    assert result is valid_response
    assert fake_llm.attempts == 2  # first attempt failed validation, second succeeded
    assert service.retry_count == 1
    assert service.total_calls == 1
    assert service.failed_calls == 0


# ---------------------------------------------------------------------------
# foamagent.services.get_llm_service / set_llm_service
# ---------------------------------------------------------------------------


def test_get_llm_service_singleton_and_reset():
    set_llm_service(None)  # start from a clean slate regardless of test order
    try:
        first = get_llm_service(Config(model_provider="totally-unsupported-provider"))
        second = get_llm_service()
        assert first is second

        set_llm_service(None)
        third = get_llm_service(Config(model_provider="totally-unsupported-provider"))
        assert third is not first
    finally:
        set_llm_service(None)  # do not leak the module-level singleton to other tests
