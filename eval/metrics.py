"""Scoring and report rendering for the evaluation harness.

Definitions are spelled out here rather than inherited from a library, because
the interesting choices are in the definitions:

* **Evidence precision / recall** are computed over *line numbers*, micro
  averaged across cases that have ground-truth evidence at all. ``HEALTHY``
  cases have an empty truth set, so recall is undefined for them and they are
  excluded from the evidence figures (they are scored separately by the
  false-alarm rate).
* **Hallucinated evidence** means a citation that does **not verify against the
  log** — the line number is out of range, or the quote does not occur on that
  line. It does *not* mean "cited a line that was not in the ground truth";
  that is simply low precision. Because the agent validates before returning,
  the final-output figure is expected to be near zero, so the pre-validation
  figure (how often the model *tried* to hallucinate, recovered by the retry)
  is reported alongside it.
* **Macro-F1** averages per-class F1 over all classes present in the ground
  truth, giving a rare class the same weight as a common one.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from wifi_doctor.schema import ALL_ROOT_CAUSES


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


@dataclass
class CaseResult:
    """One (mode, case) outcome, as persisted to the resume cache."""

    case_id: str
    mode: str
    truth: str
    predicted: str
    truth_lines: list[int]
    cited_lines: list[int]
    unverifiable_citations: int
    n_citations: int
    confidence: float
    needs_more_info: bool
    valid_first_try: bool
    produced_valid_output: bool
    pre_validation_evidence_errors: int
    steps: int
    api_requests: int
    total_tokens: int
    wall_ms: float
    llm_latency_ms: float
    variant: str = "plain"
    trace_path: str | None = None
    error: str | None = None

    @property
    def correct(self) -> bool:
        return self.predicted == self.truth


def _verifiable(ev, lines: list[str]) -> bool:
    """True when the cited line exists and the quote really occurs on it."""
    if not (1 <= ev.line_no <= len(lines)):
        return False
    return _norm(ev.quote) in _norm(lines[ev.line_no - 1])


def verify_citations(evidence, lines: list[str]) -> int:
    """Count citations that cannot be checked against the log."""
    return sum(1 for ev in evidence if not _verifiable(ev, lines))


# --------------------------------------------------------------------------
# aggregate metrics
# --------------------------------------------------------------------------


def confusion(results: list[CaseResult], labels: list[str]) -> list[list[int]]:
    """``m[i][j]`` = truth ``labels[i]`` predicted as ``labels[j]``."""
    idx = {lab: i for i, lab in enumerate(labels)}
    m = [[0] * len(labels) for _ in labels]
    for r in results:
        if r.truth in idx and r.predicted in idx:
            m[idx[r.truth]][idx[r.predicted]] += 1
    return m


def per_class(results: list[CaseResult], labels: list[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for lab in labels:
        tp = sum(1 for r in results if r.truth == lab and r.predicted == lab)
        fp = sum(1 for r in results if r.truth != lab and r.predicted == lab)
        fn = sum(1 for r in results if r.truth == lab and r.predicted != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[lab] = {"support": tp + fn, "precision": prec, "recall": rec, "f1": f1}
    return out


def _mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    """All headline numbers for one mode."""
    if not results:
        return {}
    labels = [lab for lab in ALL_ROOT_CAUSES if any(r.truth == lab for r in results)]
    pc = per_class(results, labels)
    n = len(results)

    with_truth = [r for r in results if r.truth_lines]
    tp = sum(len(set(r.cited_lines) & set(r.truth_lines)) for r in with_truth)
    n_cited = sum(len(set(r.cited_lines)) for r in with_truth)
    n_truth = sum(len(set(r.truth_lines)) for r in with_truth)

    healthy = [r for r in results if r.truth == "HEALTHY"]
    faulty = [r for r in results if r.truth != "HEALTHY"]

    walls = [r.wall_ms for r in results]
    return {
        "n_cases": n,
        "accuracy": _mean(r.correct for r in results),
        "macro_f1": _mean(pc[lab]["f1"] for lab in labels),
        "per_class": pc,
        "confusion": {"labels": labels, "matrix": confusion(results, labels)},
        "evidence": {
            "n_cases_scored": len(with_truth),
            "precision": tp / n_cited if n_cited else 0.0,
            "recall": tp / n_truth if n_truth else 0.0,
            "mean_citations_per_case": _mean(len(r.cited_lines) for r in with_truth),
            "hallucinated_rate_final": (
                sum(r.unverifiable_citations for r in results)
                / max(1, sum(r.n_citations for r in results))
            ),
            "cases_with_pre_validation_evidence_error": _mean(
                r.pre_validation_evidence_errors > 0 for r in results
            ),
        },
        "healthy": {
            "n_healthy": len(healthy),
            "false_alarm_rate": _mean(r.predicted != "HEALTHY" for r in healthy),
            "n_faulty": len(faulty),
            "missed_failure_rate": _mean(r.predicted == "HEALTHY" for r in faulty),
        },
        "schema": {
            "valid_first_try": _mean(r.valid_first_try for r in results),
            "valid_after_retry": _mean(r.produced_valid_output for r in results),
        },
        "cost": {
            "mean_api_requests": _mean(r.api_requests for r in results),
            "mean_total_tokens": _mean(r.total_tokens for r in results),
            "mean_steps": _mean(r.steps for r in results),
            "mean_wall_ms": _mean(walls),
            "median_wall_ms": statistics.median(walls),
            "mean_llm_latency_ms": _mean(r.llm_latency_ms for r in results),
            "total_api_requests": sum(r.api_requests for r in results),
            "total_tokens": sum(r.total_tokens for r in results),
        },
        "by_variant": {
            v: {"n": len(rs), "accuracy": _mean(r.correct for r in rs)}
            for v in sorted({r.variant for r in results})
            if (rs := [r for r in results if r.variant == v])
        },
        "mean_confidence_correct": _mean(r.confidence for r in results if r.correct),
        "mean_confidence_wrong": _mean(r.confidence for r in results if not r.correct),
        "needs_more_info_rate": _mean(r.needs_more_info for r in results),
        "errors": [r.case_id for r in results if r.error],
    }


def worst_failures(results: list[CaseResult], k: int = 5) -> list[CaseResult]:
    """The k most damaging mistakes: wrong, and confidently so."""
    wrong = [r for r in results if not r.correct]
    wrong.sort(key=lambda r: (-r.confidence, r.case_id))
    return wrong[:k]


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def confusion_png(matrix: list[list[int]], labels: list[str], path, title: str) -> bool:
    """Render a confusion matrix. Returns False if matplotlib is unavailable."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # pragma: no cover - optional dependency
        return False

    n = len(labels)
    fig, ax = plt.subplots(figsize=(max(6.0, n * 0.62), max(5.0, n * 0.56)), dpi=160)
    ax.imshow(matrix, cmap="Blues", vmin=0)
    ax.set_xticks(range(n), labels, rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(n), labels, fontsize=7)
    ax.set_xlabel("predicted", fontsize=8)
    ax.set_ylabel("true", fontsize=8)
    ax.set_title(title, fontsize=9)
    hi = max((v for row in matrix for v in row), default=1) or 1
    for i in range(n):
        for j in range(n):
            v = matrix[i][j]
            if v:
                ax.text(
                    j,
                    i,
                    str(v),
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="white" if v > hi * 0.6 else "black",
                )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return True


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render_report(
    meta: dict,
    per_mode: dict[str, dict],
    worst: dict[str, list[CaseResult]],
    images: dict[str, str],
) -> str:
    """The human-readable markdown report."""
    modes = list(per_mode)
    L: list[str] = []
    a = L.append

    a(f"# wifi-doctor evaluation — {meta['split']} split\n")
    a(f"- **Date (UTC):** {meta['date']}")
    a(f"- **Provider / model:** `{meta['provider']}` / `{meta['model']}`")
    a(f"- **Cases:** {meta['n_cases']} from `{meta['cases_path']}`")
    a(
        f"- **Retrieval backend:** {meta['kb_backend']}"
        + (f" (`{meta['kb_embed_model']}`)" if meta.get("kb_embed_model") else "")
    )
    a(f"- **Agent max tool steps:** {meta['max_steps']}")
    a(f"- **Total API requests this run:** {meta['total_api_requests']}")
    a(
        "\n> The test split was never used to tune prompts or rules. Every number below "
        "was produced by `eval/run_eval.py`; nothing is estimated.\n"
    )

    a("## Headline\n")
    a("| metric | " + " | ".join(f"`{m}`" for m in modes) + " |")
    a("|---|" + "---|" * len(modes))

    def row(label: str, fn):
        a(f"| {label} | " + " | ".join(fn(per_mode[m]) for m in modes) + " |")

    row("root-cause accuracy", lambda s: _pct(s["accuracy"]))
    row("macro-F1", lambda s: f"{s['macro_f1']:.3f}")
    row("evidence precision", lambda s: _pct(s["evidence"]["precision"]))
    row("evidence recall", lambda s: _pct(s["evidence"]["recall"]))
    row("hallucinated evidence (final)", lambda s: _pct(s["evidence"]["hallucinated_rate_final"]))
    row("HEALTHY false-alarm rate", lambda s: _pct(s["healthy"]["false_alarm_rate"]))
    row("missed-failure rate", lambda s: _pct(s["healthy"]["missed_failure_rate"]))
    row("schema-valid first try", lambda s: _pct(s["schema"]["valid_first_try"]))
    row("schema-valid after retry", lambda s: _pct(s["schema"]["valid_after_retry"]))
    row("API requests / log", lambda s: f"{s['cost']['mean_api_requests']:.2f}")
    row("tokens / log", lambda s: f"{s['cost']['mean_total_tokens']:,.0f}")
    row("mean latency / log", lambda s: f"{s['cost']['mean_wall_ms'] / 1000:.2f}s")
    row("median latency / log", lambda s: f"{s['cost']['median_wall_ms'] / 1000:.2f}s")
    a("")

    a("### How to read these\n")
    a(
        "- **Evidence precision/recall** are over cited line numbers vs the generator's "
        "ground-truth lines, micro-averaged over the non-`HEALTHY` cases (a `HEALTHY` case "
        "has no ground-truth evidence, so recall is undefined for it)."
    )
    a(
        "- **Hallucinated evidence (final)** is the share of returned citations whose line "
        "number is out of range or whose quote does not occur on the cited line. The agent "
        "validates before returning, so this measures what survived validation, not what "
        "the model first attempted."
    )
    a(
        "- **`baseline`** is the regex rule engine in `src/wifi_doctor/baseline.py`. It makes "
        "no API calls, does no retrieval, and cites no knowledge-base documents by "
        "construction.\n"
    )

    for m in modes:
        s = per_mode[m]
        a(f"## Mode: `{m}`\n")
        if img := images.get(m):
            a(f"![confusion matrix — {m}]({img})\n")
        a("| class | support | precision | recall | F1 |")
        a("|---|---|---|---|---|")
        for lab, v in s["per_class"].items():
            a(
                f"| {lab} | {int(v['support'])} | {v['precision']:.2f} | "
                f"{v['recall']:.2f} | {v['f1']:.2f} |"
            )
        a("")
        a(
            "Accuracy by difficulty variant: "
            + ", ".join(
                f"`{v}` {_pct(d['accuracy'])} (n={d['n']})" for v, d in s["by_variant"].items()
            )
            + "\n"
        )
        a(
            f"Mean confidence when correct **{s['mean_confidence_correct']:.2f}**, "
            f"when wrong **{s['mean_confidence_wrong']:.2f}**; "
            f"`needs_more_info` set on {_pct(s['needs_more_info_rate'])} of cases.\n"
        )
        a("### 5 worst failures (wrong, ranked by how confident it was)\n")
        w = worst.get(m, [])
        if not w:
            a("_None — every case was classified correctly._\n")
        else:
            a("| case | variant | truth | predicted | conf | trace |")
            a("|---|---|---|---|---|---|")
            for r in w:
                t = f"`{r.trace_path}`" if r.trace_path else "—"
                a(
                    f"| `{r.case_id}` | {r.variant} | {r.truth} | {r.predicted} | "
                    f"{r.confidence:.2f} | {t} |"
                )
            a("")

    a("## Reproducing\n")
    a("```bash")
    a(meta["command"])
    a("```")
    return "\n".join(L) + "\n"
