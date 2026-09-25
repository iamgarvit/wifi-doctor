"""Create or update the Hugging Face Space that hosts the Gradio demo.

    HF_TOKEN=... GEMINI_API_KEY=... python scripts/deploy_space.py
    python scripts/deploy_space.py --dry-run    # show what would be uploaded

Idempotent: it creates the Space only if it does not exist, (re)sets the
Space's secret and variables, uploads every git-tracked file except the
exclusions below, and then waits for the Space to come up.

The Space's README.md is ``hf_space_card.md``, whose YAML front matter is the
Space's configuration; the GitHub README is not uploaded. ``--dry-run`` prints
the upload plan without a token and without calling the Hub.

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

ROOT = Path(__file__).resolve().parents[1]

# Uploaded as the Space's README.md; the GitHub README.md is not uploaded.
SPACE_CARD = "hf_space_card.md"

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


def git_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [f for f in out.split("\0") if f]


def is_excluded(path: str) -> bool:
    return path not in INCLUDE_ANYWAY and any(fnmatch.fnmatch(path, pat) for pat in EXCLUDE)


def upload_plan(files: list[str]) -> dict[str, str]:
    """Map each path in the Space to the repository file it is uploaded from."""
    if SPACE_CARD not in files:
        sys.exit(f"{SPACE_CARD} is missing; the Space would have no configuration.")
    plan = {f: f for f in files if not is_excluded(f) and f not in ("README.md", SPACE_CARD)}
    plan["README.md"] = SPACE_CARD
    return dict(sorted(plan.items()))


def card_config(card_path: Path) -> dict[str, str]:
    """The top-level keys of the card's YAML front matter (flat, as the Hub uses it)."""
    text = card_path.read_text()
    if not text.startswith("---\n"):
        return {}
    header = text[4 : text.index("\n---", 4)]
    out = {}
    for line in header.splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            out[key.strip()] = value.strip().strip('"')
    return out


def check_plan(plan: dict[str, str]) -> dict[str, str]:
    """Fail early on a card the Hub would reject or that points at a missing app."""
    cfg = card_config(ROOT / plan["README.md"])
    if cfg.get("sdk") != "gradio":
        sys.exit(f"{SPACE_CARD}: expected 'sdk: gradio' in its front matter, got {cfg!r}")
    app_file = cfg.get("app_file", "app.py")
    if app_file not in plan:
        sys.exit(f"{SPACE_CARD}: app_file {app_file!r} is not in the upload")
    return cfg


def ensure_space(api, repo_id: str, hardware: str) -> None:
    from huggingface_hub.utils import HfHubHTTPError, RepositoryNotFoundError

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
                    f"The Hub refused to create the Space (HTTP {status}: "
                    f"{exc.server_message or 'no message'}). This account may not be allowed "
                    f"to create a '{hardware}' Space, or the token lacks write access to this "
                    f"namespace. Nothing was created."
                )
            raise
        return

    current = (info.runtime.hardware if info.runtime else None) or "unknown"
    requested = (info.runtime.requested_hardware if info.runtime else None) or current
    print(f"Space {repo_id} exists (hardware: {current})")
    if hardware not in (current, requested):
        print(f"Requesting hardware {hardware}")
        api.request_space_hardware(repo_id, hardware)


def configure(api, repo_id: str, variables: dict[str, str]) -> None:
    if key := os.environ.get("GEMINI_API_KEY"):
        api.add_space_secret(repo_id, "GEMINI_API_KEY", key)
        print("Set secret GEMINI_API_KEY")
    else:
        print("GEMINI_API_KEY is not set here; leaving the Space's secret as it is")
    for name, value in variables.items():
        api.add_space_variable(repo_id, name, value)
        print(f"Set variable {name}={value}")


def upload(api, repo_id: str, plan: dict[str, str]) -> None:
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete

    ops = [
        CommitOperationAdd(path_in_repo=dest, path_or_fileobj=str(ROOT / src))
        for dest, src in plan.items()
    ]
    # Remove files that are no longer part of the upload. .gitattributes is the Hub's own.
    remote = api.list_repo_files(repo_id, repo_type="space")
    stale = [f for f in remote if f not in plan and f != ".gitattributes"]
    ops += [CommitOperationDelete(path_in_repo=f) for f in stale]
    print(f"Uploading {len(plan)} files, deleting {len(stale)} stale ones")
    commit = api.create_commit(
        repo_id=repo_id,
        repo_type="space",
        operations=ops,
        commit_message="Sync from GitHub",
    )
    print(f"Committed {commit.oid[:8]}")


def print_plan(plan: dict[str, str], cfg: dict[str, str], files: list[str]) -> None:
    print(f"Would upload {len(plan)} files to the Space:")
    for dest, src in plan.items():
        print(f"  {dest}" + (f"  <- {src}" if dest != src else ""))
    print("Not uploaded: README.md (the GitHub README)")
    for pat in EXCLUDE:
        n = sum(1 for f in files if f not in INCLUDE_ANYWAY and fnmatch.fnmatch(f, pat))
        if n:
            print(f"  {n} file(s) matching {pat}")
    print("Space card: " + ", ".join(f"{k}={v}" for k, v in cfg.items()))


def wait_until_running(api, repo_id: str, timeout_s: int) -> bool:
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
    # Not the evaluation model: Gemini's free quota is per model, so the demo
    # runs on its own and can never spend the budget an evaluation run needs.
    p.add_argument("--model", default="gemini-3.1-flash-lite", help="LLM_MODEL for the demo")
    p.add_argument("--max-runs-per-session", type=int, default=5)
    # An agent diagnosis is ~6 API requests, so 50 a day is ~300 of the 500/day.
    p.add_argument("--daily-cap", type=int, default=50)
    p.add_argument("--timeout", type=int, default=900, help="seconds to wait for RUNNING")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="print the upload plan and stop")
    args = p.parse_args()

    files = git_files()
    plan = upload_plan(files)
    cfg = check_plan(plan)
    if args.dry_run:
        print_plan(plan, cfg, files)
        return 0

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("HF_TOKEN is not set; nothing to deploy.")
        return 0

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    ensure_space(api, args.space, args.hardware)
    configure(
        api,
        args.space,
        {
            "LLM_PROVIDER": "gemini",
            "LLM_MODEL": args.model,
            "DEMO_MAX_RUNS_PER_SESSION": str(args.max_runs_per_session),
            "DEMO_DAILY_CAP": str(args.daily_cap),
            "WIFI_DOCTOR_EMBEDDINGS": "0",
        },
    )
    upload(api, args.space, plan)
    print(f"https://huggingface.co/spaces/{args.space}")
    if args.no_wait:
        return 0
    return 0 if wait_until_running(api, args.space, args.timeout) else 1


if __name__ == "__main__":
    sys.exit(main())
