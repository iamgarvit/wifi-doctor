# Evaluation

Every number in the README's results table came from running
[`eval/run_eval.py`](../eval/run_eval.py) against the real API on the date shown. The table is
written into the README straight from that run's `metrics.json` by
[`scripts/update_readme_results.py`](../scripts/update_readme_results.py), between the
`RESULTS:START` / `RESULTS:END` markers, so no number is copied by hand. The full report for the
published run, with per-class breakdowns, confusion matrices and the worst failures, is
[`results/2026-09-25_gemini_gemini-3.5-flash-lite/report.md`](../results/2026-09-25_gemini_gemini-3.5-flash-lite/report.md).

## Modes

- **`agent`**: the tool-using loop in `src/wifi_doctor/agent.py`; the model reaches the log only
  through tools.
- **`single_shot`**: the whole redacted log in one prompt with a response schema. It is the
  ablation that shows what the tools add.
- **`baseline`**: the regex rules in `src/wifi_doctor/baseline.py`. No API calls, no retrieval,
  and no knowledge-base citations.

## What the metrics mean

- **Evidence precision / recall** compare the line numbers the model cited against the
  generator's ground-truth evidence lines, micro-averaged over the non-`HEALTHY` cases (a
  `HEALTHY` log has no ground-truth evidence).
- **Hallucinated evidence** is the share of returned citations whose line number does not exist
  or whose quote does not occur on the cited line. Validation runs before an answer is returned,
  so this measures what got through, not what the model first attempted.
- **HEALTHY false-alarm rate** is how often a healthy log was given a fault. A confident false
  alarm costs a support engineer more than no answer, so it is tracked separately from accuracy.
- **Missed-failure rate** is how often a failing log was called `HEALTHY`.
- **Schema-valid, first try vs after retry** separates "the model got it right immediately" from
  "the validator caught it and the retry fixed it".
- **API requests, tokens and latency** are per log; latency is wall-clock time for the whole
  diagnosis.

### Why the agent's evidence precision is lower than the baseline's

The agent cites more lines (2.8 per failing log against 2.1), and 25 of its 27 citations outside
the ground truth are on logs it diagnosed correctly. They are neighbouring lines from the same
failure sequence, such as the resulting `CTRL-EVENT-DISCONNECTED`, the `EAP-STARTED` /
`EAP-METHOD` lines or a signal reading, that the minimal ground-truth set does not include.

## Coverage of the published run

The published results cover 33 of the 66 held-out test logs: a balanced 3 per class, the same 33
for every mode. The run stopped at the Gemini free tier's daily request quota. At 3 examples per
class one case moves accuracy by 3 points, so the gaps between modes are directional rather than
statistically meaningful.

## Running it

```bash
# Prints the estimated API-request count and refuses to start if it will not fit in
# today's remaining free-tier budget.
python eval/run_eval.py --split test --modes baseline single_shot agent \
    --provider gemini --model gemini-3.5-flash-lite

python eval/run_eval.py --split test --limit 10        # a small chunk
python eval/run_eval.py --split test --modes baseline  # no API calls at all
python eval/run_eval.py --split dev --provider mock    # fully offline

python scripts/update_readme_results.py results/<run>/metrics.json
```

Every finished case is cached under `results/<run>/cache/`, so an interrupted run resumes where
it stopped and never pays for the same log twice. Re-running the first command after the quota
resets therefore finishes the remaining 33 test logs.

A client-side rate limiter paces requests (`LLM_RPM`) and a persisted daily counter enforces
`LLM_RPD`. Retryable 429s and 503s are retried with exponential backoff, honouring the provider's
own `retryDelay` hint; a 429 for a per-day quota is not retried, because it will not clear within
any useful backoff.

The prompts and rules were tuned on the dev split only; the test split was never used for tuning.

## Cost

The agent's token cost grows with the conversation: tool results are resent on every turn, so a
400-line log with a long tool phase is markedly more expensive than a short one. On the published
run the agent averaged 6.42 API requests and 44,041 tokens per log, against 1.00 and 11,011 for
single-shot. Single-shot's median latency was 2.4 s against the agent's 25.4 s.

## Traces

Each run writes one JSONL trace per case: `run_start`, then `llm_call` / `tool_call` /
`validation` events in order, then `run_end` with the totals. Samples are in
[`docs/sample_traces/`](sample_traces/).
