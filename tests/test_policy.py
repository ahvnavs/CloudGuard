"""Prove the scanner rejects the four advertised insecure configurations."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class PolicyTests(unittest.TestCase):
    def test_insecure_fixture_is_rejected_for_each_advertised_policy(self):
        scanner = shutil.which("checkov")
        self.assertIsNotNone(scanner, "Install requirements-dev.txt before running tests")
        fixture = Path(__file__).parent / "fixtures" / "insecure.tf"
        expected = {"CKV_AWS_24", "CKV_AWS_290", "CKV_AWS_8", "CKV_AWS_88"}
        with tempfile.TemporaryDirectory(prefix="cloudguard-policy-") as temporary:
            target = Path(temporary) / "insecure.tf"
            shutil.copyfile(fixture, target)
            result = subprocess.run(
                [scanner, "--file", str(target), "--framework", "terraform",
                 "--check", ",".join(sorted(expected)), "--output", "json",
                 "--quiet", "--skip-download"],
                capture_output=True, text=True, timeout=120,
            )
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["parsing_errors"], 0)
        failed = {check["check_id"] for check in report["results"]["failed_checks"]}
        self.assertEqual(failed, expected)


if __name__ == "__main__":
    unittest.main()
