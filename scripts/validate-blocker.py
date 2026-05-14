#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(f"PyYAML is required: {exc}")


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate blocker contract")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    try:
        data = yaml.safe_load(args.path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append("top-level: must be a mapping")
    else:
        for key in ("step_id", "status", "blocker_type", "summary", "details", "report_path", "requires"):
            if key not in data:
                errors.append(f"missing key {key}")
        if data.get("status") != "blocked":
            errors.append("status: must be blocked")
        if data.get("blocker_type") not in {"technical", "approval", "ambiguity", "contradiction"}:
            errors.append("blocker_type: invalid value")
        for key in ("step_id", "summary", "details", "report_path"):
            if not non_empty_string(data.get(key)):
                errors.append(f"{key}: must be a non-empty string")
        requires = data.get("requires")
        if not isinstance(requires, list) or any(not non_empty_string(item) for item in requires):
            errors.append("requires: must be a list of non-empty strings")

    if errors:
        print("FAIL: invalid blocker contract")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS: valid blocker contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
