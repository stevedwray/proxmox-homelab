"""Smoke tests for the data-flow graph viewer builder."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

# columns: key, kind, name, zone, class, trust, status, cluster, node, protocol, ports, address, vid, tier
NODES = [["p-a", "Process", "a-stack", "mgmt_seg", None, None, None, None, None, None, None, None, None, "platform"],
         ["p-b", "Process", "</script><script>alert(1)</script>", "infra_seg", None, None, None, None, None, None, None, None, None, "platform"],
         ["ee-u", "ExternalEntity", "LAN User", None, None, "medium", None, None, None, None, None, None, None, None]]
# columns: from, to, type, protocol, port, auth_kind, encrypted, crosses_zone, from_zone, to_zone, class, tb, flow_type
RELS = [["ee-u", "p-a", "FLOWS_TO", "tcp", 443, "none", False, True, "external", "mgmt_seg", "internal", None, None],
        ["p-a", "p-b", "FLOWS_TO", "tcp", 9000, "none", False, True, "mgmt_seg", "infra_seg", "internal", None, None]]


class BuildGraphView(unittest.TestCase):
    def _build(self):
        with tempfile.TemporaryDirectory() as d:
            export, out = Path(d) / "e.json", Path(d) / "o.html"
            export.write_text(json.dumps({"nodes": NODES, "rels": RELS}))
            run = subprocess.run([sys.executable, str(HERE / "build_graph_view.py"), str(export), str(out)],
                                 capture_output=True, text=True)
            return run, out.read_text() if out.exists() else ""

    def test_builds_a_page_with_the_risky_flows_counted(self):
        run, html = self._build()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn("__DATA__", html)
        self.assertIn("risky", run.stdout)  # both flows cross a zone, are unencrypted and have auth none

    def test_a_hostile_name_cannot_break_out_of_the_script_block(self):
        _run, html = self._build()
        self.assertEqual(html.count("</script>"), 1)


if __name__ == "__main__":
    unittest.main()
