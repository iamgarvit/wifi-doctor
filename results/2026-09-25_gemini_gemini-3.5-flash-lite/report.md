# wifi-doctor evaluation — test split

- **Date (UTC):** 2026-09-25
- **Provider / model:** `gemini` / `gemini-3.5-flash-lite`
- **Cases:** 33 from `data/synthetic/test/cases.jsonl`
- **Retrieval backend:** hybrid (`BAAI/bge-small-en-v1.5`)
- **Agent max tool steps:** 6
- **Total API requests this run:** 245

> The test split was never used to tune prompts or rules. Every number below was produced by `eval/run_eval.py`; nothing is estimated.

## Headline

| metric | `baseline` | `single_shot` | `agent` |
|---|---|---|---|
| root-cause accuracy | 75.8% | 84.8% | 93.9% |
| macro-F1 | 0.697 | 0.817 | 0.938 |
| evidence precision | 82.8% | 62.1% | 68.2% |
| evidence recall | 44.9% | 45.8% | 49.2% |
| hallucinated evidence (final) | 0.0% | 0.0% | 0.0% |
| HEALTHY false-alarm rate | 33.3% | 0.0% | 0.0% |
| missed-failure rate | 3.3% | 10.0% | 3.3% |
| schema-valid first try | 100.0% | 100.0% | 93.9% |
| schema-valid after retry | 100.0% | 100.0% | 100.0% |
| API requests / log | 0.00 | 1.00 | 6.42 |
| tokens / log | 0 | 11,011 | 44,041 |
| mean latency / log | 0.00s | 3.87s | 31.58s |
| median latency / log | 0.00s | 2.44s | 25.38s |

### How to read these

- **Evidence precision/recall** are over cited line numbers vs the generator's ground-truth lines, micro-averaged over the non-`HEALTHY` cases (a `HEALTHY` case has no ground-truth evidence, so recall is undefined for it).
- **Hallucinated evidence (final)** is the share of returned citations whose line number is out of range or whose quote does not occur on the cited line. The agent validates before returning, so this measures what survived validation, not what the model first attempted.
- **`baseline`** is the regex rule engine in `src/wifi_doctor/baseline.py`. It makes no API calls, does no retrieval, and cites no knowledge-base documents by construction.

## Mode: `baseline`

![confusion matrix — baseline](confusion_baseline.png)

| class | support | precision | recall | F1 |
|---|---|---|---|---|
| WRONG_PASSWORD | 3 | 0.50 | 1.00 | 0.67 |
| HANDSHAKE_TIMEOUT | 3 | 0.00 | 0.00 | 0.00 |
| AUTH_TIMEOUT | 3 | 1.00 | 1.00 | 1.00 |
| ASSOC_REJECTED | 3 | 0.50 | 1.00 | 0.67 |
| AP_DEAUTH | 3 | 0.00 | 0.00 | 0.00 |
| EAP_FAILURE | 3 | 1.00 | 1.00 | 1.00 |
| DHCP_TIMEOUT | 3 | 1.00 | 1.00 | 1.00 |
| BEACON_LOSS_WEAK_SIGNAL | 3 | 0.67 | 0.67 | 0.67 |
| ROAMING_FAILURE | 3 | 1.00 | 1.00 | 1.00 |
| NETWORK_NOT_FOUND | 3 | 1.00 | 1.00 | 1.00 |
| HEALTHY | 3 | 0.67 | 0.67 | 0.67 |

Accuracy by difficulty variant: `heavy_noise` 100.0% (n=1), `misleading` 70.0% (n=10), `plain` 83.3% (n=12), `transient_recovery` 40.0% (n=5), `truncated` 100.0% (n=5)

Mean confidence when correct **0.79**, when wrong **0.78**; `needs_more_info` set on 0.0% of cases.

### 5 worst failures (wrong, ranked by how confident it was)

| case | variant | truth | predicted | conf | trace |
|---|---|---|---|---|---|
| `test_0001` | plain | HANDSHAKE_TIMEOUT | WRONG_PASSWORD | 0.90 | — |
| `test_0012` | transient_recovery | HANDSHAKE_TIMEOUT | WRONG_PASSWORD | 0.90 | — |
| `test_0023` | misleading | HANDSHAKE_TIMEOUT | WRONG_PASSWORD | 0.90 | — |
| `test_0004` | plain | AP_DEAUTH | HEALTHY | 0.75 | — |
| `test_0015` | transient_recovery | AP_DEAUTH | ASSOC_REJECTED | 0.70 | — |

## Mode: `single_shot`

![confusion matrix — single_shot](confusion_single_shot.png)

