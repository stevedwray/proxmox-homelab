#!/usr/bin/env python3
"""Simple Phase 0 plan classifier for storage-related field transitions.

This script consumes a `terraform show -json` plan output (or similar JSON
with `resource_changes`) and emits a conservative classification for
storage-related transitions.

It is intentionally conservative: unknown or ambiguous diffs map to `blocked`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import datetime


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def classify_change(change: dict[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    actions = change.get("change", {}).get("actions", [])
    before = change.get("change", {}).get("before")
    after = change.get("change", {}).get("after")

    # Heuristics: traverse nested before/after structures to find keys that look
    # like storage-related attributes (size, path, mount_point, disk entries).

    def traverse(obj: Any, prefix: str = "") -> list[tuple[str, Any]]:
        items: list[tuple[str, Any]] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                path = f"{prefix}/{k}" if prefix else k
                items.append((path, v))
                items.extend(traverse(v, path))
        elif isinstance(obj, list):
            for idx, v in enumerate(obj):
                path = f"{prefix}[{idx}]"
                items.append((path, v))
                items.extend(traverse(v, path))
        return items

    before_items = traverse(before) if before else []
    after_items = traverse(after) if after else []

    def is_storage_related_item(path: str, value: Any) -> bool:
        lowered = path.lower()
        if any(token in lowered for token in (
            "mount_point",
            "mountpoint",
            "docker",
            "extra_mount",
            "rootfs",
            "datastore_id",
            "volume",
        )):
            return True
        if ("disk[" in lowered or "/disk[" in lowered or "disk]/" in lowered) and any(
            token in lowered for token in ("size", "datastore_id", "volume")
        ):
            return True
        if isinstance(value, str) and value == "/var/lib/docker":
            return True
        if isinstance(value, str) and value.startswith("/") and any(
            token in lowered for token in ("mount", "path")
        ):
            return True
        return False

    storage_related = any(
        is_storage_related_item(path, value) for path, value in [*before_items, *after_items]
    )

    # If provider reports replacement via actions, only treat it as storage
    # risk when the diff surface is storage-related.
    if any(a in ("delete", "create", "replace") for a in actions):
        if storage_related:
            results.append({"field_transition": "provider_replacement", "class": "replacement-sensitive"})
        return results

    def find_size_entries(items: list[tuple[str, Any]]) -> dict[str, int]:
        found: dict[str, int] = {}
        for path, valv in items:
            # key name contains 'size' and value is scalar-like
            if path.lower().endswith("/size") or "/size" in path.lower() or path.lower().endswith("_size"):
                try:
                    found[path] = parse_size(valv)
                except Exception:
                    found[path] = 0
            # also accept numeric values whose key contains 'disk' and 'size' nearby
            elif isinstance(valv, (str, int, float)) and ("g" in str(valv).lower() or str(valv).isdigit()):
                if any(k in path.lower() for k in ("docker", "rootfs", "disk", "extra", "volume")) and "size" in path.lower():
                    found[path] = parse_size(valv)
        return found

    def find_path_entries(items: list[tuple[str, Any]]) -> dict[str, str]:
        found: dict[str, str] = {}
        for path, valv in items:
            if isinstance(valv, str) and valv.startswith("/"):
                # likely a mount path
                found[path] = valv
            if path.lower().endswith("/mount_point") or path.lower().endswith("/mountpoint") or "mount_point" in path.lower():
                if isinstance(valv, str):
                    found[path] = valv
        return found

    def find_backup_entries(items: list[tuple[str, Any]]) -> dict[str, bool]:
        found: dict[str, bool] = {}
        for path, valv in items:
            lowered = path.lower()
            if lowered.endswith("/backup") or "/backup" in lowered:
                if isinstance(valv, bool):
                    found[path] = valv
        return found

    before_sizes = find_size_entries(before_items)
    after_sizes = find_size_entries(after_items)
    before_paths = find_path_entries(before_items)
    after_paths = find_path_entries(after_items)
    before_backups = find_backup_entries(before_items)
    after_backups = find_backup_entries(after_items)

    # Compare size entries and map according to Phase 0 capability matrix
    for path, new_size in after_sizes.items():
        old_size = before_sizes.get(path)
        if old_size is None:
            # New size entry introduced — treat as first extra-mount introduction or
            # as an explicit new mount. Phase 0 policy: block additives unless
            # explicitly proven safe.
            results.append({"field_transition": "new_size_introduced", "class": "blocked"})
        else:
            if new_size > old_size:
                # Increase detected — classify conservatively per matrix.
                # Prefer detecting disk[] entries (rootfs) first, then docker mount,
                # then fallback to blocked for ambiguous mount size changes.
                p = path.lower()
                if "disk[" in p or "/disk[" in p or "disk]/size" in p:
                    results.append({"field_transition": "rootfs_size_increase", "class": "safe-in-place"})
                elif "rootfs" in p or "root" in p:
                    results.append({"field_transition": "rootfs_size_increase", "class": "safe-in-place"})
                elif "docker" in p or any(isinstance(v[1], str) and "/var/lib/docker" in v[1] for v in before_items):
                    results.append({"field_transition": "docker_mount_increase", "class": "replacement-sensitive"})
                else:
                    results.append({"field_transition": "mount_size_increase", "class": "blocked"})
            elif new_size < old_size:
                results.append({"field_transition": "size_decrease", "class": "blocked"})

    # Detect mount path additions or changes
    for path, newp in after_paths.items():
        oldp = before_paths.get(path)
        if oldp is None:
            # new mount path added — first extra-mount introduction is blocked in Phase 0
            results.append({"field_transition": "extra_mount_introduce", "class": "blocked"})
        elif oldp != newp:
            # Path changes are conservatively blocked (risk of data-masking and delete/create semantics)
            results.append({"field_transition": "mount_path_change", "class": "blocked"})

    # Detect explicit mount backup-policy updates. These are expected to be
    # in-place metadata changes under the current provider path and should not
    # be treated as unsafe storage mutations.
    for path, new_backup in after_backups.items():
        old_backup = before_backups.get(path)
        if old_backup is not None and old_backup != new_backup:
            results.append({"field_transition": "mount_backup_policy_update", "class": "safe-in-place"})

    # If nothing matched, only block when the provider diff still looked
    # storage-related. Non-storage container drift should not fail storage-only
    # checks wired into broader workflow paths.
    if not results and storage_related:
        results.append({"field_transition": "unknown_or_ambiguous", "class": "blocked"})

    return results


def parse_size(val: str | int | float | None) -> int:
    # Accept strings like '8G' or numeric values (GB assumed)
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip().upper()
    try:
        if s.endswith("G"):
            return int(float(s[:-1]))
        if s.endswith("M"):
            return int(float(s[:-1]) / 1024)
        return int(float(s))
    except Exception:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", required=True, help="Path to terraform show -json output")
    parser.add_argument("--stack-name", required=False, help="Stack name for metadata")
    parser.add_argument("--out", required=False, help="Path to write JSON output (defaults to stdout)")
    args = parser.parse_args()

    plan = load_json(Path(args.plan_json))
    resource_changes = plan.get("resource_changes") or []

    classified: dict[str, Any] = {
        "stack_name": args.stack_name or "<unknown>",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "plan_path": args.plan_json,
        "classified_transitions": [],
    }

    for change in resource_changes:
        # We only care about container resources and mount_point-like resources.
        # Being conservative: classify any storage-related-looking change.
        pathname = change.get("address") or ""
        if "container" in pathname or "mount" in pathname or "docker" in pathname or "extra_mount" in pathname:
            classified_transitions = classify_change(change)
            for c in classified_transitions:
                classified["classified_transitions"].append({"address": pathname, **c})

    out = json.dumps(classified, indent=2, sort_keys=True)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out)
        print(f"Wrote classification to {args.out}")
    else:
        print(out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
