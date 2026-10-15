import unittest

import wazuh_metrics as m

AGENT_CONTROL = """
Wazuh agent_control. List of available agents:
   ID: 000, Name: wazuh.manager (server), IP: 127.0.0.1, Active/Local
   ID: 001, Name: authentik-stack, IP: any, Active
   ID: 002, Name: proxy-stack, IP: any, Disconnected
   ID: 003, Name: new-box, IP: any, Never connected

List of agentless devices:
"""


class Parsing(unittest.TestCase):
    def test_agent_control(self):
        a = m.parse_agent_control(AGENT_CONTROL)
        self.assertEqual([x["id"] for x in a], ["000", "001", "002", "003"])
        self.assertEqual(a[3]["status"], "Never connected")
        self.assertEqual(m.status_counts(a), {"Active": 1, "Disconnected": 1, "Never connected": 1, "Pending": 0})

    def test_state_keeps_numbers_only(self):
        s = m.parse_state("# header\nevents_dropped='3'\nalerts_queue_usage=0.25\nnote='text'\n")
        self.assertEqual(s, {"events_dropped": 3.0, "alerts_queue_usage": 0.25})

    def test_top_share(self):
        self.assertEqual(m.top_share([("87907", 90)], 100), 90.0)
        self.assertEqual(m.top_share([], 100), 0.0)
        self.assertEqual(m.top_share([("x", 5)], 0), 0.0)

    def test_index_date(self):
        self.assertIsNotNone(m.index_date("wazuh-alerts-4.x-2026.08.29"))
        self.assertIsNone(m.index_date("wazuh-alerts-4.x-latest"))


class Format(unittest.TestCase):
    def test_labels_are_escaped(self):
        self.assertEqual(m.metric("x", 1, a='say "hi"\nnow'), 'x{a="say \\"hi\\" now"} 1')
        self.assertEqual(m.metric("y", 2), "y 2")

    def test_header(self):
        self.assertEqual(m.header("n", "h"), ["# HELP n h", "# TYPE n gauge"])


if __name__ == "__main__":
    unittest.main()
