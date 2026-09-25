"""Shared fixtures. Every test here runs offline: no API key, no model download."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Must be set before wifi_doctor.retrieval decides whether to build a dense
# index, so the whole suite stays offline and fast.
os.environ.setdefault("WIFI_DOCTOR_EMBEDDINGS", "0")

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def dev_cases() -> list[dict]:
    path = ROOT / "data" / "synthetic" / "dev" / "cases.jsonl"
    if not path.exists():
        pytest.skip("run scripts/generate_logs.py first")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture(scope="session")
def case_by_label(dev_cases) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in dev_cases:
        out.setdefault(c["root_cause"], c)
    return out


@pytest.fixture(scope="session")
def kb():
    from wifi_doctor.retrieval import KnowledgeBase

    return KnowledgeBase(use_embeddings=False)
