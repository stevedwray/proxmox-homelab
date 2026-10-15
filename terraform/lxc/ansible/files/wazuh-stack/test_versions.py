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


if __name__ == "__main__":
    unittest.main()
