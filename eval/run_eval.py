#!/usr/bin/env python3
"""Run the evaluation and write metrics, a markdown report and confusion matrices.

    python eval/run_eval.py --split test --modes baseline single_shot agent \
        --provider gemini --model gemini-3.5-flash-lite

Free-tier discipline is built in:

* the number of API requests is **estimated and printed before anything is
  sent**, and the run refuses to start if it would not fit in the remaining
  daily budget (override with ``--yes``, or shrink it with ``--limit``);
* every finished case is cached under ``<run>/cache/``, so an interrupted run
  resumes exactly where it stopped and never pays for the same log twice;
* a client-side rate limiter paces requests and backs off on 429s.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import (  # noqa: E402
    CaseResult,
    confusion_png,
    render_report,
    summarize,
    verify_citations,
    worst_failures,
)

from wifi_doctor.agent import MAX_STEPS, diagnose  # noqa: E402
from wifi_doctor.baseline import classify  # noqa: E402
from wifi_doctor.config import ROOT, VERIFIED_FREE_TIER_RPD, get_settings  # noqa: E402
from wifi_doctor.llm import RateLimitError, build_provider  # noqa: E402
from wifi_doctor.logparse import split_lines  # noqa: E402
from wifi_doctor.ratelimit import DailyQuotaExceeded, RateLimiter  # noqa: E402
from wifi_doctor.redact import redact_log  # noqa: E402
from wifi_doctor.retrieval import KnowledgeBase  # noqa: E402

MODES = ("baseline", "single_shot", "agent")
# Mean API requests per log, used only for the pre-flight estimate. The agent
# figure allows for the forced final call plus the occasional validation retry.
EST_REQUESTS = {"baseline": 0.0, "single_shot": 1.15, "agent": 6.5}


def _rel(path: Path) -> str:
    """Display a path relative to the repo root when it is inside it."""
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def load_cases(split: str, limit: int | None) -> tuple[list[dict], Path]:
    path = ROOT / "data" / "synthetic" / split / "cases.jsonl"
    if not path.exists():
        raise SystemExit(f"no cases at {path}; run `python scripts/generate_logs.py` first")
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return (cases[:limit] if limit else cases), path


def run_baseline(case: dict) -> CaseResult:
    lines = split_lines(case["log"])
    t0 = time.perf_counter()
    d = classify(case["log"])
    wall = (time.perf_counter() - t0) * 1000
    return CaseResult(
        case_id=case["id"],
        mode="baseline",
        truth=case["root_cause"],
        predicted=d.root_cause.value,
        truth_lines=case["evidence_lines"],
        cited_lines=[e.line_no for e in d.evidence],
        unverifiable_citations=verify_citations(d.evidence, lines),
        n_citations=len(d.evidence),
        confidence=d.confidence,
        needs_more_info=d.needs_more_info,
        valid_first_try=True,
        produced_valid_output=True,
        pre_validation_evidence_errors=0,
        steps=0,
        api_requests=0,
        total_tokens=0,
        wall_ms=wall,
        llm_latency_ms=0.0,
        variant=case.get("variant", "plain"),
    )


def run_llm(case: dict, mode: str, provider, kb, trace_dir: Path, max_steps: int) -> CaseResult:
    # The agent redacts internally; redact again here only to score citations
    # against exactly the text the model saw.
    redacted, _ = redact_log(case["log"])
    lines = split_lines(redacted)
    t0 = time.perf_counter()
    err = None
    try:
        res = diagnose(
            case["log"],
            provider,
            mode=mode,
            kb=kb,
            max_steps=max_steps,
            trace_dir=trace_dir,
            trace_name=case["id"],
        )
        d = res.diagnosis
        pre_errors = sum(
            1
            for e in res.trace.events
            if e["kind"] == "validation" and not e["ok"]
            for msg in e["errors"]
            if msg.startswith("evidence[")
        )
        return CaseResult(
            case_id=case["id"],
            mode=mode,
            truth=case["root_cause"],
            predicted=d.root_cause.value,
            truth_lines=case["evidence_lines"],
            cited_lines=[e.line_no for e in d.evidence],
            unverifiable_citations=verify_citations(d.evidence, lines),
            n_citations=len(d.evidence),
            confidence=d.confidence,
            needs_more_info=d.needs_more_info,
            valid_first_try=res.valid_first_try,
            produced_valid_output=not res.validation_errors,
            pre_validation_evidence_errors=pre_errors,
            steps=res.steps,
            api_requests=res.totals["api_requests"],
            total_tokens=res.totals["total_tokens"],
            wall_ms=res.totals["wall_ms"],
            llm_latency_ms=res.totals["llm_latency_ms"],
            variant=case.get("variant", "plain"),
            trace_path=_rel(res.trace.path) if res.trace.path else None,
        )
    except (DailyQuotaExceeded, RateLimitError):
        # Out of quota (local budget, or the provider's own 429 after backoff):
        # stop rather than cache a quota error as if it were the model's answer.
        raise
    except Exception as exc:  # noqa: BLE001 - one bad case must not lose the run
        err = f"{type(exc).__name__}: {exc}"
        print(f"    !! {case['id']}: {err}", flush=True)
        return CaseResult(
            case_id=case["id"],
            mode=mode,
            truth=case["root_cause"],
            predicted="HEALTHY",
            truth_lines=case["evidence_lines"],
            cited_lines=[],
            unverifiable_citations=0,
            n_citations=0,
            confidence=0.0,
            needs_more_info=True,
            valid_first_try=False,
            produced_valid_output=False,
            pre_validation_evidence_errors=0,
            steps=0,
            api_requests=0,
            total_tokens=0,
            wall_ms=(time.perf_counter() - t0) * 1000,
            llm_latency_ms=0.0,
            variant=case.get("variant", "plain"),
            error=err,
        )


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--split", default="test", choices=["dev", "test"])
    ap.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    ap.add_argument("--provider", default=None, help="gemini | groq | mock")
    ap.add_argument("--model", default=None)
    ap.add_argument("--limit", type=int, default=None, help="only the first N cases")
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--rpm", type=int, default=None, help="override LLM_RPM")
    ap.add_argument("--rpd", type=int, default=None, help="override LLM_RPD")
    ap.add_argument(
        "--no-resume", action="store_true", help="ignore the cache and re-run everything"
    )
    ap.add_argument(
        "--yes", action="store_true", help="run even if the estimate exceeds the daily budget"
    )
    args = ap.parse_args()

    settings = get_settings(args.provider, args.model)
    needs_api = any(m != "baseline" for m in args.modes)
    if needs_api and not settings.has_key:
        raise SystemExit(
            f"no API key for provider {settings.provider!r}. Put it in .env "
            f"(see .env.example), or run with --modes baseline."
        )

    cases, cases_path = load_cases(args.split, args.limit)
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-zA-Z0-9.-]+", "-", settings.model)
    suffix = "" if args.split == "test" else f"_{args.split}"
    run_dir = args.out or (ROOT / "results" / f"{date}_{settings.provider}_{slug}{suffix}")
    (run_dir / "cache").mkdir(parents=True, exist_ok=True)

    # The mock provider makes no network calls, so pacing it would only waste
    # wall-clock time in CI.
    limiter = (
        None
        if settings.provider == "mock"
        else RateLimiter(settings.provider, args.rpm or settings.rpm, args.rpd or settings.rpd)
    )

    # -- pre-flight --------------------------------------------------------
    cached = {
        m: sum(1 for c in cases if (run_dir / "cache" / m / f"{c['id']}.json").exists())
        for m in args.modes
    }
    todo = {m: len(cases) - (0 if args.no_resume else cached[m]) for m in args.modes}
    estimate = round(sum(EST_REQUESTS[m] * todo[m] for m in args.modes))

    print(f"\nwifi-doctor eval — split={args.split} cases={len(cases)} modes={args.modes}")
    print(f"  provider={settings.provider} model={settings.model}")
    print(f"  run dir: {_rel(run_dir)}")
    if not args.no_resume and any(cached.values()):
        print(
            "  resuming: " + ", ".join(f"{m} {cached[m]}/{len(cases)} cached" for m in args.modes)
        )
    ceiling = VERIFIED_FREE_TIER_RPD.get(settings.provider)
    if args.rpd and ceiling and args.rpd > ceiling:
        print(
            f"  WARNING: --rpd {args.rpd} is above the verified free-tier ceiling for "
            f"{settings.provider} ({ceiling}/day). The client-side limiter will not stop the "
            f"run, so it will fail mid-way with server-side 429s instead. Prefer --limit."
        )
    ok, msg = (
        (True, f"{estimate} requests planned (mock provider: no network)")
        if limiter is None
        else limiter.estimate_fits(estimate)
    )
    print(f"  ESTIMATE: {msg}")
    if needs_api and not ok and not args.yes:
        raise SystemExit(
            "  Refusing to start: the estimate does not fit today's budget.\n"
            "  Use --limit N to run a chunk now and resume later, raise LLM_RPD/--rpd if "
            "your tier allows it, or pass --yes to proceed anyway."
        )

    kb = KnowledgeBase()
    provider = build_provider(settings, rate_limiter=limiter) if needs_api else None
    print(
        f"  retrieval backend: {kb.backend}"
        + (f" ({kb.model_name})" if kb.model_name else "")
        + "\n"
    )

    # -- run ---------------------------------------------------------------
    results: dict[str, list[CaseResult]] = {}
    for mode in args.modes:
        cache_dir = run_dir / "cache" / mode
        cache_dir.mkdir(parents=True, exist_ok=True)
        trace_dir = run_dir / "traces" / mode
        out: list[CaseResult] = []
        print(f"[{mode}]")
        for i, case in enumerate(cases, 1):
            cpath = cache_dir / f"{case['id']}.json"
            if cpath.exists() and not args.no_resume:
                out.append(CaseResult(**json.loads(cpath.read_text())))
                continue
            try:
                r = (
                    run_baseline(case)
                    if mode == "baseline"
                    else run_llm(case, mode, provider, kb, trace_dir, args.max_steps)
                )
            except (DailyQuotaExceeded, RateLimitError) as exc:
                print(
                    f"\n  STOPPED: {exc}\n  {len(out)}/{len(cases)} done in this mode; "
                    f"re-run the same command tomorrow to resume.\n"
                )
                break
            cpath.write_text(json.dumps(asdict(r), indent=2))
            out.append(r)
            flag = "ok " if r.correct else "MISS"
            print(
                f"  {i:>3}/{len(cases)} {flag} {case['id']} {r.truth} -> {r.predicted} "
                f"({r.api_requests} req, {r.wall_ms / 1000:.1f}s)",
                flush=True,
            )
        results[mode] = out
        n_ok = sum(r.correct for r in out)
        print(
            f"  {mode}: {n_ok}/{len(out)} correct "
            f"({(n_ok / len(out) if out else 0):.1%}), "
            f"{sum(r.api_requests for r in out)} API requests\n"
        )

    # -- report ------------------------------------------------------------
    per_mode = {m: summarize(rs) for m, rs in results.items() if rs}
    if not per_mode:
        raise SystemExit("no results produced")
    worst = {m: worst_failures(results[m]) for m in per_mode}

    images: dict[str, str] = {}
    for m, s in per_mode.items():
        name = f"confusion_{m}.png"
        if confusion_png(
            s["confusion"]["matrix"],
            s["confusion"]["labels"],
            run_dir / name,
            f"{m} — {args.split} split ({settings.model})",
        ):
            images[m] = name

    meta = {
        "date": date,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "split": args.split,
        "provider": settings.provider,
        "model": settings.model,
        "n_cases": len(cases),
        "cases_path": _rel(cases_path),
        "kb_backend": kb.backend,
        "kb_embed_model": kb.model_name,
        "max_steps": args.max_steps,
        "modes": args.modes,
        "total_api_requests": sum(s["cost"]["total_api_requests"] for s in per_mode.values()),
        "command": "python " + " ".join(shlex.quote(a) for a in [_rel(sys.argv[0]), *sys.argv[1:]]),
    }
    (run_dir / "metrics.json").write_text(json.dumps({"meta": meta, "modes": per_mode}, indent=2))
    (run_dir / "report.md").write_text(render_report(meta, per_mode, worst, images))

    print("=" * 72)
    for m, s in per_mode.items():
        print(
            f"{m:>12}: accuracy {s['accuracy']:.1%}  macro-F1 {s['macro_f1']:.3f}  "
            f"evidence P/R {s['evidence']['precision']:.2f}/{s['evidence']['recall']:.2f}  "
            f"false-alarm {s['healthy']['false_alarm_rate']:.1%}"
        )
    print(f"\nwrote {_rel(run_dir)}/metrics.json and report.md")


if __name__ == "__main__":
    main()
