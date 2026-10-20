#!/usr/bin/env python3
"""Run optional AWS checks without publishing Terraform state or secret values."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from typing import Any


BACKEND_KEY = "demo/terraform.tfstate"
DEFAULT_REGION = "ap-south-1"


class LiveError(Exception):
    """A safe-to-publish explanation of an automation failure."""


def load_config(environment: Mapping[str, str]) -> tuple[dict[str, Any], str]:
    """Read deployed inputs as data, without ever expanding them in a shell."""
    try:
        config = json.loads(environment.get("CLOUDGUARD_TFVARS_JSON", ""))
    except (json.JSONDecodeError, TypeError) as error:
        raise LiveError("CLOUDGUARD_TFVARS_JSON must contain a valid JSON object.") from error
    if not isinstance(config, dict) or not config:
        raise LiveError("CLOUDGUARD_TFVARS_JSON must contain deployed Terraform inputs.")
    region = environment.get("AWS_REGION") or DEFAULT_REGION
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", region):
        raise LiveError("AWS_REGION is invalid.")
    if config.get("aws_region", DEFAULT_REGION) != region:
        raise LiveError("AWS_REGION must match aws_region in CLOUDGUARD_TFVARS_JSON.")
    for field, default in (("project_name", "CloudGuard"), ("environment", "demo")):
        if not isinstance(config.get(field, default), str) or not config.get(field, default):
            raise LiveError(f"{field} must be a nonempty string in the deployed inputs.")
    return config, region


def clean_environment(environment: Mapping[str, str], region: str) -> dict[str, str]:
    """Prevent inherited CLI switches, logging, workspaces, or inputs changing checks."""
    result = {
        key: value
        for key, value in environment.items()
        if not key.startswith(("TF_CLI_ARGS", "TF_VAR_", "TF_LOG"))
        and key not in {"TF_WORKSPACE", "CLOUDGUARD_TFVARS_JSON"}
    }
    result.update(
        TF_IN_AUTOMATION="1", TF_INPUT="0", AWS_REGION=region, AWS_DEFAULT_REGION=region
    )
    return result


def state_is_populated(raw_state: str) -> bool:
    try:
        state = json.loads(raw_state)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(state, dict) or not isinstance(state.get("resources"), list):
        return False
    return any(
        isinstance(resource, dict)
        and resource.get("mode") == "managed"
        and isinstance(resource.get("instances"), list)
        and bool(resource.get("instances"))
        for resource in state["resources"]
    )


def change_counts(output: str) -> str:
    """Publish only numeric counts from Terraform's JSON UI events."""
    counts = None
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "change_summary":
            values = event.get("changes")
            if isinstance(values, dict) and all(
                type(values.get(key)) is int and values[key] >= 0
                for key in ("add", "change", "remove")
            ):
                counts = values
    if counts is None:
        return ""
    return f" (add: {counts['add']}, change: {counts['change']}, remove: {counts['remove']})"


def publish(message: str, environment: Mapping[str, str]) -> None:
    print(message)
    summary = environment.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write(message + "\n")


def run_command(
    argv: list[str], environment: Mapping[str, str], runner: Callable[..., Any]
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            argv,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise LiveError("Automation command could not complete; check tool installation and AWS access.") from error


def run_terraform(
    mode: str,
    directory: Path,
    environment: Mapping[str, str],
    runner: Callable[..., Any] = subprocess.run,
) -> int:
    config, region = load_config(environment)
    if not isinstance(config.get("budget_email"), str) or not config["budget_email"].strip():
        raise LiveError("Deployed inputs must include budget_email.")
    bucket = environment.get("AWS_STATE_BUCKET", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise LiveError("AWS_STATE_BUCKET must identify the bootstrapped state bucket.")
    directory = directory.resolve()
    if not directory.is_dir() or not any(directory.glob("*.tf")):
        raise LiveError("Terraform configuration directory is missing.")
    command_environment = clean_environment(environment, region)
    prefix = ["terraform", f"-chdir={directory}"]

    # TemporaryDirectory uses owner-only access. Never put state or plans in artifacts.
    with tempfile.TemporaryDirectory(prefix=".cloudguard-live-", dir=directory) as temp:
        temporary = Path(temp)
        tfvars = temporary / "deployed.tfvars.json"
        tfvars.write_text(json.dumps(config), encoding="utf-8")
        tfvars.chmod(0o600)
        backend = temporary / "backend.hcl"
        backend.write_text(
            f"bucket = {json.dumps(bucket)}\n"
            f"region = {json.dumps(region)}\n"
            f"key = {json.dumps(BACKEND_KEY)}\n"
            "encrypt = true\nuse_lockfile = true\n",
            encoding="utf-8",
        )
        initialized = run_command(
            prefix
            + [
                "init", "-input=false", "-no-color", "-reconfigure",
                "-lockfile=readonly", f"-backend-config={backend}",
            ],
            command_environment,
            runner,
        )
        if initialized.returncode != 0:
            raise LiveError("Terraform backend initialization failed; inspect AWS/backend setup locally.")

        state = run_command(prefix + ["state", "pull"], command_environment, runner)
        if state.returncode != 0 or not state_is_populated(state.stdout):
            raise LiveError("Existing populated managed state is required; deploy the demo manually first.")

        arguments = [
            "plan", "-json", "-input=false", "-no-color", "-lock-timeout=120s",
            "-detailed-exitcode", f"-var-file={tfvars}",
        ]
        if mode == "drift":
            arguments.append("-refresh-only")
        result = run_command(prefix + arguments, command_environment, runner)
        if result.returncode not in (0, 2):
            raise LiveError("Terraform plan execution failed; reproduce locally to inspect private diagnostics.")
        if mode == "drift":
            message = "Drift: detected." if result.returncode == 2 else "Drift: unchanged."
            publish(message, environment)
            if result.returncode == 2 and environment.get("GITHUB_ACTIONS") == "true":
                print("::warning title=CloudGuard drift::Deployed resources changed outside Terraform. Review the drift locally before reconciling state.")
            return result.returncode
        message = "Plan: changes detected" if result.returncode == 2 else "Plan: unchanged"
        publish(message + change_counts(result.stdout) + ".", environment)
        return 0


def run_shutdown(
    environment: Mapping[str, str], runner: Callable[..., Any] = subprocess.run
) -> int:
    config, region = load_config(environment)
    command = [
        sys.executable,
        str(Path(__file__).with_name("idle_shutdown.py")),
        "--region", region,
        "--project-name=" + config.get("project_name", "CloudGuard"),
        "--environment=" + config.get("environment", "demo"),
    ]
    if environment.get("CLOUDGUARD_EXECUTE") == "true":
        command.append("--execute")
    result = run_command(command, clean_environment(environment, region), runner)
    # Shutdown's own output contains decisions/instance IDs, never Terraform inputs/state.
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode != 0:
        raise LiveError("Idle shutdown failed; inspect the script's decision report and AWS access.")
    publish("Idle shutdown completed; see the decision report above.", environment)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "drift", "shutdown"))
    parser.add_argument("--directory", type=Path, default=Path("environments/demo"))
    arguments = parser.parse_args(argv)
    try:
        if arguments.mode == "shutdown":
            return run_shutdown(os.environ)
        return run_terraform(arguments.mode, arguments.directory, os.environ)
    except LiveError as error:
        publish(f"{arguments.mode.capitalize()}: execution error. {error}", os.environ)
        return 1


if __name__ == "__main__":
    sys.exit(main())
