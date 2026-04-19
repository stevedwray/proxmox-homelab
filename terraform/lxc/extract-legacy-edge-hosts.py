#!/usr/bin/env python3
"""CLI for read-only extraction of legacy central Traefik Host(...) routes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from edge_manifest import extract_legacy_routes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract legacy central Traefik Host(...) router rules from "
            "deploy-proxy-stack.yml without modifying any files."
        )
    )
    parser.add_argument(
        "--playbook",
        type=Path,
        default=Path(__file__).resolve().parent / "ansible" / "playbooks" / "deploy-proxy-stack.yml",
        help="Path to deploy-proxy-stack.yml (or equivalent legacy proxy playbook).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = extract_legacy_routes(args.playbook)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.ok else 1

    if result.routes:
        print(f"Extracted {len(result.routes)} legacy route(s):")
        for route in result.routes:
            print(f"- {route.router}: {route.host} ({route.source}:{route.line})")
    else:
        print("No legacy routes found.")

    if result.ok:
        return 0

    print("")
    print(f"Issue count: {len(result.issues)}")
    for issue in result.issues:
        location = issue.source or "<unknown>"
        if issue.line is not None:
            location = f"{location}:{issue.line}"
        router = f" [{issue.router}]" if issue.router else ""
        print(f"- [{issue.code}] {location}{router}: {issue.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
