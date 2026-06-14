import os
import importlib.util
import unittest
from pathlib import Path


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
        self.assertIn("enable_docker_socket_proxy:", content)
        self.assertIn("docker_socket_proxy_bind_addr:", content)
        self.assertIn("docker_socket_proxy_listen_port:", content)
        self.assertIn("docker_socket_proxy_targets:", content)

    def test_render_inventory_resolves_socket_proxy_metadata(self):
        module_path = Path("scripts/render-inventory.py")
        spec = importlib.util.spec_from_file_location("render_inventory", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        env = {"LAB_IP_MONITORING": "192.168.20.12"}
        self.assertEqual(
            module.resolve_metadata_value("${lab_ip_monitoring}", env),
            "192.168.20.12",
        )
        self.assertEqual(
            module.resolve_metadata_value(["${lab_ip_monitoring}"], env),
            ["192.168.20.12"],
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
