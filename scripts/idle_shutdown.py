#!/usr/bin/env python3
"""Stop opted-in demo instances only after a complete hour of low CPU.

Dry run is the default and never calls StopInstances. Low CPU is a heuristic;
this script deliberately skips instances when evidence is missing or ambiguous.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


REQUIRED_TAGS = {"Project": "CloudGuard", "Environment": "demo", "AutoStop": "true"}
PERIOD_SECONDS = 300
CPU_THRESHOLD = 5.0
WINDOW_BUCKETS = 12


@dataclass
class Summary:
    inspected: int = 0
    candidates: int = 0
    stopped: int = 0
    skipped: int = 0
    errors: int = 0


def metric_window(now: datetime) -> tuple[datetime, datetime]:
    """Return UTC bucket boundaries, leaving at least five minutes for ingestion."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    timestamp = int((now - timedelta(minutes=5)).timestamp())
    end = datetime.fromtimestamp(
        timestamp - timestamp % PERIOD_SECONDS, tz=timezone.utc
    )
    return end - timedelta(hours=1), end


def ineligible_reason(
    instance: dict[str, Any], start: datetime, required_tags: dict[str, str]
) -> str | None:
    tags = {tag["Key"]: tag.get("Value") for tag in instance.get("Tags", [])}
    if any(tags.get(key) != value for key, value in required_tags.items()):
        return "missing or changed opt-in tags"
    if instance.get("State", {}).get("Name") != "running":
        return "instance is not running"
    # EC2 has no documented 'on-demand' instance-lifecycle filter value.
    # On-demand instances omit InstanceLifecycle; reject every special lifecycle.
    if instance.get("InstanceLifecycle") is not None:
        return "instance is not on-demand"
    if "aws:autoscaling:groupName" in tags:
        return "instance belongs to Auto Scaling"
    if instance.get("RootDeviceType") != "ebs":
        return "instance is not EBS-backed"
    if not instance.get("InstanceType"):
        return "missing instance type"
    launched = instance.get("LaunchTime")
    if not isinstance(launched, datetime) or launched.tzinfo is None:
        return "missing launch time"
    if launched > start:
        return "instance launched after the observation window began"
    return None


def cpu_skip_reason(
    cloudwatch: Any, instance_id: str, start: datetime, end: datetime
) -> str | None:
    """Require one valid, below-threshold average for every expected bucket."""
    request: dict[str, Any] = {
        "MetricDataQueries": [
            {
                "Id": "cpu",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": "CPUUtilization",
                        "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                    },
                    "Period": PERIOD_SECONDS,
                    "Stat": "Average",
                },
                "ReturnData": True,
            }
        ],
        "StartTime": start,
        "EndTime": end,
        "ScanBy": "TimestampAscending",
    }
    expected = {
        start + timedelta(seconds=PERIOD_SECONDS * n) for n in range(WINDOW_BUCKETS)
    }
    observed: dict[datetime, float] = {}
    seen_tokens: set[str] = set()
    while True:
        response = cloudwatch.get_metric_data(**request)
        results = response.get("MetricDataResults", [])
        if response.get("Messages") or len(results) != 1:
            return "incomplete or ambiguous metric response"
        result = results[0]
        status = result.get("StatusCode")
        if status in {"Forbidden", "InternalError"}:
            raise RuntimeError(f"CloudWatch CPU query failed with status {status}")
        if (
            result.get("Id") != "cpu"
            or status != "Complete"
            or result.get("Messages")
        ):
            return "metric result is incomplete"
        timestamps = result.get("Timestamps", [])
        values = result.get("Values", [])
        if len(timestamps) != len(values):
            return "metric timestamps and values do not match"
        for timestamp, value in zip(timestamps, values):
            if timestamp not in expected or timestamp in observed:
                return "duplicate or unexpected metric bucket"
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 100
            ):
                return "invalid CPU metric value"
            observed[timestamp] = value
        token = response.get("NextToken")
        if not token:
            break
        if token in seen_tokens:
            return "metric pagination repeated a token"
        seen_tokens.add(token)
        request["NextToken"] = token

    if set(observed) != expected:
        return "missing CPU metric buckets"
    if any(value >= CPU_THRESHOLD for value in observed.values()):
        return "CPU reached the 5% threshold"
    return None


