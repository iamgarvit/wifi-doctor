"""Create or update the Hugging Face Space that hosts the Gradio demo.

    HF_TOKEN=... GEMINI_API_KEY=... python scripts/deploy_space.py

Idempotent: it creates the Space only if it does not exist, (re)sets the
Space's secret and variables, uploads every git-tracked file except the
exclusions below, and then waits for the Space to come up.

Both credentials are read from the environment and passed straight to the Hub
API. Neither is ever printed, logged or written to a file.

Free accounts can no longer run on the CPU-basic tier, so the Space is created
on ZeroGPU (``zero-a10g``). The app never touches a GPU: every model call goes
to a hosted LLM API, and retrieval runs BM25-only (``WIFI_DOCTOR_EMBEDDINGS=0``)
so torch is never installed.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
import time
from pathlib import Path

from huggingface_hub import HfApi
from huggingface_hub.utils import HfHubHTTPError, RepositoryNotFoundError

ROOT = Path(__file__).resolve().parents[1]

# Never uploaded, even if tracked by git.
EXCLUDE = [
    ".env",
    ".env.*",
    ".venv/*",
    "runs/*",
    "results/*/cache/*",
    ".cache/*",
    "*.pyc",
]
# ... except the template, which documents the settings.
INCLUDE_ANYWAY = {".env.example"}

TERMINAL_ERRORS = {"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE", "DELETED"}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    files = [f for f in out.split("\0") if f]
    return [
        f
        for f in files
        if f in INCLUDE_ANYWAY or not any(fnmatch.fnmatch(f, pat) for pat in EXCLUDE)
    ]


def ensure_space(api: HfApi, repo_id: str, hardware: str) -> None:
    try:
        info = api.space_info(repo_id)
    except RepositoryNotFoundError:
        info = None

    if info is None:
        print(f"Creating Space {repo_id} (gradio, {hardware}, public)")
        try:
            api.create_repo(
                repo_id,
                repo_type="space",
                space_sdk="gradio",
                space_hardware=hardware,
                private=False,
            )
        except HfHubHTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (402, 403):
                sys.exit(
                    f"The Hub refused to create the Space (HTTP {status}). This account may not "
                    f"be allowed to create a '{hardware}' Space, or the token lacks write "
                    f"access to this namespace. Nothing was created."
                )
            raise
        return

    current = (info.runtime.hardware if info.runtime else None) or "unknown"
    requested = (info.runtime.requested_hardware if info.runtime else None) or current
    print(f"Space {repo_id} exists (hardware: {current})")
    if hardware not in (current, requested):
        print(f"Requesting hardware {hardware}")
        api.request_space_hardware(repo_id, hardware)


def configure(api: HfApi, repo_id: str, variables: dict[str, str]) -> None:
    if key := os.environ.get("GEMINI_API_KEY"):
        api.add_space_secret(repo_id, "GEMINI_API_KEY", key)
        print("Set secret GEMINI_API_KEY")
    else:
        print("GEMINI_API_KEY is not set here; leaving the Space's secret as it is")
    for name, value in variables.items():
        api.add_space_variable(repo_id, name, value)
        print(f"Set variable {name}={value}")


def upload(api: HfApi, repo_id: str) -> None:
    files = tracked_files()
    print(f"Uploading {len(files)} tracked files")
    commit = api.upload_folder(
        repo_id=repo_id,
        repo_type="space",
        folder_path=ROOT,
        allow_patterns=files,
        # Remove files that no longer exist in the repo. .gitattributes is kept.
        delete_patterns="*",
        commit_message="Sync from GitHub",
    )
    print(f"Committed {commit.oid[:8]}")


def wait_until_running(api: HfApi, repo_id: str, timeout_s: int) -> bool:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        stage = api.get_space_runtime(repo_id).stage
        if stage != last:
            print(f"Space stage: {stage}")
            last = stage
        if stage == "RUNNING":
            return True
        if stage in TERMINAL_ERRORS:
            return False
        time.sleep(10)
    print(f"Still not running after {timeout_s}s")
    return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--space", default=os.environ.get("HF_SPACE") or "iamgarvit/wifi-doctor")
    p.add_argument("--hardware", default="zero-a10g")
    p.add_argument("--model", default="gemini-3.5-flash-lite", help="LLM_MODEL for the demo")
    p.add_argument("--max-runs-per-session", type=int, default=5)
    # ~6.4 API requests per agent diagnosis, so 30 diagnoses stay under LLM_RPD,
    # and LLM_RPD leaves most of the 500/day free quota for the evaluation.
    p.add_argument("--daily-cap", type=int, default=30)
    p.add_argument("--rpd", type=int, default=200)
    p.add_argument("--timeout", type=int, default=900, help="seconds to wait for RUNNING")
    p.add_argument("--no-wait", action="store_true")
    args = p.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("HF_TOKEN is not set; nothing to deploy.")
        return 0

    api = HfApi(token=token)
    ensure_space(api, args.space, args.hardware)
    configure(
        api,
        args.space,
        {
            "LLM_PROVIDER": "gemini",
            "LLM_MODEL": args.model,
            "LLM_RPD": str(args.rpd),
            "DEMO_MAX_RUNS_PER_SESSION": str(args.max_runs_per_session),
            "DEMO_DAILY_CAP": str(args.daily_cap),
            "WIFI_DOCTOR_EMBEDDINGS": "0",
        },
    )
    upload(api, args.space)
    print(f"https://huggingface.co/spaces/{args.space}")
    if args.no_wait:
        return 0
    return 0 if wait_until_running(api, args.space, args.timeout) else 1


if __name__ == "__main__":
    sys.exit(main())
