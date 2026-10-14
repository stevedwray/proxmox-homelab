import glob
import os
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
# FIM ignore entries must never reach into the places FIM exists to watch
PROTECTED = ("/etc/", "/usr/", "/bin/", "/sbin/", "/boot/", "/root/", "/home/", "/var/spool/cron")
ALLOWED_UNDER_PROTECTED = {"/etc/pve/nodes/pve/lrm_status"}


class AgentConf(unittest.TestCase):
    def parse(self, path):
        return ET.fromstring("<r>" + open(path).read() + "</r>")

    def test_well_formed_and_scoped_by_agent_name(self):
        for path in glob.glob(os.path.join(HERE, "agent_conf", "*.xml")):
            for block in self.parse(path).iter("agent_config"):
                if block.find("syscheck") is not None:
                    self.assertTrue(block.get("name"), f"{path}: syscheck block without name= scope")

    def test_ignores_do_not_touch_protected_paths(self):
        for path in glob.glob(os.path.join(HERE, "agent_conf", "*.xml")):
            for ig in self.parse(path).iter("ignore"):
                p = ig.text.strip()
                if p.startswith(PROTECTED):
                    self.assertIn(p, ALLOWED_UNDER_PROTECTED, f"{path}: {p}")
                self.assertGreater(len(p), len("/opt/"), p)   # no bare directory-level ignores


if __name__ == "__main__":
    unittest.main()
