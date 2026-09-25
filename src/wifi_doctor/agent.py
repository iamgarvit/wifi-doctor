"""The agent loop, written by hand.

Why by hand rather than with a framework: the loop is about forty lines, and
every interesting decision in this project lives inside it — when tools stop
and the answer is forced, what counts as a valid answer, what gets fed back on
a retry, and what is written to the trace. A framework would hide exactly those
decisions behind defaults I would then have to explain anyway.

The shape:

    system prompt
      └─ up to MAX_STEPS tool turns   (Gemini function calling, mode=AUTO)
           └─ forced submit_diagnosis (mode=ANY, allowed=[submit_diagnosis])
                └─ validate → on failure, feed the errors back and retry once
                     └─ still invalid → return needs_more_info=true, flagged

Validation is the part that matters. Three checks turn "the model said so" into
something checkable:

1. the payload parses as :class:`~wifi_doctor.schema.Diagnosis`;
2. every cited ``line_no`` exists in the log **and** the quote really occurs on
   that line;
3. every ``kb_citation`` is a doc id that was actually retrieved in this run.

A model that hallucinates a citation fails (2) or (3) and is told precisely
what was wrong.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .llm import LLMProvider, Message, ToolCall
from .logparse import split_lines, truncate_for_prompt
from .prompts import (
    RETRY_PREFIX,
    SYSTEM_AGENT,
    SYSTEM_SINGLE_SHOT,
    USER_AGENT,
    USER_SINGLE_SHOT,
)
from .redact import Redactor, redact_log
from .retrieval import KnowledgeBase, get_kb
from .schema import Diagnosis, RootCause, gemini_function_parameters
from .tools import TOOL_SPECS, ToolContext, ToolSpec, dispatch
from .tracing import Trace

MAX_STEPS = 6
MAX_VALIDATION_ATTEMPTS = 2
SINGLE_SHOT_MAX_LINES = 2000

SUBMIT_TOOL = ToolSpec(
    name="submit_diagnosis",
    description=(
        "Submit the final diagnosis. Call this exactly once, after you have "
        "gathered evidence. Every cited line number must have come from a tool result."
    ),
    parameters=gemini_function_parameters(),
    fn=lambda ctx, **kw: kw,  # never dispatched; the agent consumes the arguments directly
)


@dataclass
class AgentResult:
    diagnosis: Diagnosis
    mode: str
    steps: int
    validation_attempts: int
    valid_first_try: bool
    validation_errors: list[str]
    retrieved_doc_ids: list[str]
    trace: Trace
    redactor: Redactor
    redacted_log: str
    totals: dict = field(default_factory=dict)

    def display(self) -> Diagnosis:
        """The diagnosis with placeholders replaced by the user's real values."""
        d = self.diagnosis.model_copy(deep=True)
        u = self.redactor.unredact
        d.summary = u(d.summary)
        d.suggested_fixes = [u(f) for f in d.suggested_fixes]
        for e in d.evidence:
            e.quote, e.why = u(e.quote), u(e.why)
        return d


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def validate(
    payload: Any, lines: list[str], retrieved: set[str]
) -> tuple[Diagnosis | None, list[str]]:
    """Parse and check a candidate diagnosis. Returns ``(diagnosis_or_None, errors)``."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            return None, [f"Response was not valid JSON: {exc}"]
    if not isinstance(payload, dict):
        return None, [f"Expected a JSON object, got {type(payload).__name__}."]

    try:
        d = Diagnosis.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - pydantic ValidationError
        return None, [f"Schema validation failed: {exc}"]

    errors: list[str] = []
    n = len(lines)
    for i, ev in enumerate(d.evidence):
        if not (1 <= ev.line_no <= n):
            errors.append(f"evidence[{i}]: line_no {ev.line_no} is outside the log (1..{n}).")
            continue
        if _norm(ev.quote) not in _norm(lines[ev.line_no - 1]):
            errors.append(
                f"evidence[{i}]: quote {ev.quote[:70]!r} does not occur on line {ev.line_no}, "
                f"which reads: {lines[ev.line_no - 1].strip()[:150]!r}"
            )
    for cit in d.kb_citations:
        if cit not in retrieved:
            errors.append(
                f"kb_citations: {cit!r} was not retrieved in this run. "
                f"Retrieved: {sorted(retrieved) or 'nothing'}."
            )
    if d.root_cause is not RootCause.HEALTHY and not d.evidence:
        errors.append(f"root_cause is {d.root_cause.value} but no evidence was cited.")

    return (d if not errors else None), errors


def _fallback(errors: list[str]) -> Diagnosis:
    """What we return when the model could not produce a valid answer twice."""
    return Diagnosis(
        root_cause=RootCause.HEALTHY,
        summary=(
            "The model did not produce a verifiable diagnosis: its citations could not "
            "be confirmed against the log after a retry. Treat this as no result, not "
            "as a clean bill of health."
        ),
        evidence=[],
        confidence=0.0,
        suggested_fixes=["Re-run the diagnosis.", "Inspect the trace to see what was cited."],
        kb_citations=[],
        needs_more_info=True,
    )


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------


def diagnose(
    log: str,
    provider: LLMProvider,
    *,
    mode: str = "agent",
    kb: KnowledgeBase | None = None,
    max_steps: int = MAX_STEPS,
    trace_dir=None,
    trace_enabled: bool = True,
) -> AgentResult:
    """Diagnose one log. ``mode`` is ``"agent"`` or ``"single_shot"``."""
    if mode not in {"agent", "single_shot"}:
        raise ValueError(f"mode must be 'agent' or 'single_shot', got {mode!r}")

    # Redaction happens here, before the text can reach any provider.
    redacted, redactor = redact_log(log)
    lines = split_lines(redacted)
    kb = kb or get_kb()
    ctx = ToolContext.from_log(redacted, kb)

    trace = Trace.start(
        {
            "mode": mode,
            "provider": provider.name,
            "model": provider.model,
            "n_lines": len(lines),
            "max_steps": max_steps,
            "kb_backend": kb.backend,
            "kb_embed_model": kb.model_name,
            "redaction_counts": redactor.summary(),
        },
        out_dir=trace_dir,
        enabled=trace_enabled,
    )

    try:
        if mode == "single_shot":
            diagnosis, attempts, errors, steps = _run_single_shot(provider, lines, ctx, trace)
        else:
            diagnosis, attempts, errors, steps = _run_agent(provider, lines, ctx, trace, max_steps)
    finally:
        pass

    totals = trace.totals
    trace.finish(
        root_cause=diagnosis.root_cause.value,
        confidence=diagnosis.confidence,
        needs_more_info=diagnosis.needs_more_info,
        evidence_lines=[e.line_no for e in diagnosis.evidence],
        kb_citations=diagnosis.kb_citations,
        **totals,
    )

    return AgentResult(
        diagnosis=diagnosis,
        mode=mode,
        steps=steps,
        validation_attempts=attempts,
        valid_first_try=(attempts == 1 and not errors),
        validation_errors=errors,
        retrieved_doc_ids=sorted(ctx.retrieved_doc_ids),
        trace=trace,
        redactor=redactor,
        redacted_log=redacted,
        totals=totals,
    )


def _run_agent(provider, lines, ctx, trace, max_steps):
    messages: list[Message] = [Message(role="user", text=USER_AGENT.format(n_lines=len(lines)))]
    system = SYSTEM_AGENT.format(max_steps=max_steps)
    tools = [*TOOL_SPECS, SUBMIT_TOOL]

    step = 0
    final_args: dict | None = None

    # -- tool phase --------------------------------------------------------
    while step < max_steps:
        step += 1
        resp = provider.generate(system=system, messages=messages, tools=tools)
        trace.llm_call(
            step=step,
            model=provider.model,
            provider=provider.name,
            latency_ms=resp.latency_ms,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            finish=resp.finish,
            mode="auto",
        )
        if not resp.tool_calls:
            messages.append(Message(role="assistant", text=resp.text))
            break

        messages.append(Message(role="assistant", text=resp.text, tool_calls=resp.tool_calls))
        done = False
        for tc in resp.tool_calls:
            if tc.name == SUBMIT_TOOL.name:
                final_args, done = tc.args, True
                break
            result, ms = _run_tool(ctx, tc)
            trace.tool_call(step=step, name=tc.name, args=tc.args, result=result, latency_ms=ms)
            messages.append(
                Message(
                    role="tool",
                    tool_call_id=tc.id or tc.name,
                    tool_name=tc.name,
                    tool_result=result,
                )
            )
        if done:
            break

    # -- forced answer + validation ---------------------------------------
    errors: list[str] = []
    for attempt in range(1, MAX_VALIDATION_ATTEMPTS + 1):
        if final_args is None:
            step += 1
            resp = provider.generate(
                system=system, messages=messages, tools=tools, force_tool=SUBMIT_TOOL.name
            )
            trace.llm_call(
                step=step,
                model=provider.model,
                provider=provider.name,
                latency_ms=resp.latency_ms,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                total_tokens=resp.total_tokens,
                finish=resp.finish,
                mode="forced",
            )
            call = next((c for c in resp.tool_calls if c.name == SUBMIT_TOOL.name), None)
            if call is None:
                errors = ["The model did not call submit_diagnosis."]
                trace.validation(attempt=attempt, ok=False, errors=errors)
                messages.append(Message(role="user", text=RETRY_PREFIX.format(errors=errors[0])))
                continue
            final_args = call.args

        diagnosis, errors = validate(final_args, lines, ctx.retrieved_doc_ids)
        trace.validation(attempt=attempt, ok=diagnosis is not None, errors=errors)
        if diagnosis is not None:
            return diagnosis, attempt, [], step
        if attempt < MAX_VALIDATION_ATTEMPTS:
            messages.append(
                Message(
                    role="assistant",
                    text=None,
                    tool_calls=[ToolCall(name=SUBMIT_TOOL.name, args=final_args, id="final")],
                )
            )
            messages.append(
                Message(
                    role="user",
                    text=RETRY_PREFIX.format(errors="\n".join(f"- {e}" for e in errors)),
                )
            )
            final_args = None

    return _fallback(errors), MAX_VALIDATION_ATTEMPTS, errors, step


def _run_single_shot(provider, lines, ctx, trace):
    """Ablation: no tools, no retrieval, the whole redacted log in one prompt."""
    nums, kept = truncate_for_prompt(lines, SINGLE_SHOT_MAX_LINES)
    note = (
        ""
        if len(kept) == len(lines)
        else f" The log was {len(lines)} lines and has been reduced to {len(kept)}; "
        "line numbers are preserved, so gaps are expected."
    )
    numbered = "\n".join(f"{n:>5}| {kept[i]}" for i, n in enumerate(nums))
    messages = [
        Message(
            role="user", text=USER_SINGLE_SHOT.format(truncation_note=note, numbered_log=numbered)
        )
    ]

    errors: list[str] = []
    for attempt in range(1, MAX_VALIDATION_ATTEMPTS + 1):
        resp = provider.generate(
            system=SYSTEM_SINGLE_SHOT,
            messages=messages,
            response_schema=gemini_function_parameters(),
        )
        trace.llm_call(
            step=attempt,
            model=provider.model,
            provider=provider.name,
            latency_ms=resp.latency_ms,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            finish=resp.finish,
            mode="schema",
        )
        diagnosis, errors = validate(resp.text or "", lines, ctx.retrieved_doc_ids)
        trace.validation(attempt=attempt, ok=diagnosis is not None, errors=errors)
        if diagnosis is not None:
            return diagnosis, attempt, [], attempt
        if attempt < MAX_VALIDATION_ATTEMPTS:
            messages.append(Message(role="assistant", text=resp.text))
            messages.append(
                Message(
                    role="user",
                    text=RETRY_PREFIX.format(errors="\n".join(f"- {e}" for e in errors)),
                )
            )
    return _fallback(errors), MAX_VALIDATION_ATTEMPTS, errors, MAX_VALIDATION_ATTEMPTS


def _run_tool(ctx: ToolContext, tc: ToolCall) -> tuple[dict, float]:
    import time as _t

    t0 = _t.perf_counter()
    result = dispatch(ctx, tc.name, tc.args)
    return result, (_t.perf_counter() - t0) * 1000
