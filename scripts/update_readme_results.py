#!/usr/bin/env python3
"""Inject the results table into README.md straight from a real metrics.json.

The README must never contain a number that was not produced by
``eval/run_eval.py``. Rather than trusting a human to copy them across, the
table lives between two markers and is regenerated from the run's own
``metrics.json``:

    python scripts/update_readme_results.py results/<run>/metrics.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- RESULTS:START -->"
END = "<!-- RESULTS:END -->"

ROWS = [
    ("root-cause accuracy", lambda s: f"{100 * s['accuracy']:.1f}%"),
    ("macro-F1", lambda s: f"{s['macro_f1']:.3f}"),
    ("evidence precision", lambda s: f"{100 * s['evidence']['precision']:.1f}%"),
    ("evidence recall", lambda s: f"{100 * s['evidence']['recall']:.1f}%"),
    ("hallucinated evidence", lambda s: f"{100 * s['evidence']['hallucinated_rate_final']:.1f}%"),
    ("HEALTHY false-alarm rate", lambda s: f"{100 * s['healthy']['false_alarm_rate']:.1f}%"),
    ("missed-failure rate", lambda s: f"{100 * s['healthy']['missed_failure_rate']:.1f}%"),
    ("schema-valid, first try", lambda s: f"{100 * s['schema']['valid_first_try']:.1f}%"),
    ("schema-valid, after retry", lambda s: f"{100 * s['schema']['valid_after_retry']:.1f}%"),
    ("API requests / log", lambda s: f"{s['cost']['mean_api_requests']:.2f}"),
    ("tokens / log", lambda s: f"{s['cost']['mean_total_tokens']:,.0f}"),
    ("median latency / log", lambda s: f"{s['cost']['median_wall_ms'] / 1000:.1f}s"),
]

PRETTY = {"baseline": "rule baseline", "single_shot": "single-shot", "agent": "agent"}


def build_table(data: dict) -> str:
    meta, modes = data["meta"], data["modes"]
    names = [m for m in ("baseline", "single_shot", "agent") if m in modes]
    lines = [
        f"Provider **{meta['provider']}**, model **`{meta['model']}`**, "
        f"run on **{meta['date']}** against the held-out **{meta['split']}** split "
        f"({meta['n_cases']} logs, {meta['total_api_requests']} API requests). "
        f"Retrieval backend: {meta['kb_backend']}"
        + (f" (`{meta['kb_embed_model']}`)." if meta.get("kb_embed_model") else "."),
        "",
        "| metric | " + " | ".join(PRETTY[m] for m in names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for label, fn in ROWS:
        lines.append(f"| {label} | " + " | ".join(fn(modes[m]) for m in names) + " |")
    lines += [
        "",
        f"Full report with per-class breakdowns, confusion matrices and the worst failures: "
        f"[`{meta['run_dir']}/report.md`]({meta['run_dir']}/report.md).",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("metrics", type=Path)
    ap.add_argument("--readme", type=Path, default=ROOT / "README.md")
    args = ap.parse_args()

    data = json.loads(args.metrics.read_text())
    data["meta"]["run_dir"] = str(args.metrics.parent.relative_to(ROOT))

    text = args.readme.read_text()
    if START not in text or END not in text:
        raise SystemExit(f"{args.readme} is missing the {START} / {END} markers")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    args.readme.write_text(f"{head}{START}\n{build_table(data)}\n{END}{tail}")
    print(f"updated {args.readme.name} from {args.metrics}")


if __name__ == "__main__":
    main()
