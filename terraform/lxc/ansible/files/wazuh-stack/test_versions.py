import os
import re
import unittest

ANSIBLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")


def find(path, pattern):
    return re.search(pattern, open(os.path.join(ANSIBLE, path)).read()).group(1)


class Versions(unittest.TestCase):
    def test_manager_and_agent_versions_match(self):
        manager = find("playbooks/deploy-wazuh-stack.yml", r'wazuh_image_tag: "([\d.]+)"')
        agent = find("roles/wazuh_agent/defaults/main.yml", r'wazuh_agent_version: "([\d.]+)"')
        self.assertEqual(manager, agent)

    def test_agent_package_is_held_after_install(self):
        tasks = open(os.path.join(ANSIBLE, "roles/wazuh_agent/tasks/main.yml")).read()
        unhold, install, hold = (tasks.index(x) for x in ("apt-mark, unhold, wazuh-agent", "name: Install the wazuh-agent package", "apt-mark, hold, wazuh-agent"))
        self.assertLess(unhold, install)   # a version change needs the hold lifted first
        self.assertLess(install, hold)     # and re-applied afterwards


if __name__ == "__main__":
    unittest.main()
