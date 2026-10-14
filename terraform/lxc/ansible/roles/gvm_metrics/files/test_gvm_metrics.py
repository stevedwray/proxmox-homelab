import unittest

import gvm_metrics as m


class KindTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(m.kind_of("Credentialed scan: ai_seg"), "credentialed")
        self.assertEqual(m.kind_of("LAN scan: lan discovery"), "discovery")
        self.assertEqual(m.kind_of("LAN scan: lan full-vuln"), "full_vuln")
        self.assertEqual(m.kind_of("OCI Pangolin public edge"), "other")


class TaskLineTests(unittest.TestCase):
    TASKS = [
        {"name": "Credentialed scan: ai_seg", "status": "Done", "progress": "-1", "schedule": "w",
         "last_scan_start": "2026-10-12T21:59:06Z", "last_scan_end": "2026-10-12T22:09:06Z",
         "last_counts": {"hole": 0, "warning": 2, "info": 1, "log": 40}},
        {"name": "LAN scan: lan full-vuln", "status": "Running", "progress": "42", "schedule": None,
         "last_scan_start": None, "last_scan_end": None, "last_counts": None},
    ]

    def setUp(self):
        self.text = "\n".join(m.task_lines(self.TASKS))

    def test_status_counts_include_zeroes(self):
        self.assertIn('gvm_tasks{kind="credentialed",status="Done"} 1', self.text)
        self.assertIn('gvm_tasks{kind="discovery",status="Running"} 0', self.text)
        self.assertIn('gvm_tasks{kind="full_vuln",status="Running"} 1', self.text)

    def test_duration_and_results(self):
        self.assertIn('gvm_task_last_scan_duration_seconds{task="Credentialed scan: ai_seg",kind="credentialed"} 600', self.text)
        self.assertIn('severity="warning"} 2', self.text)

    def test_progress_only_while_running(self):
        self.assertIn('gvm_task_progress_percent{task="LAN scan: lan full-vuln",kind="full_vuln"} 42', self.text)
        self.assertNotIn('gvm_task_progress_percent{task="Credentialed', self.text)

    def test_label_escaping(self):
        self.assertEqual(m.esc('a"b\\c'), 'a\\"b\\\\c')


class RedisTests(unittest.TestCase):
    def test_parse_and_scan_kbs(self):
        info = m.parse_redis_info(
            "used_memory:419430400\nused_memory_human:400M\n",
            "# Keyspace\ndb0:keys=1,expires=0\ndb1:keys=91276,expires=0\ndb3:keys=4,expires=0\ndb4:keys=117233,expires=0\n",
            "6442450944",
        )
        text = "\n".join(m.redis_lines(info))
        self.assertIn("gvm_redis_used_memory_bytes 419430400", text)
        self.assertIn("gvm_redis_maxmemory_bytes 6442450944", text)
        self.assertIn('gvm_redis_keys{db="db4"} 117233', text)
        self.assertIn("gvm_redis_scan_kbs 2", text)


if __name__ == "__main__":
    unittest.main()
