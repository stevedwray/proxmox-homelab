#!/usr/bin/env python3
"""Validate docker-compose.yml conventions for active platform stacks.

Checks generic, repo-wide conventions confirmed against every active
stack's real compose file (see terraform/lxc/README.md): no unpinned
`:latest` image tags, and no custom top-level `networks:` block (every
active stack relies on Compose's default project network). This does not
attempt to validate image correctness, volume strategy, or anything
stack-specific — those stay in each stack's own plan/contract.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Keep in sync with ACTIVE_STACKS in validate-stack-metadata.py.
ACTIVE_STACKS = (
    "harbor-stack",
    "apt-cacher-stack",
    "netbox-stack",
    "portainer-stack",
    "authentik-stack",
    "step-ca-stack",
    "ci-runner-01",
    "minecraft-stack",
)


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    stacks_dir = script_dir / "stacks"

    stacks = [args.stack] if args.stack else list(ACTIVE_STACKS)
    all_issues: list[str] = []

    for stack_name in stacks:
        compose_path = stacks_dir / stack_name / "docker-compose.yml"
        # Not every active stack uses Docker Compose (harbor-stack and
        # portainer-stack have no committed compose file — different deploy
        # mechanisms). Only require the file to exist when a specific stack
        # was named on the command line; in bulk mode, silently skip stacks
        # that don't have one and just check conventions on the ones that do.
        if not compose_path.exists() and not args.stack:
            continue
        all_issues.extend(validate_compose(stack_name, compose_path))

    if all_issues:
        print("Compose validation failed.", file=sys.stderr)
        for issue in all_issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    print(f"Compose validation passed. Stacks checked: {', '.join(stacks)}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate docker-compose.yml conventions for active stacks."
    )
    parser.add_argument(
        "--stack",
        help="Validate only this stack instead of every active stack.",
    )
    return parser.parse_args()


def validate_compose(stack_name: str, compose_path: Path) -> list[str]:
    if not compose_path.exists():
        return [
            f"{stack_name}: missing docker-compose.yml at {compose_path} "
            "(it belongs in the stack's own directory, not a shared "
            "terraform/lxc/templates/ location — see "
            "terraform/lxc/ansible/playbooks/deploy-stack.yml's "
            "lookup('file', ...) for the actual convention)"
        ]

    try:
        with compose_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        return [f"{stack_name}: failed to parse docker-compose.yml: {exc}"]

    if not isinstance(data, dict):
        return [f"{stack_name}: docker-compose.yml top-level must be a mapping"]

    issues: list[str] = []

    if "networks" in data:
        issues.append(
            f"{stack_name}: docker-compose.yml declares a custom top-level "
            "'networks:' block — no active stack does this, they all rely "
            "on Compose's default project network"
        )

    services = data.get("services")
    if not isinstance(services, dict):
        issues.append(f"{stack_name}: docker-compose.yml has no 'services:' mapping")
        return issues

    for service_name, service in services.items():
        if not isinstance(service, dict):
            continue
        image = service.get("image")
        if not isinstance(image, str):
            issues.append(
                f"{stack_name}: service '{service_name}' has no 'image' key"
            )
            continue
        tag = image.rsplit(":", 1)[-1] if ":" in image.split("/")[-1] else None
        if tag is None:
            issues.append(
                f"{stack_name}: service '{service_name}' image '{image}' has "
                "no tag (implicit ':latest') — every active stack pins an "
                "explicit version"
            )
        elif tag == "latest":
            issues.append(
                f"{stack_name}: service '{service_name}' image '{image}' is "
                "pinned to ':latest' — every active stack pins an explicit "
                "version instead"
            )

    return issues


if __name__ == "__main__":
    raise SystemExit(main())
