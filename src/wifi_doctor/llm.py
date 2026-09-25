"""Provider interface plus Gemini, Groq and Mock implementations.

The agent loop is written against :class:`LLMProvider`, not against any SDK, so
swapping providers is a flag and CI can run the whole pipeline offline against
:class:`MockProvider`.

Two capabilities the interface has to expose, because the agent needs both:

* **tool calling** — the model asks to run a tool and we feed the result back;
* **a forced final answer** — the model is *required* to emit one specific
  function call whose arguments are the diagnosis.

On Gemini those are ``FunctionCallingConfig(mode="AUTO")`` and
``mode="ANY", allowed_function_names=["submit_diagnosis"]``. Note that Gemini
rejects ``tools`` and ``response_schema`` in the same request (verified against
``gemini-3.5-flash-lite`` on 2026-09-25), which is exactly why the agent uses a
forced ``submit_diagnosis`` function rather than a response schema: it is the
only way to get a schema-constrained answer *and* keep the tools attached.
Single-shot mode has no tools, so it uses the native ``response_schema``
instead — both structured-output mechanisms are therefore live in this project.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .tools import ToolSpec

MAX_RETRIES = 5
BACKOFF_BASE = 2.0
BACKOFF_CAP = 60.0


class RateLimitError(RuntimeError):
    """The provider returned 429 / RESOURCE_EXHAUSTED."""


class ProviderError(RuntimeError):
    """Any other provider-side failure."""


@dataclass
class ToolCall:
    name: str
    args: dict
    id: str = ""
    # Opaque provider state that must be echoed back verbatim on the next turn.
    # Gemini 3.x rejects a multi-turn tool conversation whose function_call parts
    # are missing their thought_signature, so it rides along here rather than
    # leaking a Gemini concept into the agent loop.
    meta: dict = field(default_factory=dict)


@dataclass
class Message:
    """Provider-neutral conversation turn."""

    role: str  # "user" | "assistant" | "tool"
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_result: dict | None = None


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    finish: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: float


_RETRYABLE = re.compile(
    r"429|RESOURCE_EXHAUSTED|rate.?limit|quota|503|UNAVAILABLE|overloaded", re.IGNORECASE
)


def _is_retryable(exc: Exception) -> bool:
    return isinstance(exc, RateLimitError) or bool(_RETRYABLE.search(str(exc)))


# Gemini names the exhausted quota in its 429, e.g.
# "GenerateRequestsPerDayPerProjectPerModel-FreeTier". A daily quota does not
# come back within any backoff worth waiting for, so it is not retried.
_DAILY_QUOTA = re.compile(r"PerDay", re.IGNORECASE)


def _is_daily_quota(exc: Exception) -> bool:
    return bool(_DAILY_QUOTA.search(str(exc)))


def _retry_after_seconds(exc: Exception) -> float | None:
    """Honour the provider's own backoff hint when it gives one."""
    m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(exc))
    return float(m.group(1)) if m else None


