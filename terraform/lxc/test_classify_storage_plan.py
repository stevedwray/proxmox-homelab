"""Tests for the storage-plan classifier's no-op handling.

Regression coverage for the 2026-07-07 fix: a Terraform no-op action (zero
drift) against a resource with disk/mount_point/datastore_id fields used to
fall through to the "unknown_or_ambiguous" -> blocked catch-all, since
`storage_related` is computed from field *names* present in the plan, not
from whether anything actually changed. This affected every LXC stack's
storage-plan-safety check in docs/teardown-test's harness.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "classify-storage-plan.py"
SPEC = importlib.util.spec_from_file_location("classify_storage_plan", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_change(actions, before, after):
    return {"change": {"actions": actions, "before": before, "after": after}}


STORAGE_STATE = {
    "disk": [{"datastore_id": "infrastructure-containers", "size": 8}],
    "mount_point": [
        {
            "path": "/var/lib/docker",
            "path_in_datastore": "infrastructure-containers:subvol-40011-disk-3",
            "size": "20G",
            "backup": True,
        }
    ],
}


class TestNoOpHandling(unittest.TestCase):
    def test_no_op_with_storage_fields_yields_no_transitions(self):
        change = make_change(["no-op"], STORAGE_STATE, STORAGE_STATE)
        self.assertEqual(MODULE.classify_change(change), [])

    def test_no_op_is_checked_before_storage_related_scan(self):
        # Identical before/after but with a plain benign non-storage field
        # thrown in too -- still must yield nothing for a genuine no-op.
        before = {**STORAGE_STATE, "description": "Managed by Terraform\n"}
        change = make_change(["no-op"], before, before)
        self.assertEqual(MODULE.classify_change(change), [])


class TestExistingBehaviorUnaffected(unittest.TestCase):
    def test_rootfs_size_increase_is_safe_in_place(self):
        before = {"disk": [{"datastore_id": "infrastructure-containers", "size": 8}]}
        after = {"disk": [{"datastore_id": "infrastructure-containers", "size": 12}]}
        change = make_change(["update"], before, after)
        results = MODULE.classify_change(change)
        self.assertTrue(
            any(r["class"] == "safe-in-place" for r in results),
            f"expected a safe-in-place rootfs size increase, got {results}",
        )

    def test_size_decrease_is_blocked(self):
        before = {"disk": [{"datastore_id": "infrastructure-containers", "size": 12}]}
        after = {"disk": [{"datastore_id": "infrastructure-containers", "size": 8}]}
        change = make_change(["update"], before, after)
        results = MODULE.classify_change(change)
        self.assertTrue(
            any(r["class"] == "blocked" for r in results),
            f"expected a blocked size decrease, got {results}",
        )

    def test_pure_create_in_fresh_workspace_is_safe(self):
        after = {"disk": [{"datastore_id": "infrastructure-containers", "size": 8}]}
        change = make_change(["create"], None, after)
        self.assertEqual(MODULE.classify_change(change), [])

    def test_replace_with_prior_state_is_replacement_sensitive(self):
        before = {"disk": [{"datastore_id": "infrastructure-containers", "size": 8}]}
        after = {"disk": [{"datastore_id": "infrastructure-containers", "size": 8}]}
        change = make_change(["delete", "create"], before, after)
        results = MODULE.classify_change(change)
        self.assertTrue(
            any(r["class"] == "replacement-sensitive" for r in results),
            f"expected replacement-sensitive, got {results}",
        )


if __name__ == "__main__":
    unittest.main()
