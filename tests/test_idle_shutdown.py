"""Credential-free shutdown tests using small EC2 and CloudWatch fakes."""

import copy
from contextlib import redirect_stdout
import io
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from scripts.idle_shutdown import REQUIRED_TAGS, main, metric_window, run_shutdown


NOW = datetime(2026, 10, 20, 17, 0, 42, tzinfo=timezone.utc)
START, END = metric_window(NOW)


def instance(**changes):
    result = {
        "InstanceId": "i-demo",
        "InstanceType": "t3.micro",
        "State": {"Name": "running"},
        "Tags": [{"Key": key, "Value": value} for key, value in REQUIRED_TAGS.items()],
        "LaunchTime": START - timedelta(hours=1),
        "RootDeviceType": "ebs",
    }
    result.update(changes)
    return result


def metrics(values=None, timestamps=None, status="Complete", **extra):
    return {
        "MetricDataResults": [
            {
                "Id": "cpu",
                "StatusCode": status,
                "Timestamps": timestamps
                if timestamps is not None
                else [START + timedelta(minutes=5 * n) for n in range(12)],
                "Values": values if values is not None else [1.0] * 12,
            }
        ],
        **extra,
    }


class FakeEC2:
    def __init__(self, instances=None, latest=None):
        self.instances = [instance()] if instances is None else instances
        self.latest = latest
        self.stop_calls = []
        self.describe_calls = []
        self.filters = None

    def get_paginator(self, operation):
        assert operation == "describe_instances"
        return self

    def paginate(self, **kwargs):
        self.filters = kwargs["Filters"]
        # Exercise pagination with one instance per page.
        return [
            {"Reservations": [{"Instances": [item]}]} for item in self.instances
        ]

    def describe_instances(self, **kwargs):
        self.describe_calls.append(kwargs)
        latest = self.latest if self.latest is not None else self.instances
        return {"Reservations": [{"Instances": latest}]}

    def stop_instances(self, **kwargs):
        self.stop_calls.append(kwargs)
        return {"StoppingInstances": []}


