"""The tools the model may call, and the registry that describes them.

Design rule: **a tool never returns free prose.** Each one returns a compact,
structured, line-numbered view of something the model cannot see otherwise. The
model has no access to the raw log at all in agent mode — it can only reach it
through ``search_log`` and ``get_timeline``, which is what forces it to cite
line numbers that actually exist.

Each tool is a plain Python function plus a JSON Schema description. The schema
is provider-neutral; :mod:`wifi_doctor.llm` translates it into whatever each
API wants.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .logparse import ctrl_events, find, min_signal, split_lines, transitions
from .retrieval import KnowledgeBase, load_code_table

MAX_HITS_CAP = 40
MAX_KB_K = 5


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., dict]


@dataclass
class ToolContext:
    """Per-run state a tool needs: the (already redacted) log and the KB.

    ``retrieved_doc_ids`` accumulates every doc the model was actually shown.
    The agent uses it to reject citations of documents that were never
    retrieved, which is the cheapest possible defence against invented sources.
    """

    redacted_lines: list[str]
    kb: KnowledgeBase
    retrieved_doc_ids: set[str] = field(default_factory=set)

    @classmethod
    def from_log(cls, redacted_log: str, kb: KnowledgeBase) -> ToolContext:
        return cls(redacted_lines=split_lines(redacted_log), kb=kb)


# --------------------------------------------------------------------------
# tool implementations
# --------------------------------------------------------------------------


def search_log(ctx: ToolContext, pattern: str, max_hits: int = 10) -> dict:
    """Regex search over the log."""
    max_hits = max(1, min(int(max_hits or 10), MAX_HITS_CAP))
    hits = find(ctx.redacted_lines, pattern, max_hits=max_hits)
    return {
        "pattern": pattern,
        "total_lines": len(ctx.redacted_lines),
        "returned": len(hits),
        "truncated": len(hits) >= max_hits,
        "matches": [{"line_no": n, "text": t} for n, t in hits],
    }


def get_timeline(ctx: ToolContext) -> dict:
    """Parsed supplicant state transitions plus every CTRL-EVENT line."""
    lines = ctx.redacted_lines
    trans = transitions(lines)
    events = ctrl_events(lines)
    return {
        "total_lines": len(lines),
        "states": [{"line_no": t.line_no, "from": t.frm, "to": t.to} for t in trans],
        "furthest_state": _furthest_state(trans),
        "final_state": trans[-1].to if trans else None,
        "control_events": [
            {"line_no": n, "event": ev, "text": text} for n, ev, text in events[:120]
        ],
        "control_events_truncated": len(events) > 120,
        "min_signal_dbm": min_signal(lines),
    }


# Rough progress order of the supplicant state machine, used only to report how
# far the client got. See kb/supplicant-state-machine.md.
_STATE_ORDER = [
    "DISCONNECTED",
    "INACTIVE",
    "SCANNING",
    "AUTHENTICATING",
    "ASSOCIATING",
    "ASSOCIATED",
    "4WAY_HANDSHAKE",
    "GROUP_HANDSHAKE",
    "COMPLETED",
]


def _furthest_state(trans) -> str | None:
    best, best_i = None, -1
    for t in trans:
        for s in (t.frm, t.to):
            if s in _STATE_ORDER and _STATE_ORDER.index(s) > best_i:
                best, best_i = s, _STATE_ORDER.index(s)
    return best


def lookup_code(ctx: ToolContext, kind: str, code: int) -> dict:
    """Look up an IEEE 802.11 reason or status code in the knowledge base."""
    kind = (kind or "").strip().lower()
    if kind not in {"reason", "status"}:
        return {"error": "kind must be 'reason' or 'status'"}
    try:
        code = int(code)
    except (TypeError, ValueError):
        return {"error": f"code must be an integer, got {code!r}"}
    table = load_code_table(kind, ctx.kb.kb_dir)
    doc_id = f"{kind}-codes"
    ctx.retrieved_doc_ids.add(doc_id)
    meaning = table.get(code)
    return {
        "kind": kind,
        "code": code,
        "meaning": meaning,
        "found": meaning is not None,
        "doc_id": doc_id,
        "source": "IEEE 802.11-2020 Table 9-49 (Reason codes)"
        if kind == "reason"
        else "IEEE 802.11-2020 Table 9-50 (Status codes)",
        "known_codes": sorted(table) if meaning is None else None,
    }


def retrieve_kb(ctx: ToolContext, query: str, k: int = 3) -> dict:
    """Hybrid BM25 + embedding search over the knowledge base."""
    k = max(1, min(int(k or 3), MAX_KB_K))
    hits = ctx.kb.search(query, k=k)
    for h in hits:
        ctx.retrieved_doc_ids.add(h.chunk.doc_id)
    return {
        "query": query,
        "backend": ctx.kb.backend,
        "results": [
            {
                "doc_id": h.chunk.doc_id,
                "section": h.chunk.heading or None,
                "score": h.score,
                "snippet": h.snippet(),
            }
            for h in hits
        ],
    }


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="search_log",
        description=(
            "Search the log with a Python regular expression. Returns matching lines with "
            "their 1-based line numbers. Use this to find specific events, e.g. "
            "'CTRL-EVENT-ASSOC-REJECT', 'EAPOL-Key timeout', 'signal=-\\\\d+'. "
            "Case-insensitive. Invalid regexes fall back to a literal substring search."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression to search for."},
                "max_hits": {
                    "type": "integer",
                    "description": f"Maximum matches to return (1-{MAX_HITS_CAP}, default 10).",
                },
            },
            "required": ["pattern"],
        },
        fn=search_log,
    ),
    ToolSpec(
        name="get_timeline",
        description=(
            "Return the parsed wpa_supplicant state transitions and every CTRL-EVENT line, "
            "each with its 1-based line number, plus the furthest state reached and the "
            "weakest reported signal. Call this first: the furthest state bounds which "
            "root causes are possible at all."
        ),
        parameters={"type": "object", "properties": {}},
        fn=get_timeline,
    ),
    ToolSpec(
        name="lookup_code",
        description=(
            "Look up the meaning of an IEEE 802.11 reason code (from a deauth/disassoc, "
            "e.g. 'reason=15') or status code (from an auth/assoc response, e.g. "
            "'status_code=17'). Reason and status codes are different tables: the same "
            "number means different things, so pass the right kind."
        ),
        parameters={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["reason", "status"]},
                "code": {"type": "integer"},
            },
            "required": ["kind", "code"],
        },
        fn=lookup_code,
    ),
    ToolSpec(
        name="retrieve_kb",
        description=(
            "Search the Wi-Fi knowledge base (802.11 mechanics, the supplicant state "
            "machine, and a troubleshooting note per failure class). Returns doc ids and "
            "snippets. Only doc ids returned here may appear in kb_citations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language question."},
                "k": {
                    "type": "integer",
                    "description": f"How many snippets (1-{MAX_KB_K}, default 3).",
                },
            },
            "required": ["query"],
        },
        fn=retrieve_kb,
    ),
]

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOL_SPECS}


def dispatch(ctx: ToolContext, name: str, args: dict) -> dict:
    """Run a tool by name. Never raises: the model sees errors as tool output.

    A tool crash must not end the run — the model can usually recover from
    "your regex was invalid" on the next step, and an exception here would
    throw away every step taken so far.
    """
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        return {"error": f"unknown tool {name!r}", "available": sorted(TOOLS_BY_NAME)}
    allowed = set(spec.parameters.get("properties", {}))
    clean = {k: v for k, v in (args or {}).items() if k in allowed}
    missing = set(spec.parameters.get("required", [])) - set(clean)
    if missing:
        return {"error": f"missing required argument(s): {sorted(missing)}"}
    try:
        return spec.fn(ctx, **clean)
    except Exception as exc:  # noqa: BLE001 - deliberately surfaced to the model
        return {"error": f"{type(exc).__name__}: {exc}"}
