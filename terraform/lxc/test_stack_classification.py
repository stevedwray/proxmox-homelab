import glob
import os
import unittest
import yaml

PLATFORM_STACKS = [
    "portainer-stack",
    "harbor-stack",
    "apt-cacher-stack",
    "ci-runner-01",
    "dns-stack",
    "step-ca-stack",
    "authentik-stack",
    "proxy-stack",
    "monitoring-stack",
    "netbox-stack",
]


class TestStackClassification(unittest.TestCase):
    STACKS_DIR = "terraform/lxc/stacks"

    def _load_stack_yaml(self, stack):
        path = os.path.join(self.STACKS_DIR, stack, "stack.yaml")
        with open(path) as f:
            return yaml.safe_load(f)

    def test_platform_stacks_have_deployment_tier_platform(self):
        for stack in PLATFORM_STACKS:
            with self.subTest(stack=stack):
                data = self._load_stack_yaml(stack)
                self.assertEqual(
                    data.get("deployment_tier"), "platform",
                    f"{stack}/stack.yaml must have deployment_tier: platform",
                )

    def test_platform_stacks_have_portainer_agent_false(self):
        for stack in PLATFORM_STACKS:
            with self.subTest(stack=stack):
                data = self._load_stack_yaml(stack)
                self.assertFalse(
                    data.get("portainer_agent", False),
                    f"{stack}/stack.yaml must have portainer_agent: false",
                )

    def test_all_stacks_define_dns_server(self):
        for stack_yaml in sorted(glob.glob(os.path.join(self.STACKS_DIR, "*", "stack.yaml"))):
            stack = os.path.basename(os.path.dirname(stack_yaml))

            with self.subTest(stack=stack):
                data = self._load_stack_yaml(stack)
                self.assertIn(
                    "dns_server",
                    data,
                    f"{stack}/stack.yaml must set dns_server explicitly",
                )
                self.assertTrue(
                    str(data.get("dns_server", "")).strip(),
                    f"{stack}/stack.yaml must set a non-empty dns_server",
                )
