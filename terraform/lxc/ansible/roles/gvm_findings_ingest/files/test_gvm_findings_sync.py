"""Unit tests for evaluate_coverage() in gvm_findings_sync.py."""
import unittest
from datetime import datetime, timezone

import gvm_findings_sync as g

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
START = "2026-10-14T01:00:00Z"
AFTER = "2026-10-14T01:05:00Z"


def row_for(names, *, schedule="Weekly VLAN scan: x", status="Done"):
    task = {"name": "Credentialed scan: x", "status": status, "schedule": schedule,
            "last_report_scan_start": START, "target_hosts": ["10.0.0.1"]}
    results = [{"task_name": "Credentialed scan: x", "host": "10.0.0.1",
                "name": n, "creation_time": AFTER} for n in names]
    return g.evaluate_coverage([task], results, now=NOW)[0]["coverage"]


class EvaluateCoverageTests(unittest.TestCase):
    def test_login_ok_only_is_ok(self):
        self.assertEqual(row_for([g.AUTH_OK_NAME, "Other"]), "ok")

    def test_login_failed_only_is_auth_failed(self):
        self.assertEqual(row_for([g.AUTH_FAIL_NAME, "Other"]), "auth_failed")

    def test_failure_alongside_success_is_ok(self):
        # MikroTik: several parallel SSH sessions, one refused, the rest worked.
        self.assertEqual(row_for([g.AUTH_FAIL_NAME, g.AUTH_OK_NAME]), "ok")

    def test_no_login_evidence(self):
        self.assertEqual(row_for(["Other"]), "no_auth_evidence")

    def test_no_results(self):
        self.assertEqual(row_for([]), "no_results")

    def test_unscheduled_wins_over_results(self):
        self.assertEqual(row_for([g.AUTH_OK_NAME], schedule=None), "unscheduled")


if __name__ == "__main__":
    unittest.main()