class LLMProvider(ABC):
    """What the agent loop is allowed to assume about a model."""

    name: str = "abstract"

    def __init__(self, model: str, *, rate_limiter=None, sleep=time.sleep) -> None:
        self.model = model
        self.rate_limiter = rate_limiter
        self._sleep = sleep

    @abstractmethod
    def _generate(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        force_tool: str | None,
        response_schema: dict | None,
    ) -> LLMResponse: ...

    def generate(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        force_tool: str | None = None,
        response_schema: dict | None = None,
    ) -> LLMResponse:
        """One model call, with the client-side rate limiter and 429 backoff applied."""
        last: Exception | None = None
        for attempt in range(MAX_RETRIES):
            if self.rate_limiter is not None:
                self.rate_limiter.acquire()
            try:
                return self._generate(
                    system=system,
                    messages=messages,
                    tools=tools,
                    force_tool=force_tool,
                    response_schema=response_schema,
                )
            except Exception as exc:  # noqa: BLE001
                last = exc
                if not _is_retryable(exc) or _is_daily_quota(exc) or attempt == MAX_RETRIES - 1:
                    raise
                hint = _retry_after_seconds(exc)
                delay = hint if hint is not None else min(BACKOFF_CAP, BACKOFF_BASE**attempt)
                self._sleep(delay + random.uniform(0, 0.5))
        raise ProviderError(str(last))  # pragma: no cover


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, model: str, api_key: str | None = None, **kw) -> None:
        super().__init__(model, **kw)
        from google import genai  # imported lazily so CI need not install it

        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ProviderError("GEMINI_API_KEY is not set")
        self._client = genai.Client(api_key=key)

    @staticmethod
    def _to_contents(messages: list[Message]):
        from google.genai import types

        out = []
        for m in messages:
            if m.role == "user":
                out.append(types.Content(role="user", parts=[types.Part(text=m.text or "")]))
            elif m.role == "assistant":
                parts = []
                if m.text:
                    parts.append(types.Part(text=m.text))
                for tc in m.tool_calls:
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(name=tc.name, args=tc.args),
                            thought_signature=tc.meta.get("thought_signature"),
                        )
                    )
                out.append(types.Content(role="model", parts=parts))
            elif m.role == "tool":
                out.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=m.tool_name or "", response=m.tool_result or {}
                            )
                        ],
                    )
                )
        return out

    @staticmethod
    def _to_tools(tools: list[ToolSpec]):
        from google.genai import types

        return [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t.name, description=t.description, parameters=t.parameters
                    )
                    for t in tools
                ]
            )
        ]

    def _generate(self, *, system, messages, tools, force_tool, response_schema) -> LLMResponse:
        from google.genai import types

        cfg: dict[str, Any] = {"system_instruction": system, "temperature": 0.0}
        if tools:
            cfg["tools"] = self._to_tools(tools)
            # The SDK would otherwise try to *execute* the functions itself.
            cfg["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
            fcc = (
                types.FunctionCallingConfig(mode="ANY", allowed_function_names=[force_tool])
                if force_tool
                else types.FunctionCallingConfig(mode="AUTO")
            )
            cfg["tool_config"] = types.ToolConfig(function_calling_config=fcc)
        elif response_schema is not None:
            cfg["response_mime_type"] = "application/json"
            cfg["response_schema"] = response_schema

        t0 = time.perf_counter()
        try:
            resp = self._client.models.generate_content(
                model=self.model,
                contents=self._to_contents(messages),
                config=types.GenerateContentConfig(**cfg),
            )
        except Exception as exc:  # noqa: BLE001
            raise (
                RateLimitError(str(exc)) if _is_retryable(exc) else ProviderError(str(exc))
            ) from exc
        latency = (time.perf_counter() - t0) * 1000

        text_parts, calls = [], []
        cands = resp.candidates or []
        finish = str(cands[0].finish_reason) if cands and cands[0].finish_reason else None
        if cands and cands[0].content and cands[0].content.parts:
            for p in cands[0].content.parts:
                if getattr(p, "text", None):
                    text_parts.append(p.text)
                fc = getattr(p, "function_call", None)
                if fc is not None and fc.name:
                    sig = getattr(p, "thought_signature", None)
                    calls.append(
                        ToolCall(
                            name=fc.name,
                            args=dict(fc.args or {}),
                            id=getattr(fc, "id", "") or fc.name,
                            meta={"thought_signature": sig} if sig else {},
                        )
                    )
        u = resp.usage_metadata
        return LLMResponse(
            text="".join(text_parts) or None,
            tool_calls=calls,
            finish=finish,
            prompt_tokens=getattr(u, "prompt_token_count", None) if u else None,
            completion_tokens=getattr(u, "candidates_token_count", None) if u else None,
            total_tokens=getattr(u, "total_token_count", None) if u else None,
            latency_ms=latency,
        )


# --------------------------------------------------------------------------
# Groq (OpenAI-compatible)
# --------------------------------------------------------------------------


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, model: str, api_key: str | None = None, **kw) -> None:
        super().__init__(model, **kw)
        from groq import Groq

        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise ProviderError("GROQ_API_KEY is not set")
        self._client = Groq(api_key=key)

    @staticmethod
    def _to_messages(system: str, messages: list[Message]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.text or ""})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.text or ""}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": tc.id or tc.name,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                        }
                        for tc in m.tool_calls
                    ]
                out.append(msg)
            elif m.role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id or m.tool_name or "",
                        "name": m.tool_name,
                        "content": json.dumps(m.tool_result or {}),
                    }
                )
        return out

    def _generate(self, *, system, messages, tools, force_tool, response_schema) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_messages(system, messages),
            "temperature": 0.0,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            kwargs["tool_choice"] = (
                {"type": "function", "function": {"name": force_tool}} if force_tool else "auto"
            )
        elif response_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}

        t0 = time.perf_counter()
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise (
                RateLimitError(str(exc)) if _is_retryable(exc) else ProviderError(str(exc))
            ) from exc
        latency = (time.perf_counter() - t0) * 1000

        choice = resp.choices[0]
        calls = []
        for tc in choice.message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(name=tc.function.name, args=args, id=tc.id))
        u = resp.usage
        return LLMResponse(
            text=choice.message.content,
            tool_calls=calls,
            finish=choice.finish_reason,
            prompt_tokens=getattr(u, "prompt_tokens", None) if u else None,
            completion_tokens=getattr(u, "completion_tokens", None) if u else None,
            total_tokens=getattr(u, "total_tokens", None) if u else None,
            latency_ms=latency,
        )


# --------------------------------------------------------------------------
# Mock
# --------------------------------------------------------------------------


