"""The output contract, and the flat JSON Schema handed to the provider."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from wifi_doctor.schema import (
    ALL_ROOT_CAUSES,
    Diagnosis,
    Evidence,
    RootCause,
    gemini_function_parameters,
)


def _valid() -> dict:
    return {
        "root_cause": "WRONG_PASSWORD",
        "summary": "The passphrase is wrong.",
        "evidence": [{"line_no": 3, "quote": "reason=WRONG_KEY", "why": "explicit verdict"}],
        "confidence": 0.9,
        "suggested_fixes": ["Re-enter the passphrase."],
        "kb_citations": ["troubleshoot-wrong-password"],
        "needs_more_info": False,
    }


def test_valid_payload_parses():
    d = Diagnosis.model_validate(_valid())
    assert d.root_cause is RootCause.WRONG_PASSWORD
    assert d.evidence[0].line_no == 3


def test_unknown_root_cause_rejected():
    bad = _valid() | {"root_cause": "COSMIC_RAYS"}
    with pytest.raises(ValidationError):
        Diagnosis.model_validate(bad)


@pytest.mark.parametrize("conf", [-0.1, 1.5])
def test_confidence_bounds(conf):
    with pytest.raises(ValidationError):
        Diagnosis.model_validate(_valid() | {"confidence": conf})


def test_empty_quote_rejected():
    with pytest.raises(ValidationError):
        Evidence(line_no=1, quote="   ", why="x")


def test_defaults_allow_a_minimal_healthy_answer():
    d = Diagnosis(root_cause=RootCause.HEALTHY, summary="All good.", confidence=0.8)
    assert d.evidence == [] and d.kb_citations == [] and d.needs_more_info is False


def test_function_parameters_cover_every_field_and_stay_gemini_safe():
    schema = gemini_function_parameters()
    assert set(schema["properties"]) == set(Diagnosis.model_fields)
    assert set(schema["required"]) == set(Diagnosis.model_fields)
    assert schema["properties"]["root_cause"]["enum"] == ALL_ROOT_CAUSES
    # Gemini's schema dialect does not accept $ref/$defs/anyOf, which is why the
    # schema is spelled out flat instead of using model_json_schema().
    blob = repr(schema)
    for banned in ("$ref", "$defs", "anyOf", "allOf"):
        assert banned not in blob


def test_evidence_item_schema_matches_the_model():
    item = gemini_function_parameters()["properties"]["evidence"]["items"]
    assert set(item["properties"]) == set(Evidence.model_fields)
