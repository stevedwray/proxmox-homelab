#!/usr/bin/env python3
"""Generate a stack-architecture snapshot for the UVM deep-dive assessment.

See docs/threat-vuln-platform/plan.md's Phase 11 (CVE deep-dive):
cve_deep_dive.py needs real architecture context per stack -- its network
zone (and that zone's containment policy), whether it's reachable through
the shared reverse proxy, and whether that route is auth-gated -- to turn
a bare CVE triage into a genuine remediation call ("this is CRITICAL but
isolated in pentest_seg with no edge route" vs "this is CRITICAL and
sitting unauthenticated on the shared edge").

Deliberately reuses generate-zone-members-index.py's exact technique
(load each stacks/*/stack.yaml, cross-reference the environment's network
intent YAML for zone metadata) rather than inventing a new one, plus reads
each stack's own edge.yaml (if present) for its Traefik-route/auth
posture. Both are structured YAML already treated as source of truth
elsewhere in this repo -- no prose (STACK_CONTRACT.md) parsing, which
would be fragile.

Deliberately does NOT attempt a full stack-to-stack dependency graph
(STACK_CONTRACT.md's "Inputs" tables reference other stacks by env var/
hostname in free text, not a structured field) -- zone + edge exposure is
enough real signal for a home-lab blast-radius judgment without guessing
at a dependency graph this repo doesn't actually encode anywhere.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def build_stack_architecture(stacks_dir: Path, network_intent_path: Path) -> dict:
    network_intent = load_yaml(network_intent_path)
    zones = network_intent.get("zones", {})
    zone_descriptions = {
        zone_name: zone.get("description", "") for zone_name, zone in zones.items()
    }

    stacks: dict[str, dict] = {}
    for stack_path in sorted(stacks_dir.glob("*/stack.yaml")):
        if ".hold" in stack_path.parts:
            continue
        stack_name = stack_path.parent.name
        stack = load_yaml(stack_path)
        zone_name = stack.get("network", {}).get("zone")

        edge_path = stack_path.parent / "edge.yaml"
        edge_exposed = False
        edge_auth_mode = None
        if edge_path.exists():
            edge = load_yaml(edge_path)
            routes = edge.get("spec", {}).get("routes", [])
            if routes:
                edge_exposed = True
                # First route's auth mode -- every stack observed to date
                # declares exactly one route with one auth mode; take the
                # first rather than over-generalizing to multi-route stacks
                # that don't exist yet.
                edge_auth_mode = routes[0].get("auth", {}).get("mode")

        stacks[stack_name] = {
            "zone": zone_name,
            "zone_description": zone_descriptions.get(zone_name, ""),
            "vmid": stack.get("vmid"),
            "edge_exposed": edge_exposed,
            "edge_auth_mode": edge_auth_mode,
        }

    return {
        "generated_from": {
            "network_intent": str(network_intent_path),
            "stacks_dir": str(stacks_dir),
        },
        "stacks": stacks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a stack-architecture snapshot (zone + edge exposure per stack)."
    )
    parser.add_argument(
        "--stacks-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "stacks",
        help="Directory containing stack subdirectories with stack.yaml/edge.yaml files.",
    )
    parser.add_argument(
        "--network-intent",
        type=Path,
        required=True,
        help="Path to the environment network intent YAML file (e.g. network/pve.yaml).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the generated stack-architecture JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = build_stack_architecture(
        stacks_dir=args.stacks_dir.resolve(),
        network_intent_path=args.network_intent.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