| class | support | precision | recall | F1 |
|---|---|---|---|---|
| WRONG_PASSWORD | 3 | 0.75 | 1.00 | 0.86 |
| HANDSHAKE_TIMEOUT | 3 | 1.00 | 1.00 | 1.00 |
| AUTH_TIMEOUT | 3 | 1.00 | 1.00 | 1.00 |
| ASSOC_REJECTED | 3 | 0.67 | 0.67 | 0.67 |
| AP_DEAUTH | 3 | 1.00 | 0.67 | 0.80 |
| EAP_FAILURE | 3 | 1.00 | 1.00 | 1.00 |
| DHCP_TIMEOUT | 3 | 1.00 | 1.00 | 1.00 |
| BEACON_LOSS_WEAK_SIGNAL | 3 | 1.00 | 1.00 | 1.00 |
| ROAMING_FAILURE | 3 | 0.00 | 0.00 | 0.00 |
| NETWORK_NOT_FOUND | 3 | 1.00 | 1.00 | 1.00 |
| HEALTHY | 3 | 0.50 | 1.00 | 0.67 |

Accuracy by difficulty variant: `heavy_noise` 100.0% (n=1), `misleading` 80.0% (n=10), `plain` 91.7% (n=12), `transient_recovery` 80.0% (n=5), `truncated` 80.0% (n=5)

Mean confidence when correct **0.99**, when wrong **0.94**; `needs_more_info` set on 0.0% of cases.

### 5 worst failures (wrong, ranked by how confident it was)

| case | variant | truth | predicted | conf | trace |
|---|---|---|---|---|---|
| `test_0008` | plain | ROAMING_FAILURE | HEALTHY | 1.00 | `results/2026-09-25_gemini_gemini-3.5-flash-lite/traces/single_shot/test_0008.jsonl` |
| `test_0026` | misleading | AP_DEAUTH | HEALTHY | 1.00 | `results/2026-09-25_gemini_gemini-3.5-flash-lite/traces/single_shot/test_0026.jsonl` |
| `test_0019` | misleading | ROAMING_FAILURE | ASSOC_REJECTED | 0.95 | `results/2026-09-25_gemini_gemini-3.5-flash-lite/traces/single_shot/test_0019.jsonl` |
| `test_0030` | truncated | ROAMING_FAILURE | HEALTHY | 0.90 | `results/2026-09-25_gemini_gemini-3.5-flash-lite/traces/single_shot/test_0030.jsonl` |
| `test_0025` | transient_recovery | ASSOC_REJECTED | WRONG_PASSWORD | 0.85 | `results/2026-09-25_gemini_gemini-3.5-flash-lite/traces/single_shot/test_0025.jsonl` |

## Mode: `agent`

![confusion matrix — agent](confusion_agent.png)

| class | support | precision | recall | F1 |
|---|---|---|---|---|
| WRONG_PASSWORD | 3 | 1.00 | 1.00 | 1.00 |
| HANDSHAKE_TIMEOUT | 3 | 1.00 | 1.00 | 1.00 |
| AUTH_TIMEOUT | 3 | 1.00 | 0.67 | 0.80 |
| ASSOC_REJECTED | 3 | 0.75 | 1.00 | 0.86 |
| AP_DEAUTH | 3 | 1.00 | 1.00 | 1.00 |
| EAP_FAILURE | 3 | 1.00 | 1.00 | 1.00 |
| DHCP_TIMEOUT | 3 | 1.00 | 0.67 | 0.80 |
| BEACON_LOSS_WEAK_SIGNAL | 3 | 1.00 | 1.00 | 1.00 |
| ROAMING_FAILURE | 3 | 1.00 | 1.00 | 1.00 |
| NETWORK_NOT_FOUND | 3 | 1.00 | 1.00 | 1.00 |
| HEALTHY | 3 | 0.75 | 1.00 | 0.86 |

Accuracy by difficulty variant: `heavy_noise` 100.0% (n=1), `misleading` 90.0% (n=10), `plain` 100.0% (n=12), `transient_recovery` 80.0% (n=5), `truncated` 100.0% (n=5)

Mean confidence when correct **1.00**, when wrong **1.00**; `needs_more_info` set on 0.0% of cases.

### 5 worst failures (wrong, ranked by how confident it was)

| case | variant | truth | predicted | conf | trace |
|---|---|---|---|---|---|
| `test_0013` | misleading | AUTH_TIMEOUT | ASSOC_REJECTED | 1.00 | `results/2026-09-25_gemini_gemini-3.5-flash-lite/traces/agent/test_0013.jsonl` |
| `test_0028` | transient_recovery | DHCP_TIMEOUT | HEALTHY | 1.00 | `results/2026-09-25_gemini_gemini-3.5-flash-lite/traces/agent/test_0028.jsonl` |

## Reproducing

```bash
python eval/run_eval.py --split test --modes baseline single_shot agent --provider gemini --model gemini-3.5-flash-lite --limit 33
```
