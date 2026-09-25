# Sample traces

Every diagnosis run writes one JSONL file: one JSON object per event, in the order
they happened. The file is appended and flushed as the run proceeds, so a trace can
be tailed live, and two runs can be diffed line by line.

The files here are **real traces from the evaluation run reported in the top-level
README**, copied out of `results/<run>/traces/` so they survive independently of any
one results directory. Run traces from local use land in `runs/<timestamp>/`, which
is gitignored.

## Event kinds

| `kind` | When | Key fields |
|---|---|---|
| `run_start` | once, first | `mode`, `provider`, `model`, `n_lines`, `max_steps`, `kb_backend`, `kb_embed_model`, `redaction_counts` |
| `llm_call` | each model request | `step`, `call_mode` (`auto` / `forced` / `schema`), `prompt_tokens`, `completion_tokens`, `total_tokens`, `latency_ms`, `finish` |
| `tool_call` | each tool execution | `step`, `name`, `args`, `result_bytes`, `result_summary`, `latency_ms` |
| `validation` | each attempt at the final answer | `attempt`, `ok`, `errors` |
| `run_end` | once, last | `root_cause`, `confidence`, `evidence_lines`, `kb_citations`, `needs_more_info`, plus the totals |

Every event also carries `ts` (wall clock), `t_ms` (milliseconds since the run
started) and `run_id`.

## What is deliberately absent

A trace is written to disk and attached to evaluation reports, so it has to be safe
to share. It therefore never contains:

- the **redaction mapping** (`<MAC_1>` → the real BSSID) — only the *counts* of what
  was replaced, under `redaction_counts`;
- the **un-redacted log** — tool results are summarised to line numbers and shapes,
  not stored verbatim;
- any **API key**.

`tests/test_agent_e2e.py::test_trace_never_records_the_redaction_mapping` asserts
this against real cases rather than trusting the claim.

## Reading one

```bash
# the whole trace, pretty-printed
jq . docs/sample_traces/<file>.jsonl

# just what the agent did, in order
jq -r 'select(.kind=="tool_call") | "\(.step) \(.name) \(.args)"' docs/sample_traces/<file>.jsonl

# token and latency totals
jq -r 'select(.kind=="run_end") | {api_requests, total_tokens, wall_ms}' docs/sample_traces/<file>.jsonl
```
