"""Structural checks on action.yml — the composite GitHub Action wrapping the CLI.

Catches the failure mode that bit block 12's --sarif work before it was caught by
hand: a YAML/wiring mistake that only surfaces the first time someone's workflow
actually runs the action.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ACTION_YML = Path(__file__).resolve().parent.parent / "action.yml"


def _load():
    return yaml.safe_load(ACTION_YML.read_text())


def test_action_yml_parses():
    action = _load()
    assert action["name"] == "ocr-verify"
    assert action["runs"]["using"] == "composite"


def test_inputs_cover_the_documented_cli_flags():
    inputs = _load()["inputs"]
    for name in (
        "pdf",
        "engine-output",
        "batch",
        "fail-on",
        "max-unverified",
        "out",
        "json",
        "sarif",
    ):
        assert name in inputs, f"missing input: {name}"
        assert inputs[name]["required"] is False


def test_exit_code_output_is_wired_to_the_run_step():
    action = _load()
    assert action["outputs"]["exit-code"]["value"] == "${{ steps.run.outputs.exit-code }}"
    steps = action["runs"]["steps"]
    run_step = next(s for s in steps if s.get("id") == "run")
    assert "echo \"exit-code=$code\" >> \"$GITHUB_OUTPUT\"" in run_step["run"]


def test_every_input_is_passed_through_env_not_interpolated_into_the_script():
    """Values must reach the shell via `env:`, never spliced into `run:` text directly —
    the latter is a known GitHub Actions script-injection vector for untrusted inputs.
    """
    run_step = next(s for s in _load()["runs"]["steps"] if s.get("id") == "run")
    assert "${{" not in run_step["run"]
    for env_value in run_step["env"].values():
        assert env_value.startswith("${{ inputs.")