def _instances(response: dict[str, Any]):
    for reservation in response.get("Reservations", []):
        yield from reservation.get("Instances", [])


def run_shutdown(
    ec2: Any,
    cloudwatch: Any,
    *,
    execute: bool = False,
    project_name: str = "CloudGuard",
    environment: str = "demo",
    now: datetime | None = None,
    log: Callable[[str], None] = print,
) -> Summary:
    start, end = metric_window(now or datetime.now(timezone.utc))
    summary = Summary()
    mode = "execute" if execute else "dry-run"
    log(f"mode={mode} CPU window=[{start.isoformat()}, {end.isoformat()})")
    required_tags = {
        "Project": project_name, "Environment": environment, "AutoStop": "true"
    }
    filters = [{"Name": "instance-state-name", "Values": ["running"]}]
    filters.extend(
        {"Name": f"tag:{key}", "Values": [value]}
        for key, value in required_tags.items()
    )
    seen: set[str] = set()
    try:
        pages = ec2.get_paginator("describe_instances").paginate(Filters=filters)
        for page in pages:
            for instance in _instances(page):
                instance_id = instance.get("InstanceId", "unknown")
                if instance_id in seen:
                    continue
                seen.add(instance_id)
                summary.inspected += 1
                reason = ineligible_reason(instance, start, required_tags)
                if instance_id == "unknown":
                    reason = "missing instance ID"
                try:
                    if reason is None:
                        reason = cpu_skip_reason(cloudwatch, instance_id, start, end)
                    if reason:
                        summary.skipped += 1
                        log(f"SKIP {instance_id}: {reason}")
                        continue
                    summary.candidates += 1
                    if not execute:
                        log(f"DRY-RUN {instance_id}: would stop; all 12 CPU averages <5%")
                        continue

                    # Refresh safety conditions immediately before the stop call.
                    latest = list(
                        _instances(ec2.describe_instances(InstanceIds=[instance_id]))
                    )
                    if len(latest) != 1 or latest[0].get("InstanceId") != instance_id:
                        reason = "instance could not be rechecked"
                    else:
                        reason = ineligible_reason(latest[0], start, required_tags)
                        if reason is None and any(
                            latest[0].get(key) != instance.get(key)
                            for key in ("LaunchTime", "InstanceType")
                        ):
                            reason = "launch time or instance type changed during inspection"
                    if reason:
                        summary.skipped += 1
                        log(f"SKIP {instance_id}: pre-stop recheck: {reason}")
                        continue
                    ec2.stop_instances(InstanceIds=[instance_id])
                    summary.stopped += 1
                    log(f"STOP {instance_id}: stop requested; all 12 CPU averages <5%")
                except Exception as error:
                    summary.errors += 1
                    log(f"ERROR {instance_id}: {type(error).__name__}: {error}")
    except Exception as error:
        summary.errors += 1
        log(f"ERROR listing instances: {type(error).__name__}: {error}")
    log(
        f"SUMMARY mode={mode} inspected={summary.inspected} "
        f"candidates={summary.candidates} stop_requests={summary.stopped} "
        f"skipped={summary.skipped} errors={summary.errors}"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--project-name", default="CloudGuard")
    parser.add_argument("--environment", default="demo")
    parser.add_argument(
        "--execute", action="store_true", help="send stop requests (default: dry run)"
    )
    args = parser.parse_args(argv)
    try:
        import boto3  # Imported only for the CLI; unit tests need no SDK or credentials.

        ec2 = boto3.client("ec2", region_name=args.region)
        cloudwatch = boto3.client("cloudwatch", region_name=args.region)
    except Exception as error:
        print(f"ERROR creating AWS clients: {type(error).__name__}: {error}")
        return 1

    summary = run_shutdown(
        ec2,
        cloudwatch,
        execute=args.execute,
        project_name=args.project_name,
        environment=args.environment,
    )
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
