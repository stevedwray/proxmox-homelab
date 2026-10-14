import json
import os
import unittest

import must_fire
import wazuh_tuning as wt


def health(heap=50, mem=2000, queues=None, dropped=0, status=None):
    return {"heap": {"heap_used_pct": heap}, "mem_available_mb": mem,
            "analysisd": {"events_dropped": dropped, **(queues or {})},
            "agents": {"status": status or {"active": 28}}}


class StopConditions(unittest.TestCase):
    def test_healthy(self):
        self.assertEqual(wt.stop_conditions(health()), [])

    def test_each_condition(self):
        self.assertIn("indexer heap above 85%", wt.stop_conditions(health(heap=90)))
        self.assertIn("free RAM under 800MB", wt.stop_conditions(health(mem=500)))
        self.assertIn("a queue above 50%", wt.stop_conditions(health(queues={"alerts_queue_usage": 0.6})))
        self.assertIn("events_dropped increased", wt.stop_conditions(health(dropped=3), baseline_dropped=0))
        self.assertIn("an agent is not active", wt.stop_conditions(health(status={"active": 27, "disconnected": 1})))

    def test_dropped_ignored_without_baseline(self):
        self.assertEqual(wt.stop_conditions(health(dropped=9)), [])


class Diff(unittest.TestCase):
    def test_diff(self):
        d = wt.diff_json({"a": {"b": 1, "c": 2}, "x": 1}, {"a": {"b": 1, "c": 3}})
        self.assertEqual(d, [("/a/c", 2, 3), ("/x", 1, None)])


class Cases(unittest.TestCase):
    def test_cases_file_is_well_formed(self):
        spec = json.load(open(os.path.join(os.path.dirname(__file__), "must_fire_cases.json")))
        for c in spec["cases"]:
            self.assertTrue(c.get("event") or c.get("sample_rule"), c["name"])
            self.assertTrue(c["ids"] and c["min_level"] > 0, c["name"])

    def test_check(self):
        c = {"ids": ["5760"], "min_level": 5}
        self.assertTrue(must_fire.check(c, "5760", 5))
        self.assertFalse(must_fire.check(c, "5760", 3))   # level dropped
        self.assertFalse(must_fire.check(c, "", 0))       # nothing fired


if __name__ == "__main__":
    unittest.main()
