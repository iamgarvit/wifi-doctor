"""The Hugging Face deploy script's upload plan. No Hub calls, no token."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("deploy_space", ROOT / "scripts" / "deploy_space.py")
deploy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deploy)


def test_the_space_readme_is_the_card_not_the_github_readme():
    plan = deploy.upload_plan(["README.md", "hf_space_card.md", "app.py", "src/x.py"])
    assert plan["README.md"] == "hf_space_card.md"
    assert "hf_space_card.md" not in plan, "the card is uploaded only as README.md"
    assert "README.md" not in {src for dest, src in plan.items() if dest != "README.md"}


def test_secrets_venvs_runs_and_caches_are_never_uploaded():
    files = [
        "hf_space_card.md",
        "app.py",
        ".env",
        ".env.local",
        ".env.example",
        ".venv/lib/x.py",
        "runs/a.jsonl",
        "results/r1/cache/agent/test_0000.json",
        "results/r1/metrics.json",
    ]
    plan = deploy.upload_plan(files)
    assert set(plan) == {"README.md", "app.py", ".env.example", "results/r1/metrics.json"}


def test_a_missing_card_stops_the_deploy():
    with pytest.raises(SystemExit):
        deploy.upload_plan(["README.md", "app.py"])


def test_the_real_repository_plan_is_a_valid_gradio_space():
    files = deploy.git_files()
    cfg = deploy.check_plan(deploy.upload_plan(files))
    assert cfg["sdk"] == "gradio" and cfg["app_file"] == "app.py"
    assert cfg["sdk_version"] and cfg["short_description"]


def test_the_github_readme_has_no_front_matter():
    assert not (ROOT / "README.md").read_text().startswith("---")


def test_dry_run_needs_no_token_and_makes_no_hub_calls():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "deploy_space.py"), "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"]},  # no HF_TOKEN
        check=True,
    ).stdout
    assert "README.md  <- hf_space_card.md" in out
    assert "sdk=gradio" in out
