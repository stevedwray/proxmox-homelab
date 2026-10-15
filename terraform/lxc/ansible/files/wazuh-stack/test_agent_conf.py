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

    def render_ossec_conf(self, use_journald, trim_blocks):
        import jinja2
        import yaml
        path = os.path.join(HERE, "..", "..", "roles", "wazuh_agent", "tasks", "main.yml")
        task = next(t for t in yaml.safe_load(open(path)) if t.get("name") == "Write this host's ossec.conf")
        env = jinja2.Environment(trim_blocks=trim_blocks)
        env.filters["bool"] = bool
        return env.from_string(task["ansible.builtin.copy"]["content"]).render(
            wazuh_agent_manager_ip="192.0.2.1", wazuh_agent_docker_monitoring_enabled=False,
            wazuh_agent_fim_paths=[], wazuh_agent_use_journald=use_journald)

    def test_log_source_files_by_default_journald_when_no_rsyslog(self):
        for trim_blocks in (True, False):   # Ansible templates with trim_blocks on; the output must not depend on it
            files = self.render_ossec_conf(False, trim_blocks)
            journald = self.render_ossec_conf(True, trim_blocks)
            ET.fromstring(files)
            ET.fromstring(journald)
            self.assertIn("<location>/var/log/auth.log</location>", files)
            self.assertNotIn("journald", files)
            self.assertIn("<log_format>journald</log_format>", journald)
            self.assertNotIn("/var/log/auth.log", journald)
            # the LXC fleet keeps exactly the blank-line layout it had before journald support existed
            self.assertIn("</syscheck>\n\n  <localfile>\n    <log_format>syslog</log_format>", files.replace("        ", ""))


if __name__ == "__main__":
    unittest.main()