class MockProvider(LLMProvider):
    """Deterministic, offline provider for tests and CI.

    It plays a fixed but realistic policy — timeline, then a targeted
    ``search_log``, then ``retrieve_kb``, then the forced ``submit_diagnosis``
    — so the whole agent loop (tool dispatch, validation, retry) is exercised
    without a network. The diagnosis it submits is the **rule baseline's**
    answer, computed from the tool results it has already seen, so end-to-end
    tests assert on a real, self-consistent output rather than a canned blob.

    ``MockProvider`` is never used for any reported metric.
    """

    name = "mock"

    def __init__(self, model: str = "mock-1", *, fail_first_validation: bool = False, **kw) -> None:
        super().__init__(model, **kw)
        self.fail_first_validation = fail_first_validation
        self.calls = 0
        self.final_calls = 0

    def _generate(self, *, system, messages, tools, force_tool, response_schema) -> LLMResponse:
        self.calls += 1
        time.sleep(0)  # keep latency non-negative and the shape identical
        t0 = time.perf_counter()
        log_text = _extract_mock_log(messages)

        if force_tool or response_schema is not None:
            self.final_calls += 1
            payload = _mock_diagnosis(
                log_text, messages, break_it=self.fail_first_validation and self.final_calls == 1
            )
            if response_schema is not None:
                return self._resp(text=json.dumps(payload), calls=[], t0=t0, finish="STOP")
            return self._resp(
                text=None,
                t0=t0,
                finish="STOP",
                calls=[ToolCall(name=force_tool, args=payload, id="mock_final")],
            )

        # Tool phase: a fixed, sensible investigation order.
        used = {tc.name for m in messages if m.role == "assistant" for tc in m.tool_calls}
        if "get_timeline" not in used:
            call = ToolCall(name="get_timeline", args={}, id="mock_1")
        elif "search_log" not in used:
            call = ToolCall(
                name="search_log",
                args={
                    "pattern": r"fail|timeout|reject|deauth|WRONG_KEY|No DHCPOFFERS|NETWORK-NOT-FOUND",
                    "max_hits": 12,
                },
                id="mock_2",
            )
        elif "retrieve_kb" not in used:
            call = ToolCall(
                name="retrieve_kb",
                args={"query": "how to tell wifi failure classes apart", "k": 3},
                id="mock_3",
            )
        else:
            return self._resp(text="Ready to conclude.", calls=[], t0=t0, finish="STOP")
        return self._resp(text=None, calls=[call], t0=t0, finish="TOOL_CALL")

    def _resp(self, *, text, calls, t0, finish) -> LLMResponse:
        return LLMResponse(
            text=text,
            tool_calls=calls,
            finish=finish,
            prompt_tokens=100,
            completion_tokens=40,
            total_tokens=140,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )


def _extract_mock_log(messages: list[Message]) -> str:
    """Recover a usable view of the log from whatever this mode exposed.

    In single-shot mode the log is in the prompt. In agent mode the mock has
    only ever seen tool results, so the log is reassembled sparsely from the
    line numbers those returned -- which is exactly the information a real
    model would have had, and keeps the mock's citations valid.
    """
    for m in messages:
        if m.role == "user" and m.text and "<log>" in m.text:
            block = re.search(r"<log>\n(.*?)\n</log>", m.text, re.DOTALL)
            if block:
                return re.sub(r"^\s*\d+\|\s?", "", block.group(1), flags=re.MULTILINE)

    known: dict[int, str] = {}
    total = 0
    for m in messages:
        if m.role != "tool" or not m.tool_result:
            continue
        res = m.tool_result
        total = max(total, int(res.get("total_lines") or 0))
        for hit in res.get("matches", []):
            known[int(hit["line_no"])] = hit["text"]
        for ev in res.get("control_events", []):
            known[int(ev["line_no"])] = ev["text"]
    if not total:
        return ""
    return "\n".join(known.get(i, "") for i in range(1, total + 1))


def _mock_diagnosis(log_text: str, messages: list[Message], *, break_it: bool) -> dict:
    from .baseline import classify

    d = classify(log_text)
    cited = sorted(
        {
            r["doc_id"]
            for m in messages
            if m.role == "tool" and m.tool_name == "retrieve_kb"
            for r in (m.tool_result or {}).get("results", [])
        }
    )
    payload = {
        "root_cause": d.root_cause.value,
        "summary": d.summary,
        "evidence": [{"line_no": e.line_no, "quote": e.quote, "why": e.why} for e in d.evidence],
        "confidence": d.confidence,
        "suggested_fixes": d.suggested_fixes,
        "kb_citations": cited,
        "needs_more_info": d.needs_more_info,
    }
    if break_it:
        # Deliberately invalid: a line number that cannot exist, so the
        # validation-and-retry path can be tested.
        payload["evidence"] = [
            {"line_no": 10**9, "quote": "nonexistent", "why": "broken on purpose"}
        ]
    return payload


# --------------------------------------------------------------------------


def build_provider(settings, *, rate_limiter=None) -> LLMProvider:
    """Construct the provider named by ``settings.provider``."""
    kinds = {"gemini": GeminiProvider, "groq": GroqProvider, "mock": MockProvider}
    cls = kinds.get(settings.provider)
    if cls is None:
        raise ProviderError(
            f"unknown provider {settings.provider!r}; expected one of {sorted(kinds)}"
        )
    if cls is MockProvider:
        return MockProvider(settings.model, rate_limiter=rate_limiter)
    return cls(settings.model, api_key=settings.api_key, rate_limiter=rate_limiter)
