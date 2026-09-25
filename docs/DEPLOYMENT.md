# Deploying the demo

The demo has two front ends over the same logic in
[`src/wifi_doctor/demo.py`](../src/wifi_doctor/demo.py):

| front end | file | host | local URL |
|---|---|---|---|
| Streamlit | [`streamlit_app.py`](../streamlit_app.py) | Streamlit Community Cloud (the live demo) | http://localhost:8501 |
| Gradio | [`app.py`](../app.py) | Hugging Face Spaces (needs a paid plan) | http://127.0.0.1:7860 |

Run either from the repository root: `streamlit run streamlit_app.py` or `python app.py`.

## Streamlit Community Cloud (live demo)

Live at <https://wifi-doctor.streamlit.app>. Hugging Face now requires a paid plan for Gradio
and Docker Spaces, so the public demo runs on Streamlit Community Cloud, which is free.

### Create or recreate the app

At <https://share.streamlit.io> choose **Create app → Deploy a public app from GitHub**:

| field | value |
|---|---|
| Repository | `iamgarvit/wifi-doctor` |
| Branch | `main` |
| Main file path | `streamlit_app.py` |
| App URL | `wifi-doctor` (→ `wifi-doctor.streamlit.app`) |
| Advanced settings → Python version | `3.12` |
| Advanced settings → Secrets | see below |

Secrets, in TOML:

```toml
GEMINI_API_KEY = "your-gemini-api-key"

# Optional; these are the defaults.
# LLM_MODEL = "gemini-3.1-flash-lite"
# DEMO_MAX_RUNS_PER_SESSION = "5"
# DEMO_DAILY_CAP = "50"
# WIFI_DOCTOR_EMBEDDINGS = "0"
```

Each setting is read from `st.secrets` first, then from the environment, then from the demo
defaults. Locally the same keys can go in `.streamlit/secrets.toml` (gitignored) or `.env`.
The key is never printed, logged or written to a trace.

### Dependencies: why a `Pipfile`

Community Cloud installs the first dependency file it finds, and a `Pipfile` takes precedence
over `requirements.txt`. So:

- [`Pipfile`](../Pipfile) and `Pipfile.lock` are the lightweight Streamlit set: `streamlit`,
  `google-genai`, `pydantic`, `python-dotenv`, `numpy` and `rank-bm25`, with no gradio, groq,
  torch or `sentence-transformers`.
- [`requirements.txt`](../requirements.txt) stays the Gradio / Hugging Face set.
- [`requirements-dev.txt`](../requirements-dev.txt) is everything for local development and
  tests.
- [`.streamlit/config.toml`](../.streamlit/config.toml) holds the theme and the 5 MB upload
  limit.

### Measured footprint

From a clean copy of the repository on Python 3.12, installed from the `Pipfile` alone and
started from the repository root as Community Cloud does: the install took 35 s (491 MB), the
app went from launch to rendered in a browser in 3.5 s, and the process's peak memory was 125 MB
after two agent diagnoses, well inside Community Cloud's 690 MB minimum.

## Demo configuration (both hosts)

| setting | value | why |
|---|---|---|
| `LLM_MODEL` | `gemini-3.1-flash-lite` | Gemini's free quota is per model, so the demo never spends the evaluation model's budget |
| `DEMO_MAX_RUNS_PER_SESSION` | `5` | one visitor cannot use up the day |
| `DEMO_DAILY_CAP` | `50` | about 6 API requests per diagnosis, so at most ~300 requests a day |
| `WIFI_DOCTOR_EMBEDDINGS` | `0` | BM25-only retrieval (see below) |

**The demo is not the evaluated configuration.** The published results are for
`gemini-3.5-flash-lite` with hybrid retrieval; the demo runs `gemini-3.1-flash-lite` with
BM25-only retrieval, and its footer shows both. The embedding model itself is cheap (on a CPU
container `bge-small-en-v1.5` loaded and indexed the knowledge base in about 14 s cold,
including the download, and 7 s warm, with 20 ms queries), but it needs `sentence-transformers`
and torch, which took 5.8 GB of disk to install. That is too much for a 28-document knowledge
base, so the demo leaves it out.

The rule-baseline mode needs no key and makes no API calls, so it keeps working when the key is
missing or the quota is spent; the demo shows a clear message in both cases.

## Hugging Face Space (alternative)

Use this route only if the account has a plan that allows Gradio Spaces. Creating the Space on
this account returned HTTP 402.

`app.py` is the same demo in Gradio. The Space's configuration (SDK, Gradio version, Python
version, app file) is the YAML front matter of [`hf_space_card.md`](../hf_space_card.md), which
the deploy script uploads as the Space's `README.md`; it is kept out of the GitHub README, where
GitHub would render it as a table. The Space would run on **ZeroGPU** (`zero-a10g`) without
using the GPU: every model call goes to the Gemini API, it does not import torch, and nothing is
decorated with `@spaces.GPU`.

```bash
python scripts/deploy_space.py --dry-run   # the upload plan; no token, no Hub calls

pip install huggingface_hub
export HF_TOKEN=...          # a Hugging Face token with write access
export GEMINI_API_KEY=...    # stored as a Space secret, never printed
python scripts/deploy_space.py
```

[`scripts/deploy_space.py`](../scripts/deploy_space.py):

- creates the public Space `iamgarvit/wifi-doctor` if it does not exist (`--space` to change);
- sets the `GEMINI_API_KEY` secret and the settings in the table above as Space variables;
- uploads every git-tracked file except `.env`, `.venv/`, `runs/` and the results caches, with
  `hf_space_card.md` in place of the GitHub `README.md`;
- deletes files that are no longer part of the upload (the Hub's `.gitattributes` is kept);
- waits until the Space reports `RUNNING` (`--no-wait` to skip).

It is idempotent, so run it again to redeploy. If the Hub refuses to create the Space (HTTP 402
or 403), it stops without creating anything.

[`.github/workflows/sync-to-hf.yml`](../.github/workflows/sync-to-hf.yml) runs the same script,
but only when started by hand from the Actions tab (`workflow_dispatch`). It skips cleanly when
the repository has no `HF_TOKEN` secret, and it leaves the Space's `GEMINI_API_KEY` untouched.

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every push to `main` and every
pull request, on Python 3.11 and 3.12. It installs only what the offline tests import, runs
`ruff`, regenerates the dataset and checks it is unchanged, and runs `pytest`. The Gradio and
Streamlit UI tests skip there because those packages are not installed; locally they run once
`requirements-dev.txt` is installed.
