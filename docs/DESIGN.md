# Design notes

The README summarises each decision in a few sentences; this is the longer rationale.

## A hand-written agent loop rather than a framework

The loop (`_run_agent` in [`src/wifi_doctor/agent.py`](../src/wifi_doctor/agent.py)) is about a
hundred lines, and every decision that matters in this project lives inside it: when tool calls
stop and the final answer is forced, what counts as a valid answer, what exactly gets fed back on
a retry, and what lands in the trace. A framework would hide those decisions behind defaults that
would then need explaining anyway.

## The model cannot see the log

In agent mode the log is reachable only through `search_log` and `get_timeline`. A model that
has never been shown line 88 cannot claim line 88 says something, so every citation has to come
back through a tool that returns real line numbers. (Single-shot mode, the ablation, does send
the whole redacted log.)

## A forced `submit_diagnosis` function instead of a response schema

Gemini rejects `tools` and `response_schema` in the same request; this was verified against
`gemini-3.5-flash-lite` on 2026-09-25. Agent mode needs its tools attached right up to the final
turn, so the structured answer comes from a forced function call
(`mode="ANY", allowed_function_names=["submit_diagnosis"]`) whose parameter schema is the
Pydantic model. Single-shot mode has no tools, so it uses the native `response_schema`. Both of
Gemini's structured-output mechanisms are used, each where it fits.

## Hybrid retrieval with Reciprocal Rank Fusion

Wi-Fi troubleshooting is full of exact tokens (`status_code=17`, `EAPOL-Key`, `Reason: 15`), and a
dense model maps status 17 and status 27 to nearly the same vector; BM25 does not. But a user
typing "it keeps asking for the password again" shares no tokens with the document that answers
them, and BM25 cannot help there. Neither retriever is sufficient, so both run and their rankings
are fused with Reciprocal Rank Fusion, which needs no score normalisation between two retrievers
whose scores are on incomparable scales.

Embeddings are optional at runtime: if `sentence-transformers` is missing, the model cannot be
fetched, or `WIFI_DOCTOR_EMBEDDINGS=0` is set, retrieval degrades to BM25-only and reports its
backend as `bm25`. The public demo runs this way (see [`DEPLOYMENT.md`](DEPLOYMENT.md)).

## Validation and one retry

A diagnosis nobody can check is of little use in a support workflow. Three checks make "the model
said so" falsifiable:

1. the payload must parse as the Pydantic model;
2. every cited line number must exist, and the quote must occur on that line;
3. every `kb_citation` must be a document that was retrieved during this run.

On failure the specific errors, including the real text of a misquoted line, go back to the model
for exactly one retry. If it fails twice, the run returns `needs_more_info=true` rather than a
confident guess.

On the reported run the guardrail fired on 2 of 33 agent cases (schema-valid first try 93.9%,
100% after retry). In
[`sample_traces/agent_test_0006_validation_retry.jsonl`](sample_traces/agent_test_0006_validation_retry.jsonl)
the model cited a NetworkManager line with the right process name, log format and a plausible
timestamp, but the line did not exist. The validator compared the quote with line 41, rejected
it with that line's real text, and the retry produced a correct, checkable answer.

## Redaction before anything is sent

Free-tier LLM APIs generally reserve the right to use submitted prompts to improve their products,
so anything sent to one should be treated as published. A Wi-Fi log is not neutral: a BSSID plus
an SSID is a geolocatable fingerprint (this is how public BSSID-location databases are built), and
an EAP identity is somebody's username.

So MACs, SSIDs, IPv4/IPv6 addresses, EAP identities, certificate subjects, syslog usernames and
hostnames are replaced with stable placeholders (`<MAC_1>`, `<SSID_1>`, …) before the text
reaches a provider. Placeholders are stable within a document, so the model can still reason about
"the same AP as before", which is most of what the identifiers were for. The mapping back to the
real values stays in the process, is never written to a trace, and is used only to render the
answer for the person who owns the log. The demo's *What was sent to the LLM* tab shows the exact
redacted text.

Protocol constants such as `255.255.255.255` are deliberately not redacted: replacing them would
destroy meaning (a `DHCPDISCOVER` must go to the broadcast address) and protect nobody.

One of the redaction tests, run over the whole corpus rather than over handpicked strings, caught
a real leak: the SSID reappearing inside a RADIUS certificate subject in
`CTRL-EVENT-EAP-PEER-CERT`, which no other pattern covered. That case is now a regression test.

## A good-faith regex baseline

Comparing the LLM with a strawman would make it look good for no reason. The baseline in
[`src/wifi_doctor/baseline.py`](../src/wifi_doctor/baseline.py) encodes the disambiguations an
engineer would write after a week of reading supplicant output: `WRONG_KEY` before EAPOL
timeouts, a roam attempt before a generic association rejection, and `locally_generated=1` to
tell "we left" from "we were kicked". If the agent cannot clear that bar, it is not worth its API
calls.

## Limitations in more detail

- **Synthetic logs.** They are format-faithful (real control-event names, supplicant states, and
  IEEE 802.11 reason and status codes) but generated, not captured. Doing well on them shows the
  model has learned the format and the reasoning, which is necessary but not sufficient for real
  captures. See [`data/README.md`](../data/README.md).
- **Eleven classes, one label per log.** Real failures overlap and cascade; a single mutually
  exclusive root cause keeps accuracy and macro-F1 well defined at the cost of realism.
- **WPA2-Personal and 802.1X.** WPA3/SAE is documented in the knowledge base but is not a
  generated class, and SAE fails at a different point in the state machine (`AUTHENTICATING`, not
  `4WAY_HANDSHAKE`), so the learned patterns do not transfer.
- **Confidence is not calibrated.** On the reported run the agent's mean confidence was 1.00 when
  it was right and 1.00 when it was wrong. Making it meaningful (verbalised uncertainty,
  self-consistency across samples, or a calibrated head over the evidence count) is the most
  valuable next piece of work, and the evaluation harness already measures it.
- **One model, one day.** Everything was measured on a single provider and model on the date
  recorded, with temperature 0. No repeated-run variance is reported.
- **Token cost grows with the conversation.** See [`EVALUATION.md`](EVALUATION.md#cost).