class FakeCloudWatch:
    def __init__(self, responses=None):
        self.responses = [metrics()] if responses is None else responses
        self.calls = []

    def get_metric_data(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


class ShutdownTests(unittest.TestCase):
    def run_check(self, ec2=None, cloudwatch=None, execute=False, **kwargs):
        self.ec2 = ec2 if ec2 is not None else FakeEC2()
        self.cloudwatch = cloudwatch if cloudwatch is not None else FakeCloudWatch()
        self.logs = []
        return run_shutdown(
            self.ec2, self.cloudwatch, execute=execute, now=NOW, log=self.logs.append,
            **kwargs,
        )

    def test_window_is_aligned_and_allows_metric_delay(self):
        self.assertEqual(END, datetime(2026, 10, 20, 16, 55, tzinfo=timezone.utc))
        self.assertEqual(END - START, timedelta(hours=1))
        self.assertGreaterEqual(NOW - END, timedelta(minutes=5))
        with self.assertRaises(ValueError):
            metric_window(NOW.replace(tzinfo=None))

    def test_default_dry_run_never_stops_or_rechecks(self):
        summary = self.run_check()
        self.assertEqual(summary.candidates, 1)
        self.assertEqual(summary.stopped, 0)
        self.assertEqual(self.ec2.stop_calls, [])
        self.assertEqual(self.ec2.describe_calls, [])
        self.assertTrue(any("DRY-RUN i-demo" in line for line in self.logs))

    def test_execute_stops_only_the_rechecked_candidate(self):
        summary = self.run_check(execute=True)
        self.assertEqual(summary.stopped, 1)
        self.assertEqual(self.ec2.describe_calls, [{"InstanceIds": ["i-demo"]}])
        self.assertEqual(self.ec2.stop_calls, [{"InstanceIds": ["i-demo"]}])
        filters = {item["Name"]: item["Values"] for item in self.ec2.filters}
        self.assertEqual(filters["instance-state-name"], ["running"])
        for key, value in REQUIRED_TAGS.items():
            self.assertEqual(filters[f"tag:{key}"], [value])
        request = self.cloudwatch.calls[0]
        self.assertEqual(request["StartTime"], START)
        self.assertEqual(request["EndTime"], END)
        stat = request["MetricDataQueries"][0]["MetricStat"]
        self.assertEqual(stat["Period"], 300)
        self.assertEqual(stat["Stat"], "Average")
        self.assertEqual(stat["Metric"]["Dimensions"], [{"Name": "InstanceId", "Value": "i-demo"}])

    def test_busy_and_threshold_equal_are_skipped(self):
        for cpu in (5.0, 70.0):
            with self.subTest(cpu=cpu):
                summary = self.run_check(
                    cloudwatch=FakeCloudWatch([metrics([1.0] * 11 + [cpu])]),
                    execute=True,
                )
                self.assertEqual(summary.skipped, 1)
                self.assertEqual(self.ec2.stop_calls, [])

    def test_missing_invalid_and_incomplete_metrics_are_skipped(self):
        responses = [
            metrics(values=[1.0] * 11, timestamps=[START + timedelta(minutes=5 * n) for n in range(11)]),
            metrics(status="PartialData"),
            metrics(values=[float("nan")] + [1.0] * 11),
            metrics(values=[float("inf")] + [1.0] * 11),
            metrics(values=[-1] + [1.0] * 11),
            metrics(values=[101] + [1.0] * 11),
            metrics(values=[True] + [1.0] * 11),
            metrics(values=[1.0] * 11),
            metrics(timestamps=[START] * 12),
            metrics(timestamps=[END] + [START + timedelta(minutes=5 * n) for n in range(1, 12)]),
            {"MetricDataResults": []},
            metrics(Messages=[{"Code": "InternalError", "Value": "try again"}]),
        ]
        for response in responses:
            with self.subTest(response=response):
                summary = self.run_check(cloudwatch=FakeCloudWatch([response]), execute=True)
                self.assertEqual(summary.skipped, 1)
                self.assertEqual(self.ec2.stop_calls, [])

    def test_wrong_tags_recent_spot_asg_non_ebs_and_stopped_are_skipped(self):
        invalid = [
            instance(Tags=[]),
            instance(Tags=[{"Key": key, "Value": "false" if key == "AutoStop" else value} for key, value in REQUIRED_TAGS.items()]),
            instance(LaunchTime=START + timedelta(seconds=1)),
            instance(LaunchTime=None),
            instance(InstanceLifecycle="spot"),
            instance(InstanceLifecycle="capacity-block"),
            instance(Tags=instance()["Tags"] + [{"Key": "aws:autoscaling:groupName", "Value": "demo"}]),
            instance(RootDeviceType="instance-store"),
            instance(State={"Name": "stopped"}),
            instance(InstanceType=""),
        ]
        for item in invalid:
            with self.subTest(instance=item):
                summary = self.run_check(ec2=FakeEC2([item]), execute=True)
                self.assertEqual(summary.skipped, 1)
                self.assertEqual(self.cloudwatch.calls, [])
                self.assertEqual(self.ec2.stop_calls, [])

    def test_changed_conditions_before_stop_are_rejected(self):
        changed = [
            instance(Tags=[]),
            instance(State={"Name": "stopped"}),
            instance(InstanceLifecycle="spot"),
            instance(InstanceType="t3.large"),
            instance(LaunchTime=START - timedelta(minutes=1)),
        ]
        for item in changed:
            with self.subTest(instance=item):
                summary = self.run_check(ec2=FakeEC2(latest=[item]), execute=True)
                self.assertEqual(summary.stopped, 0)
                self.assertEqual(summary.skipped, 1)
                self.assertEqual(self.ec2.stop_calls, [])

    def test_custom_project_and_environment_are_filtered_and_rechecked(self):
        tags = {"Project": "Sandbox", "Environment": "poc", "AutoStop": "true"}
        item = instance(Tags=[{"Key": key, "Value": value} for key, value in tags.items()])
        summary = self.run_check(
            ec2=FakeEC2([item]), execute=True,
            project_name="Sandbox", environment="poc",
        )
        self.assertEqual(summary.stopped, 1)
        filters = {entry["Name"]: entry["Values"] for entry in self.ec2.filters}
        self.assertEqual(filters["tag:Project"], ["Sandbox"])
        self.assertEqual(filters["tag:Environment"], ["poc"])
        summary = self.run_check(
            ec2=FakeEC2([item], latest=[instance()]), execute=True,
            project_name="Sandbox", environment="poc",
        )
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(self.ec2.stop_calls, [])

    def test_missing_instance_during_recheck_is_skipped(self):
        summary = self.run_check(ec2=FakeEC2(latest=[]), execute=True)
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(self.ec2.stop_calls, [])

    def test_complete_metric_pagination_is_combined(self):
        times = [START + timedelta(minutes=5 * n) for n in range(12)]
        cloudwatch = FakeCloudWatch([
            metrics(values=[1.0] * 6, timestamps=times[:6], NextToken="page-2"),
            metrics(values=[1.0] * 6, timestamps=times[6:]),
        ])
        summary = self.run_check(cloudwatch=cloudwatch, execute=True)
        self.assertEqual(summary.stopped, 1)
        self.assertEqual(cloudwatch.calls[1]["NextToken"], "page-2")

    def test_repeated_metric_pagination_token_is_skipped(self):
        cloudwatch = FakeCloudWatch([
            metrics(values=[], timestamps=[], NextToken="same"),
        ])
        summary = self.run_check(cloudwatch=cloudwatch, execute=True)
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(len(cloudwatch.calls), 2)
        self.assertEqual(self.ec2.stop_calls, [])

    def test_metric_api_error_is_failure_and_does_not_stop(self):
        summary = self.run_check(
            cloudwatch=FakeCloudWatch([RuntimeError("access denied")]), execute=True
        )
        self.assertEqual(summary.errors, 1)
        self.assertEqual(summary.candidates, 0)
        self.assertEqual(self.ec2.stop_calls, [])

    def test_cloudwatch_error_status_is_a_failure_instead_of_an_idle_skip(self):
        for status in ("Forbidden", "InternalError"):
            with self.subTest(status=status):
                summary = self.run_check(
                    cloudwatch=FakeCloudWatch([metrics(status=status)]), execute=True
                )
                self.assertEqual(summary.errors, 1)
                self.assertEqual(summary.stopped, 0)
                self.assertEqual(self.ec2.stop_calls, [])
                self.assertTrue(any(f"status {status}" in line for line in self.logs))

    def test_recheck_api_error_is_failure_and_does_not_stop(self):
        ec2 = FakeEC2()
        def fail(**kwargs):
            raise RuntimeError("access denied")
        ec2.describe_instances = fail
        summary = self.run_check(ec2=ec2, execute=True)
        self.assertEqual(summary.errors, 1)
        self.assertEqual(self.ec2.stop_calls, [])

    def test_stop_api_error_is_reported_and_not_counted_as_stopped(self):
        ec2 = FakeEC2()
        def fail(**kwargs):
            raise RuntimeError("access denied")
        ec2.stop_instances = fail
        summary = self.run_check(ec2=ec2, execute=True)
        self.assertEqual(summary.errors, 1)
        self.assertEqual(summary.stopped, 0)
        self.assertTrue(any("ERROR i-demo:" in line for line in self.logs))

    def test_listing_api_error_is_a_reported_failure(self):
        ec2 = FakeEC2()
        def fail(**kwargs):
            raise RuntimeError("access denied")
        ec2.paginate = fail
        summary = self.run_check(ec2=ec2, execute=True)
        self.assertEqual(summary.errors, 1)
        self.assertEqual(summary.inspected, 0)
        self.assertEqual(self.ec2.stop_calls, [])
        self.assertTrue(any("ERROR listing instances:" in line for line in self.logs))

    def test_cli_client_initialization_failure_is_readable(self):
        sdk = Mock()
        sdk.client.side_effect = RuntimeError("credentials unavailable")
        output = io.StringIO()
        with patch.dict(sys.modules, {"boto3": sdk}), redirect_stdout(output):
            result = main([])
        self.assertEqual(result, 1)
        self.assertIn("ERROR creating AWS clients:", output.getvalue())
        self.assertIn("credentials unavailable", output.getvalue())

    def test_ec2_pagination_inspects_each_instance(self):
        items = [instance(InstanceId="i-first"), instance(InstanceId="i-second")]
        summary = self.run_check(ec2=FakeEC2(items))
        self.assertEqual(summary.inspected, 2)
        self.assertEqual(summary.candidates, 2)
        self.assertEqual(len(self.cloudwatch.calls), 2)

    def test_empty_inventory_reports_no_candidates(self):
        summary = self.run_check(ec2=FakeEC2([]))
        self.assertEqual(summary.inspected, 0)
        self.assertEqual(summary.errors, 0)
        self.assertEqual(self.cloudwatch.calls, [])


if __name__ == "__main__":
    unittest.main()
