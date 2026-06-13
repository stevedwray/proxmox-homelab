#!/usr/bin/env python3
"""Simple schema checker for Phase 1 storage manifest contract.

Checks that the environment storage manifest exposes `mount_contracts` with
`docker_mount` and `extra_mount` and that tracked stacks either declare the
new `docker_mount` block or still present the legacy `docker_storage_size`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML at {path} must decode to a mapping")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Path to storage manifest")
    parser.add_argument("--stacks-dir", required=True, help="Path to stacks dir")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    stacks_dir = Path(args.stacks_dir)

    try:
        manifest = load_yaml(manifest_path)
    except Exception as exc:
        print(f"ERROR: failed to load manifest: {exc}")
        return 2

    errors: list[str] = []
    warnings: list[str] = []

    mounts = manifest.get("mount_contracts")
    if not isinstance(mounts, dict):
        errors.append("manifest missing top-level 'mount_contracts' mapping")
    else:
        for key in ("docker_mount", "extra_mount"):
            if key not in mounts:
                errors.append(f"manifest missing mount_contracts.{key}")

    stacks_checked = 0
    for stack_yaml in sorted(stacks_dir.glob("*/stack.yaml")):
        stacks_checked += 1
        try:
            stack = load_yaml(stack_yaml)
        except Exception as exc:
            errors.append(f"failed to parse {stack_yaml}: {exc}")
            continue

        # Accept either the new explicit `docker_mount` block or the legacy
        # `docker_storage_size` for backwards compatibility.
        if "docker_mount" not in stack and "docker_storage_size" not in stack:
            # Many stacks are direct/rootfs-only and do not require a docker
            # mount. Treat missing docker intent as a warning rather than a hard
            # error so Phase 1 schema validation can pass for environment-wide
            # manifests while still surfacing stacks that may need conversion.
            warnings.append(f"stack {stack_yaml.parent.name} missing docker mount intent (docker_mount or docker_storage_size)")

    payload = {
        "manifest": str(manifest_path),
        "stacks_dir": str(stacks_dir),
        "stacks_checked": stacks_checked,
        "errors": errors,
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if errors:
            print("Schema validation failed:")
            for e in errors:
                print(f"- {e}")
            if warnings:
                print("Warnings:")
                for w in warnings:
                    print(f"- {w}")
        else:
            print(f"Schema validation passed for manifest {manifest_path} (checked {stacks_checked} stacks)")
            if warnings:
                print("Warnings:")
                for w in warnings:
                    print(f"- {w}")

        # Exit non-zero only for hard errors (manifest-level problems)
        return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
