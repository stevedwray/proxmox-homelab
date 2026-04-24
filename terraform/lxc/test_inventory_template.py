import os
import unittest


class TestInventoryTemplate(unittest.TestCase):
    TEMPLATE_PATH = "terraform/lxc/templates/inventory.tpl"

    def test_template_renders_ansible_playbook_conditionally(self):
        with open(self.TEMPLATE_PATH) as f:
            content = f.read()
        self.assertIn(
            "%{ if ansible_playbook",
            content,
            "inventory.tpl must render ansible_playbook conditionally",
        )

    def test_generated_harbor_inventory_has_playbook(self):
        path = "terraform/lxc/stacks/harbor-stack/inventory.yml"
        if not os.path.exists(path):
            self.skipTest("harbor-stack inventory not yet generated")
        with open(path) as f:
            content = f.read()
        self.assertIn("ansible_playbook:", content)

    def test_generated_test_lxc_inventory_has_no_playbook(self):
        path = "terraform/lxc/stacks/test-lxc/inventory.yml"
        if not os.path.exists(path):
            self.skipTest("test-lxc inventory not yet generated")
        with open(path) as f:
            content = f.read()
        self.assertNotIn("ansible_playbook:", content)
