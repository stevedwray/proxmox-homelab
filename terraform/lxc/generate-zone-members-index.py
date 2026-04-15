#!/usr/bin/env python3
"""Generate an environment-scoped zone-members index from stack metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data or {}


def build_zone_members_index(stacks_dir: Path, network_intent_path: Path) -> dict:
    network_intent = load_yaml(network_intent_path)
    zones = network_intent.get("zones", {})
    attachments = network_intent.get("attachments", {})

    zone_gateways = {
        zone_name: attachments.get(zone.get("attachment"), {}).get("sdn", {}).get("gateway")
        for zone_name, zone in zones.items()
    }

    index = {
        "generated_from": {
            "network_intent": str(network_intent_path),
            "stacks_dir": str(stacks_dir),
        },
        "zones": {
            zone_name: []
            for zone_name in zones
        },
    }

    for stack_path in sorted(stacks_dir.glob("*/stack.yaml")):
        if ".hold" in stack_path.parts:
            continue

        stack = load_yaml(stack_path)
        zone_name = stack.get("network", {}).get("zone")
        if zone_name not in zones:
            continue

        gateway = stack.get("gateway")
        zone_gateway = zone_gateways.get(zone_name)
        if zone_gateway and gateway != zone_gateway:
            continue

        ip_raw = stack.get("ip_address")
        if not ip_raw:
            continue

        index["zones"][zone_name].append(
            {
                "stack_name": stack_path.parent.name,
                "ip_address": str(ip_raw).split("/", 1)[0],
                "description": stack.get("hostname", stack_path.parent.name),
            }
        )

    return index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a zone-members index from stack.yaml metadata."
    )
    parser.add_argument(
        "--stacks-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "stacks",
        help="Directory containing stack subdirectories with stack.yaml files.",
    )
    parser.add_argument(
        "--network-intent",
        type=Path,
        required=True,
        help="Path to the environment network intent YAML file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the generated zone-members YAML index.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index = build_zone_members_index(
        stacks_dir=args.stacks_dir.resolve(),
        network_intent_path=args.network_intent.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(index, handle, sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
