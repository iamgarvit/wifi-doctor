"""The contract between the model and the rest of the system.

Everything the LLM is allowed to return is described here once, and that single
description is used three ways:

* as the JSON Schema handed to Gemini (``response_schema`` in single-shot mode,
  the ``submit_diagnosis`` function parameters in agent mode),
* as the runtime validator for whatever comes back,
* as the type the app and the evaluator program against.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class RootCause(str, Enum):
    """The closed label set the diagnoser must choose from.

    Kept deliberately small and mutually exclusive: every synthetic log in
    ``data/synthetic`` is generated from exactly one of these, so accuracy and
    macro-F1 are well defined.
    """

    WRONG_PASSWORD = "WRONG_PASSWORD"
    HANDSHAKE_TIMEOUT = "HANDSHAKE_TIMEOUT"
    AUTH_TIMEOUT = "AUTH_TIMEOUT"
    ASSOC_REJECTED = "ASSOC_REJECTED"
    AP_DEAUTH = "AP_DEAUTH"
    EAP_FAILURE = "EAP_FAILURE"
    DHCP_TIMEOUT = "DHCP_TIMEOUT"
    BEACON_LOSS_WEAK_SIGNAL = "BEACON_LOSS_WEAK_SIGNAL"
    ROAMING_FAILURE = "ROAMING_FAILURE"
    NETWORK_NOT_FOUND = "NETWORK_NOT_FOUND"
    HEALTHY = "HEALTHY"


ALL_ROOT_CAUSES: list[str] = [rc.value for rc in RootCause]


class Evidence(BaseModel):
    """One citation into the log.

    ``line_no`` is 1-based and ``quote`` must be a substring of that line. Both
    are checked against the real log in :mod:`wifi_doctor.agent`, which is what
    turns "the model said so" into "the model pointed at a line that exists".
    """

    line_no: int = Field(description="1-based line number in the log being diagnosed.")
    quote: str = Field(description="Verbatim text copied from that line.")
    why: str = Field(description="One sentence: why this line supports the diagnosis.")

    @field_validator("quote", "why")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v


class Diagnosis(BaseModel):
    """The final answer. This is the only shape the agent is allowed to return."""

    root_cause: RootCause
    summary: str = Field(description="2-3 sentences a support engineer can read aloud.")
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Log lines that justify the root cause. Empty only for HEALTHY.",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_fixes: list[str] = Field(
        default_factory=list, description="Concrete, ordered remediation steps."
    )
    kb_citations: list[str] = Field(
        default_factory=list,
        description="Knowledge-base doc ids used, e.g. 'reason-codes'. Must have been retrieved this run.",
    )
    needs_more_info: bool = Field(
        default=False,
        description="True when the log is insufficient, or when validation failed twice.",
    )

    model_config = {"use_enum_values": False}


def gemini_function_parameters() -> dict:
    """JSON Schema for the ``submit_diagnosis`` tool / ``response_schema``.

    Pydantic's own ``model_json_schema()`` emits ``$defs``/``$ref`` and
    ``anyOf``, which the Gemini schema dialect does not accept, so the shape is
    spelled out flat here. It is covered by a test that keeps it in sync with
    :class:`Diagnosis`.
    """
    return {
        "type": "object",
        "properties": {
            "root_cause": {"type": "string", "enum": ALL_ROOT_CAUSES},
            "summary": {"type": "string"},
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "line_no": {"type": "integer"},
                        "quote": {"type": "string"},
                        "why": {"type": "string"},
                    },
                    "required": ["line_no", "quote", "why"],
                },
            },
            "confidence": {"type": "number"},
            "suggested_fixes": {"type": "array", "items": {"type": "string"}},
            "kb_citations": {"type": "array", "items": {"type": "string"}},
            "needs_more_info": {"type": "boolean"},
        },
        "required": [
            "root_cause",
            "summary",
            "evidence",
            "confidence",
            "suggested_fixes",
            "kb_citations",
            "needs_more_info",
        ],
    }
