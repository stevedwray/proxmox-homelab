"""Tests for the nightly schedule slots in setup_credentials.py (python-gvm is stubbed)."""
import datetime
import os
import sys
import types
import unittest

os.environ.setdefault("GVM_USERNAME", "x")
os.environ.setdefault("GVM_PASSWORD", "x")
os.environ.setdefault("GREENBONE_MIKROTIK_KEY_PATH", "/nonexistent")
for name in ("gvm", "gvm.connections", "gvm.errors", "gvm.protocols", "gvm.protocols.gmp", "gvm.transforms"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["gvm.connections"].UnixSocketConnection = object
sys.modules["gvm.errors"].GvmError = Exception
sys.modules["gvm.protocols.gmp"].Gmp = object
sys.modules["gvm.transforms"].EtreeCheckCommandTransform = object

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setup_credentials as sc  # noqa: E402

NOW = datetime.datetime(2026, 10, 22, 6, 30, tzinfo=datetime.timezone.utc)  # Thu evening NZ
# Last measured duration in minutes (2026-10-22); the slot must be at least this long.
LAST_MINUTES = {"connector_seg": 7, "build_seg": 23, "cse_seg": 20, "openbao": 22, "game_seg": 28,
                "apps_seg": 30, "ai_seg": 40, "pentest_seg": 41, "media_seg": 49, "edge_seg": 50}


def nightly_slots():
    slots = {z: s[1] for z, s in sc.ZONE_WEEKLY_SLOT.items() if s[0] == "DAILY"}
    for splits in sc.SPLIT_HOSTS.values():
        for split in splits:
            if split["slot"][0] == "DAILY":
                slots[split["label"]] = split["slot"][1]
    return slots


def minutes_after_2200(hhmm):
    h, m = map(int, hhmm.split(":"))
    return ((h * 60 + m) - 22 * 60) % (24 * 60)


class IcalendarTests(unittest.TestCase):
    def test_daily_repeats_daily_and_starts_in_the_past(self):
        ics = sc.build_icalendar("Nightly VLAN scan: ai_seg", "DAILY", "01:05", NOW)
        self.assertIn("RRULE:FREQ=DAILY", ics)
        self.assertIn("DTSTART:20261021T010500", ics)

    def test_weekly_is_unchanged(self):
        ics = sc.build_icalendar("Weekly VLAN scan: lan", "TU", "00:30", NOW)
        self.assertIn("RRULE:FREQ=WEEKLY", ics)
        self.assertIn("DTSTART:20261027T003000", ics)

    def test_names(self):
        self.assertEqual(sc.schedule_name("ai_seg", None, ("DAILY", "01:05")), "Nightly VLAN scan: ai_seg")
        self.assertEqual(sc.schedule_name("lan", None, ("TU", "00:30")), "Weekly VLAN scan: lan")
        self.assertEqual(sc.schedule_name("mgmt_seg", "openbao", ("DAILY", "23:15")), "Nightly VLAN scan: mgmt_seg (openbao)")


class SlotPlanTests(unittest.TestCase):
    def test_quick_ten_are_nightly_and_big_four_are_not(self):
        self.assertEqual(set(nightly_slots()), set(LAST_MINUTES))
        for zone in ("lan", "mgmt_seg", "infra_seg"):
            self.assertNotEqual(sc.ZONE_WEEKLY_SLOT[zone][0], "DAILY")
        self.assertNotEqual(sc.MIKROTIK_SLOT[0], "DAILY")

    def test_slots_do_not_overlap_and_finish_before_0700(self):
        order = sorted(nightly_slots().items(), key=lambda kv: minutes_after_2200(kv[1]))
        self.assertEqual(order[0][1], "22:00")
        for (zone, start), (_, nxt) in zip(order, order[1:]):
            gap = minutes_after_2200(nxt) - minutes_after_2200(start)
            self.assertGreaterEqual(gap, LAST_MINUTES[zone], f"{zone} slot shorter than its last run")
        last_zone, last_start = order[-1]
        self.assertLessEqual(minutes_after_2200(last_start) + LAST_MINUTES[last_zone], 9 * 60)


if __name__ == "__main__":
    unittest.main()
