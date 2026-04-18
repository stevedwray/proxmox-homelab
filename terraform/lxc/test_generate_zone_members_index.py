"""Tests for generate-zone-members-index.py."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


MODULE_PATH = Path(__file__).resolve().parent / "generate-zone-members-index.py"
SPEC = importlib.util.spec_from_file_location("generate_zone_members_index", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TestBuildZoneMembersIndex(unittest.TestCase):
    def test_filters_members_to_matching_zone_gateway(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stacks_dir = root / "stacks"
            stacks_dir.mkdir()

            (stacks_dir / "harbor-stack").mkdir()
            (stacks_dir / "harbor-stack" / "stack.yaml").write_text(
                yaml.safe_dump(
                    {
                        "hostname": "harbor-stack",
                        "ip_address": "10.57.3.10/24",
                        "gateway": "10.57.3.1",
                        "network": {"zone": "infra_seg"},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            (stacks_dir / "net-service-01").mkdir()
            (stacks_dir / "net-service-01" / "stack.yaml").write_text(
                yaml.safe_dump(
                    {
                        "hostname": "net-service-01",
                        "ip_address": "10.55.0.62/24",
                        "gateway": "10.55.0.1",
                        "network": {"zone": "infra_seg"},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            intent_path = root / "pve-test.yaml"
            intent_path.write_text(
                yaml.safe_dump(
                    {
                        "attachments": {
                            "infra_seg": {
                                "sdn": {
                                    "gateway": "10.57.3.1",
                                }
                            }
                        },
                        "zones": {
                            "infra_seg": {
                                "attachment": "infra_seg",
                            }
                        },
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            index = MODULE.build_zone_members_index(stacks_dir, intent_path)

        self.assertEqual(
            index["zones"]["infra_seg"],
            [
                {
                    "stack_name": "harbor-stack",
                    "ip_address": "10.57.3.10",
                    "description": "harbor-stack",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
