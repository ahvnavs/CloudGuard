"""Exercise live orchestration without Terraform, AWS credentials, or API calls."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from scripts import terraform_live as live


class TerraformLiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        (self.directory / "main.tf").write_text('terraform { backend "s3" {} }')
        self.environment = {
            "AWS_STATE_BUCKET": "cloudguard-test-state",
            "AWS_REGION": "ap-south-1",
            "CLOUDGUARD_TFVARS_JSON": json.dumps({"budget_email": "private@example.test"}),
            "GITHUB_STEP_SUMMARY": str(self.directory / "summary.md"),
        }
        self.state = json.dumps({
            "version": 4,
            "resources": [{"mode": "managed", "type": "aws_vpc", "instances": [{}]}],
        })
        self.calls = []

    def runner(self, exitcode=0, state=None, plan_output=None, init_exitcode=0):
        """Return a small Terraform stand-in and inspect temporary files in flight."""
        def fake_run(argv, **kwargs):
            self.calls.append((argv, kwargs))
            self.assertIsInstance(argv, list)
            self.assertNotIn("shell", kwargs)
            self.assertTrue(kwargs["capture_output"])
            if "init" in argv:
                backend = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("-backend-config=")))
                self.assertIn('key = "demo/terraform.tfstate"', backend.read_text())
                self.assertIn("use_lockfile = true", backend.read_text())
                self.assertIn("-lockfile=readonly", argv)
                return subprocess.CompletedProcess(argv, init_exitcode, "private init text", "private init error")
            if "state" in argv:
                return subprocess.CompletedProcess(argv, 0, self.state if state is None else state, "")
            self.assertIn("-detailed-exitcode", argv)
            self.assertIn("-lock-timeout=120s", argv)
            tfvars = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("-var-file=")))
            self.assertEqual(tfvars.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(tfvars.read_text()), json.loads(self.environment["CLOUDGUARD_TFVARS_JSON"]))
            return subprocess.CompletedProcess(argv, exitcode, plan_output or "", "private plan error")
        return fake_run

    def run_check(self, mode, **kwargs):
        output = io.StringIO()
        with redirect_stdout(output):
            result = live.run_terraform(mode, self.directory, self.environment, self.runner(**kwargs))
        self.assertFalse(list(self.directory.glob(".cloudguard-live-*")))
        return result, output.getvalue()

    def test_normal_plan_zero_and_two_both_succeed(self):
        for code, label in ((0, "unchanged"), (2, "changes detected")):
            with self.subTest(code=code):
                result, output = self.run_check("plan", exitcode=code)
                self.assertEqual(result, 0)
                self.assertIn(f"Plan: {label}", output)
                self.assertNotIn("-refresh-only", self.calls[-1][0])

    def test_drift_zero_and_two_remain_distinct(self):
        for code, label in ((0, "unchanged"), (2, "detected")):
            with self.subTest(code=code):
                result, output = self.run_check("drift", exitcode=code)
                self.assertEqual(result, code)
                self.assertIn(f"Drift: {label}", output)
                self.assertIn("-refresh-only", self.calls[-1][0])

    def test_error_exit_is_never_reported_as_no_drift(self):
        for mode in ("plan", "drift"):
            with self.subTest(mode=mode), self.assertRaisesRegex(live.LiveError, "execution failed"):
                self.run_check(mode, exitcode=1)

    def test_init_error_stops_before_pulling_state(self):
        with self.assertRaisesRegex(live.LiveError, "initialization failed"):
            self.run_check("drift", init_exitcode=1)
        self.assertEqual(len(self.calls), 1)

    def test_missing_empty_and_data_only_state_never_report_clean(self):
        invalid_states = (
            "", "not-json", "null", "[]", "{}", '{"resources": null}',
            '{"resources": []}',
            '{"resources": [null]}',
            '{"resources": [{"mode": "managed", "instances": "invalid"}]}',
            '{"resources": [{"mode": "managed", "instances": []}]}',
            '{"resources": [{"mode": "data", "instances": [{}]}]}',
        )
        for mode in ("plan", "drift"):
            for state in invalid_states:
                with self.subTest(mode=mode, state=state):
                    self.calls.clear()
                    with self.assertRaisesRegex(live.LiveError, "populated managed state"):
                        self.run_check(mode, state=state)
                    self.assertEqual(len(self.calls), 2)

    def test_failed_state_pull_is_an_error(self):
        delegate = self.runner()
        def fake_run(argv, **kwargs):
            if "state" in argv:
                return subprocess.CompletedProcess(argv, 1, self.state, "private missing state")
            return delegate(argv, **kwargs)
        with self.assertRaisesRegex(live.LiveError, "populated managed state"):
            live.run_terraform("drift", self.directory, self.environment, fake_run)

    def test_missing_or_invalid_config_fails_before_running_commands(self):
        cases = (
            ("CLOUDGUARD_TFVARS_JSON", ""),
            ("CLOUDGUARD_TFVARS_JSON", "[]"),
            ("CLOUDGUARD_TFVARS_JSON", "{}"),
            ("CLOUDGUARD_TFVARS_JSON", '{"other": "value"}'),
            ("AWS_STATE_BUCKET", ""),
            ("AWS_STATE_BUCKET", "$(touch /tmp/should-not-exist)"),
            ("AWS_REGION", "bad region"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                environment = dict(self.environment, **{field: value})
                with self.assertRaises(live.LiveError):
                    live.run_terraform("plan", self.directory, environment, self.runner())
        self.assertEqual(self.calls, [])

    def test_region_must_match_deployed_inputs(self):
        self.environment["CLOUDGUARD_TFVARS_JSON"] = json.dumps({
            "budget_email": "private@example.test", "aws_region": "us-east-1",
        })
        with self.assertRaisesRegex(live.LiveError, "must match"):
            self.run_check("drift")

    def test_missing_configuration_directory_fails(self):
        with self.assertRaisesRegex(live.LiveError, "directory is missing"):
            live.run_terraform("plan", self.directory / "missing", self.environment, self.runner())
        self.assertEqual(self.calls, [])

    def test_secret_values_are_data_never_shell_code_or_public_logs(self):
        payload = '$(touch /tmp/cloudguard-injection); `echo private`; "\n-private'
        self.environment["CLOUDGUARD_TFVARS_JSON"] = json.dumps({
            "budget_email": "private@example.test", "project_name": payload,
        })
        event = json.dumps({
            "type": "change_summary", "changes": {"add": 1, "change": 2, "remove": 0},
            "private": payload,
        })
        result, output = self.run_check("plan", exitcode=2, plan_output=event)
        self.assertEqual(result, 0)
        self.assertIn("add: 1, change: 2, remove: 0", output)
        for argv, kwargs in self.calls:
            self.assertNotIn(payload, " ".join(argv))
            self.assertNotIn("CLOUDGUARD_TFVARS_JSON", kwargs["env"])
        self.assertNotIn(payload, output)
        self.assertNotIn("private@example.test", output)
        self.assertEqual((self.directory / "summary.md").read_text(), output)

    def test_inherited_terraform_switches_and_logging_are_removed(self):
        self.environment.update({
            "TF_CLI_ARGS_plan": "-lock=false -var=private=leak",
            "TF_WORKSPACE": "other", "TF_VAR_project_name": "wrong", "TF_LOG": "TRACE",
            "TF_LOG_PATH": "dump.txt",
        })
        self.run_check("plan")
        for _, kwargs in self.calls:
            for key in ("TF_CLI_ARGS_plan", "TF_WORKSPACE", "TF_VAR_project_name", "TF_LOG", "TF_LOG_PATH"):
                self.assertNotIn(key, kwargs["env"])
            self.assertEqual(kwargs["env"]["TF_IN_AUTOMATION"], "1")

    def test_temporary_secrets_are_removed_after_execution_failure(self):
        with self.assertRaises(live.LiveError):
            self.run_check("plan", exitcode=1)
        self.assertFalse(list(self.directory.glob(".cloudguard-live-*")))

    def test_github_drift_emits_a_notice_and_keeps_failure_exitcode(self):
        self.environment["GITHUB_ACTIONS"] = "true"
        result, output = self.run_check("drift", exitcode=2)
        self.assertEqual(result, 2)
        self.assertIn("::warning title=CloudGuard drift::", output)
        self.assertEqual((self.directory / "summary.md").read_text(), "Drift: detected.\n")

    def test_timeout_and_missing_binary_are_safe_errors(self):
        for error in (FileNotFoundError("terraform"), subprocess.TimeoutExpired("terraform", 600)):
            with self.subTest(error=error):
                with self.assertRaisesRegex(live.LiveError, "could not complete"):
                    live.run_terraform("plan", self.directory, self.environment,
                                       lambda *args, **kwargs: (_ for _ in ()).throw(error))

    def test_main_reports_execution_error_without_private_details(self):
        output = io.StringIO()
        with patch.dict(os.environ, self.environment, clear=True), \
             patch.object(live, "run_terraform", side_effect=live.LiveError("Safe diagnosis.")), \
             redirect_stdout(output):
            result = live.main(["drift", "--directory", str(self.directory)])
        self.assertEqual(result, 1)
        self.assertIn("Drift: execution error. Safe diagnosis.", output.getvalue())

    def test_shutdown_defaults_to_dry_run_and_passes_tags_as_argv(self):
        payload = 'my-project; $(touch /tmp/not-executed)'
        self.environment["CLOUDGUARD_TFVARS_JSON"] = json.dumps({
            "project_name": payload, "environment": "demo",
        })
        for execute in (None, "false", "true"):
            captured = []
            def fake_run(argv, **kwargs):
                captured.append(argv)
                self.assertNotIn("CLOUDGUARD_TFVARS_JSON", kwargs["env"])
                return subprocess.CompletedProcess(argv, 0, "Decision report.\n", "")
            environment = dict(self.environment)
            if execute is not None:
                environment["CLOUDGUARD_EXECUTE"] = execute
            with redirect_stdout(io.StringIO()):
                self.assertEqual(live.run_shutdown(environment, fake_run), 0)
            argv = captured[0]
            self.assertIn("--project-name=" + payload, argv)
            self.assertEqual("--execute" in argv, execute == "true")

    def test_shutdown_leading_hyphens_are_option_values(self):
        self.environment["CLOUDGUARD_TFVARS_JSON"] = json.dumps({
            "project_name": "-project", "environment": "-demo",
        })
        def fake_run(argv, **kwargs):
            self.assertIn("--project-name=-project", argv)
            self.assertIn("--environment=-demo", argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(live.run_shutdown(self.environment, fake_run), 0)

    def test_change_counts_reject_non_numeric_or_injected_values(self):
        self.assertEqual(live.change_counts('{"type":"change_summary","changes":{"add":"private","change":0,"remove":0}}'), "")
        self.assertEqual(live.change_counts("not json\n[]\nnull"), "")


class WorkflowContractTests(unittest.TestCase):
    """Protect credential boundaries and the distinction between plan and drift."""

    @classmethod
    def setUpClass(cls):
        cls.directory = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        # PyYAML's default YAML 1.1 maps `on` to True; BaseLoader preserves GitHub keys.
        cls.workflows = {
            file.name: yaml.load(file.read_text(), Loader=yaml.BaseLoader)
            for file in cls.directory.glob("*.yml")
        }

    def test_all_actions_and_tools_are_pinned(self):
        for name, workflow in self.workflows.items():
            with self.subTest(workflow=name):
                self.assertNotIn("pull_request_target", workflow["on"])
                for job in workflow["jobs"].values():
                    self.assertEqual(job["runs-on"], "ubuntu-24.04")
                    for step in job["steps"]:
                        if "uses" in step:
                            self.assertRegex(step["uses"], r"^[\w-]+/[\w-]+@[a-f0-9]{40}$")
                        if step.get("uses", "").startswith("hashicorp/setup-terraform@"):
                            self.assertEqual(step["with"]["terraform_version"], "1.13.5")
                            self.assertEqual(step["with"]["terraform_wrapper"], "false")

    def test_pr_plan_and_base_drift_are_independent_and_gated(self):
        workflow = self.workflows["aws-pr.yml"]
        self.assertEqual(workflow["on"]["pull_request"]["branches"], ["main"])
        gate = workflow["jobs"]["availability"]["steps"][0]["run"]
        for guard in ("$PR_AUTHOR", "$GITHUB_REPOSITORY_OWNER", "$PR_REPOSITORY", "$GITHUB_REPOSITORY", "$AWS_ENABLED"):
            self.assertIn(guard, gate)
        for job_name, ref, mode in (("plan", "head.sha", "plan"), ("base-drift", "base.sha", "drift")):
            job = workflow["jobs"][job_name]
            self.assertEqual(job["needs"], "availability")
            self.assertEqual(job["if"], "needs.availability.outputs.run_aws == 'true'")
            self.assertEqual(job["permissions"]["id-token"], "write")
            self.assertIn(ref, job["steps"][0]["with"]["ref"])
            self.assertEqual(job["steps"][-1]["run"], f"python scripts/terraform_live.py {mode}")

    def test_scheduled_jobs_restrict_main_and_shutdown_is_opt_in(self):
        shutdown = self.workflows["shutdown.yml"]
        self.assertEqual(shutdown["on"]["schedule"][0]["cron"], "0 17 * * *")
        self.assertEqual(shutdown["on"]["workflow_dispatch"]["inputs"]["execute"]["default"], "false")
        execution = shutdown["jobs"]["shutdown"]["steps"][-1]["env"]["CLOUDGUARD_EXECUTE"]
        self.assertIn("vars.CLOUDGUARD_STOP_ENABLED == 'true'", execution)
        self.assertIn("inputs.execute == true", execution)
        self.assertIn("github.event_name == 'schedule' && vars.CLOUDGUARD_STOP_ENABLED", execution)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.execute", execution)
        for name in ("drift.yml", "shutdown.yml"):
            gate = self.workflows[name]["jobs"]["availability"]["steps"][0]["run"]
            self.assertIn('"$GITHUB_REF" != "refs/heads/main"', gate)

    def run_gate(self, workflow_name, **overrides):
        steps = self.workflows[workflow_name]["jobs"]["availability"]["steps"]
        script = next(step["run"] for step in steps if step.get("id") == "gate")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            output = directory / "output"
            summary = directory / "summary"
            environment = dict(os.environ, **{
                "AWS_ENABLED": "true",
                "PLAN_ROLE": "arn:aws:iam::123456789012:role/plan",
                "SHUTDOWN_ROLE": "arn:aws:iam::123456789012:role/shutdown",
                "STATE_BUCKET": "cloudguard-test-state",
                "DEPLOYED_INPUTS": '{"budget_email":"private@example.test"}',
                "PR_AUTHOR": "owner",
                "PR_REPOSITORY": "owner/CloudGuard",
                "GITHUB_REPOSITORY": "owner/CloudGuard",
                "GITHUB_REPOSITORY_OWNER": "owner",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_OUTPUT": str(output),
                "GITHUB_STEP_SUMMARY": str(summary),
                **overrides,
            })
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-eu", "-o", "pipefail", "-c", script],
                env=environment, text=True, capture_output=True, check=False, timeout=5,
            )
            return result, output.read_text(), summary.read_text()

    def test_disabled_aws_is_a_clear_successful_skip(self):
        for workflow in ("aws-pr.yml", "drift.yml", "shutdown.yml"):
            with self.subTest(workflow=workflow):
                result, output, summary = self.run_gate(workflow, AWS_ENABLED="", DEPLOYED_INPUTS="")
                self.assertEqual(result.returncode, 0)
                self.assertEqual(output, "run_aws=false\n")
                self.assertIn("skipped", summary)

    def test_enabled_but_missing_aws_configuration_fails(self):
        required = {
            "aws-pr.yml": ("PLAN_ROLE", "STATE_BUCKET", "DEPLOYED_INPUTS"),
            "drift.yml": ("PLAN_ROLE", "STATE_BUCKET", "DEPLOYED_INPUTS"),
            "shutdown.yml": ("SHUTDOWN_ROLE", "DEPLOYED_INPUTS"),
        }
        for workflow, fields in required.items():
            for field in fields:
                with self.subTest(workflow=workflow, field=field):
                    result, output, summary = self.run_gate(workflow, **{field: ""})
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(output, "run_aws=false\n")
                    self.assertIn("configuration error", summary)
                    self.assertNotIn("private@example.test", result.stdout + summary)

    def test_configured_owner_pr_and_main_jobs_are_enabled(self):
        for workflow in ("aws-pr.yml", "drift.yml", "shutdown.yml"):
            with self.subTest(workflow=workflow):
                result, output, _ = self.run_gate(workflow)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(output, "run_aws=true\n")

    def test_forks_and_other_authors_skip_even_with_unavailable_secrets(self):
        cases = ({"PR_AUTHOR": "contributor"}, {"PR_REPOSITORY": "fork/CloudGuard"})
        for changes in cases:
            with self.subTest(changes=changes):
                result, output, summary = self.run_gate(
                    "aws-pr.yml", DEPLOYED_INPUTS="", **changes
                )
                self.assertEqual(result.returncode, 0)
                self.assertEqual(output, "run_aws=false\n")
                self.assertIn("owner-authored", summary)

    def test_manual_jobs_skip_nonmain_refs(self):
        for workflow in ("drift.yml", "shutdown.yml"):
            with self.subTest(workflow=workflow):
                result, output, summary = self.run_gate(
                    workflow, GITHUB_REF="refs/heads/feature", DEPLOYED_INPUTS=""
                )
                self.assertEqual(result.returncode, 0)
                self.assertEqual(output, "run_aws=false\n")
                self.assertIn("main branch", summary)


if __name__ == "__main__":
    unittest.main()
