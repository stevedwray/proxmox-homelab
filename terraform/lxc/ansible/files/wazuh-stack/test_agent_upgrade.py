import os
import unittest

ANSIBLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")


class AgentUpgradePlay(unittest.TestCase):
    def setUp(self):
        self.text = open(os.path.join(ANSIBLE, "playbooks", "wazuh-agent-upgrade.yml")).read()

    def test_one_host_at_a_time_and_stops_on_failure(self):
        self.assertIn("serial: 1", self.text)
        self.assertIn("max_fail_percentage: 0", self.text)

    def test_no_all_hosts_default_and_config_untouched(self):
        self.assertIn("upgrade_agents is defined", self.text)       # explicit list required
        for forbidden in ("ossec.conf", "client.keys", "agent-auth", "wazuh_agent_group", "include_role"):
            code = "\n".join(line for line in self.text.splitlines() if not line.lstrip().startswith("#"))
            self.assertNotIn(forbidden, code, forbidden)

    def test_hold_lifted_before_install_and_reapplied_after(self):
        unhold, install, hold = (self.text.index(x) for x in ("apt-mark, unhold", "Install the pinned wazuh-agent", "apt-mark, hold"))
        self.assertLess(unhold, install)
        self.assertLess(install, hold)

    def test_version_comes_from_the_role_default_and_never_downgrades(self):
        self.assertIn("roles/wazuh_agent/defaults/main.yml", self.text)
        self.assertIn("allow_downgrade: false", self.text)
        self.assertIn("is version(", self.text)                      # never past the manager


if __name__ == "__main__":
    unittest.main()
