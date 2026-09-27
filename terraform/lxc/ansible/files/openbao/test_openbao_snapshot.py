"""Unit tests for the OpenBao snapshot retention logic (pure functions only)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "openbao_snapshot.py"
SPEC = importlib.util.spec_from_file_location("openbao_snapshot", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["openbao_snapshot"] = MODULE
SPEC.loader.exec_module(MODULE)

NOW = datetime(2026, 10, 15, 4, 0, 0, tzinfo=timezone.utc)  # a Thursday


def name(ts: datetime, kind: str = "nightly") -> str:
    return f"openbao-{ts.strftime('%Y%m%dT%H%M%SZ')}-{kind}.snap"


def nightlies(days: int) -> list[str]:
    return [name(NOW - timedelta(days=d)) for d in range(days)]


class PruneTests(unittest.TestCase):
    def test_parse_rejects_foreign_files(self):
        self.assertIsNone(MODULE.parse_name("notes.txt"))
        self.assertIsNone(MODULE.parse_name(".openbao-20261015T040000Z-nightly.snap.partial"))

    def test_recent_dailies_kept(self):
        self.assertEqual(MODULE.prune_plan(nightlies(14), NOW), [])

    def test_old_plain_daily_deleted(self):
        old = datetime(2026, 9, 23, 3, 30, tzinfo=timezone.utc)  # Wednesday, 22 days old, not 1st
        names = nightlies(10) + [name(old)]
        self.assertEqual(MODULE.prune_plan(names, NOW), [name(old)])

    def test_sunday_kept_8_weeks_then_deleted(self):
        sunday_recent = datetime(2026, 9, 6, 3, 30, tzinfo=timezone.utc)  # 39 days
        sunday_old = datetime(2026, 8, 9, 3, 30, tzinfo=timezone.utc)  # 67 days
        self.assertEqual(sunday_recent.weekday(), 6)
        self.assertEqual(sunday_old.weekday(), 6)
        names = nightlies(10) + [name(sunday_recent), name(sunday_old)]
        self.assertEqual(MODULE.prune_plan(names, NOW), [name(sunday_old)])

    def test_first_of_month_kept_12_months(self):
        month_recent = datetime(2026, 3, 1, 3, 30, tzinfo=timezone.utc)
        month_old = datetime(2025, 9, 1, 3, 30, tzinfo=timezone.utc)  # > 365 days
        names = nightlies(10) + [name(month_recent), name(month_old)]
        self.assertEqual(MODULE.prune_plan(names, NOW), [name(month_old)])

    def test_postwrite_kept_90_days(self):
        pw_recent = NOW - timedelta(days=80)
        pw_old = NOW - timedelta(days=100)
        names = nightlies(10) + [name(pw_recent, "postwrite"), name(pw_old, "postwrite")]
        self.assertEqual(MODULE.prune_plan(names, NOW), [name(pw_old, "postwrite")])

    def test_newest_seven_never_deleted_even_if_expired(self):
        # Timer silently broken for a year: every file is past policy.
        ancient = [name(NOW - timedelta(days=400 + d)) for d in range(10)]
        to_delete = MODULE.prune_plan(ancient, NOW)
        self.assertEqual(len(to_delete), 3)
        kept = set(ancient) - set(to_delete)
        self.assertEqual(kept, set(sorted(ancient, reverse=True)[:7]))


if __name__ == "__main__":
    unittest.main()
