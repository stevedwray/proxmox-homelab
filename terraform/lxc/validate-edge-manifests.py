#!/usr/bin/env python3
"""CLI for side-effect-free EdgeManifest validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from edge_manifest import discover_edge_manifests, validate_manifests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate EdgeManifest v1alpha1 files from stacks/*/edge.yaml "
            "without runtime side effects."
        )
    )
    parser.add_argument(
        "manifests",
        nargs="*",
        type=Path,
        help=(
            "Optional explicit manifest files to validate. "
            "If omitted, discover stacks/*/edge.yaml under --stacks-dir."
        ),
    )
    parser.add_argument(
        "--stacks-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "stacks",
        help="Stacks directory used for discovery mode.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    return parser.parse_args()


def _resolve_manifest_paths(args: argparse.Namespace) -> list[Path]:
    if args.manifests:
        return sorted(path.resolve() for path in args.manifests)
    return discover_edge_manifests(args.stacks_dir.resolve())


def main() -> int:
    args = parse_args()
    manifest_paths = _resolve_manifest_paths(args)
    result = validate_manifests(manifest_paths)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.ok else 1

    if result.ok:
        print(
            "Edge manifest validation passed. "
            f"Checked {len(result.manifests)} manifest(s)."
        )
        return 0

    print("Edge manifest validation failed.")
    print(f"Checked {len(result.manifests)} manifest(s).")
    print(f"Issue count: {len(result.issues)}")
    print("")
    for issue in result.issues:
        scope = issue.manifest or "<cross-manifest>"
        print(f"- [{issue.code}] {scope}: {issue.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
