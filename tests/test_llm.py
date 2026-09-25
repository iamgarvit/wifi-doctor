"""The provider layer: retry policy, message translation, and the mock's policy."""

from __future__ import annotations

import json

import pytest

from wifi_doctor.config import get_settings
from wifi_doctor.llm import (
    GroqProvider,
    LLMProvider,
    LLMResponse,
    Message,
    MockProvider,
    ProviderError,
    RateLimitError,
    ToolCall,
    _is_retryable,
    _retry_after_seconds,
    build_provider,
)


class Flaky(LLMProvider):
    """Fails `n_failures` times with `exc`, then succeeds."""

    name = "flaky"

    def __init__(self, exc: Exception, n_failures: int, **kw) -> None:
        super().__init__("flaky-1", **kw)
        self.exc = exc
        self.left = n_failures
        self.attempts = 0

    def _generate(self, **kw) -> LLMResponse:
        self.attempts += 1
        if self.left > 0:
            self.left -= 1
            raise self.exc
        return LLMResponse(
            text="ok",
            tool_calls=[],
            finish="STOP",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=1.0,
        )


@pytest.mark.parametrize(
    "text",
    ["429 RESOURCE_EXHAUSTED", "rate limit exceeded", "503 UNAVAILABLE", "model is overloaded"],
)
def test_recognises_retryable_failures(text):
    assert _is_retryable(RuntimeError(text))


def test_does_not_retry_a_plain_bad_request():
    assert not _is_retryable(RuntimeError("400 INVALID_ARGUMENT: bad schema"))


def test_retryable_error_is_retried_with_backoff():
    slept: list[float] = []
    p = Flaky(RateLimitError("429 RESOURCE_EXHAUSTED"), 2, sleep=slept.append)
    resp = p.generate(system="s", messages=[])
    assert resp.text == "ok" and p.attempts == 3
    assert len(slept) == 2 and slept[1] > slept[0]  # exponential


def test_provider_backoff_hint_is_honoured():
    slept: list[float] = []
    p = Flaky(RateLimitError("429 {'retryDelay': '7s'}"), 1, sleep=slept.append)
    p.generate(system="s", messages=[])
    assert 7.0 <= slept[0] < 7.6  # the hint, plus a little jitter


def test_non_retryable_error_propagates_immediately():
    slept: list[float] = []
    p = Flaky(ProviderError("400 INVALID_ARGUMENT"), 1, sleep=slept.append)
    with pytest.raises(ProviderError):
        p.generate(system="s", messages=[])
    assert p.attempts == 1 and slept == []


def test_retry_after_seconds_parsing():
    assert _retry_after_seconds(RuntimeError("{'retryDelay': '12s'}")) == 12.0
    assert _retry_after_seconds(RuntimeError("no hint here")) is None


def test_rate_limiter_is_consulted_once_per_attempt():
    class CountingLimiter:
        def __init__(self) -> None:
            self.n = 0

        def acquire(self) -> None:
            self.n += 1

    limiter = CountingLimiter()
    p = Flaky(RateLimitError("429"), 2, rate_limiter=limiter, sleep=lambda _: None)
    p.generate(system="s", messages=[])
    assert limiter.n == 3


def test_groq_message_translation_round_trips_tool_calls():
    messages = [
        Message(role="user", text="hello"),
        Message(
            role="assistant",
            tool_calls=[ToolCall(name="search_log", args={"pattern": "x"}, id="c1")],
        ),
        Message(
            role="tool", tool_call_id="c1", tool_name="search_log", tool_result={"returned": 2}
        ),
    ]
    out = GroqProvider._to_messages("SYS", messages)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[1] == {"role": "user", "content": "hello"}
    assert out[2]["tool_calls"][0]["function"]["name"] == "search_log"
    assert json.loads(out[2]["tool_calls"][0]["function"]["arguments"]) == {"pattern": "x"}
    assert out[3]["role"] == "tool" and out[3]["tool_call_id"] == "c1"
    assert json.loads(out[3]["content"]) == {"returned": 2}


def test_mock_follows_a_fixed_investigation_order():
    p = MockProvider()
    messages: list[Message] = [Message(role="user", text="go")]
    names = []
    for _ in range(3):
        resp = p.generate(system="s", messages=messages, tools=[])
        call = resp.tool_calls[0]
        names.append(call.name)
        messages.append(Message(role="assistant", tool_calls=[call]))
        messages.append(Message(role="tool", tool_name=call.name, tool_result={"total_lines": 1}))
    assert names == ["get_timeline", "search_log", "retrieve_kb"]


def test_mock_reports_tokens_so_cost_accounting_is_exercised():
    resp = MockProvider().generate(system="s", messages=[Message(role="user", text="x")], tools=[])
    assert resp.total_tokens == 140


def test_build_provider_selects_by_name():
    assert build_provider(get_settings("mock")).name == "mock"


def test_build_provider_rejects_an_unknown_provider():
    with pytest.raises(ProviderError, match="unknown provider"):
        build_provider(get_settings("banana"))
