#!/usr/bin/env python3
"""Check plan safety by classifying storage transitions and gating on unsafe classes.

This script uses the classify-storage-plan logic and returns non-zero if any
classified transition maps to a disallowed mutation class (blocked, replacement-sensitive).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import importlib.util


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("classify", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", required=True, help="Path to plan JSON")
    args = parser.parse_args()

    plan_path = Path(args.plan_json)
    classifier = load_module(Path(__file__).parent / "classify-storage-plan.py")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    resource_changes = plan.get("resource_changes") or []
    issues = []

    for change in resource_changes:
        addr = change.get("address") or ""
        if "container" in addr or "mount" in addr or "docker" in addr or "extra_mount" in addr:
            results = classifier.classify_change(change)
            for r in results:
                cls = r.get("class", "blocked")
                if cls.startswith("blocked") or cls == "replacement-sensitive" or cls == "provider_replacement":
                    issues.append({"address": addr, "field_transition": r.get("field_transition"), "class": cls})

    if issues:
        print("Plan safety check failed: unsafe storage transitions detected:")
        print(json.dumps(issues, indent=2, sort_keys=True))
        return 2

    print("Plan safety check passed: no disallowed storage transitions detected (offline classification).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
