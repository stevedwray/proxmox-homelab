import glob
import os
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
# FIM ignore entries must never reach into the places FIM exists to watch
PROTECTED = ("/etc/", "/usr/", "/bin/", "/sbin/", "/boot/", "/root/", "/home/", "/var/spool/cron")
ALLOWED_UNDER_PROTECTED = {"/etc/pve/nodes/pve/lrm_status", "/etc/pve/nodes/pve-test/lrm_status"}


class AgentConf(unittest.TestCase):
    def parse(self, path):
        return ET.fromstring("<r>" + open(path).read() + "</r>")

    def test_well_formed_and_scoped_by_agent_name(self):
        for path in glob.glob(os.path.join(HERE, "agent_conf", "*.xml")):
            if path.endswith("common.xml"):   # fleet-wide on purpose; test_common_block_* pins what it may contain
                continue
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


    def test_common_block_protects_secrets_and_enables_rootkit_checks(self):
        root = self.parse(os.path.join(HERE, "agent_conf", "common.xml"))
        nodiff = " ".join(n.text for n in root.iter("nodiff"))
        for must in ("^/etc/shadow", "^/etc/pve/priv/", ".key$", ".env$", "id_rsa$"):
            self.assertIn(must, nodiff)
        self.assertEqual({r.text for r in root.iter("rootkit_files")}, {"etc/shared/rootkit_files.txt"})
        self.assertEqual({r.text for r in root.iter("rootkit_trojans")}, {"etc/shared/rootkit_trojans.txt"})
        # nodiff must never be confused with ignore: the common block ignores nothing
        self.assertEqual(list(root.iter("ignore")), [])

    def test_role_and_common_nodiff_agree(self):
        role = open(os.path.join(HERE, "..", "..", "roles", "wazuh_agent", "tasks", "main.yml")).read()
        common = self.parse(os.path.join(HERE, "agent_conf", "common.xml"))
        pattern = next(common.iter("nodiff")).text
        self.assertIn(pattern, role)
        self.assertIn("<rootkit_files>etc/shared/rootkit_files.txt</rootkit_files>", role)
        self.assertNotIn("ubuntu24", role)


if __name__ == "__main__":
    unittest.main()
