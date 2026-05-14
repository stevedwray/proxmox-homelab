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


ALLOWED_STATUSES = {"pending", "ready", "in_progress", "blocked", "complete", "skipped"}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def validate(path: Path) -> list[str]:
    doc = load_yaml(path)
    errors: list[str] = []

    for section in ("program", "current", "steps"):
        if section not in doc:
            errors.append(f"top-level: missing {section}")

    program = doc.get("program")
    if not isinstance(program, dict):
        errors.append("program: must be a mapping")
    else:
        for key in ("id", "plan_path", "state_version"):
            if key not in program:
                errors.append(f"program: missing {key}")

    current = doc.get("current")
    if not isinstance(current, dict):
        errors.append("current: must be a mapping")
    else:
        for key in ("stage", "step_id", "status", "last_report", "blocker_path"):
            if key not in current:
                errors.append(f"current: missing {key}")
        if current.get("status") not in ALLOWED_STATUSES:
            errors.append("current.status: invalid status")

    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps: must be a non-empty list")
    else:
        ids: set[str] = set()
        ready_count = 0
        current_matches = 0
        for idx, step in enumerate(steps):
            label = f"steps[{idx}]"
            if not isinstance(step, dict):
                errors.append(f"{label}: must be a mapping")
                continue
            for key in ("id", "stage", "title", "type", "status", "branch", "report_path", "depends_on"):
                if key not in step:
                    errors.append(f"{label}: missing {key}")
            step_id = step.get("id")
            if not non_empty_string(step_id):
                errors.append(f"{label}.id: must be a non-empty string")
            elif step_id in ids:
                errors.append(f"{label}.id: duplicate {step_id!r}")
            else:
                ids.add(step_id)
            if step.get("status") not in ALLOWED_STATUSES:
                errors.append(f"{label}.status: invalid status")
            if step.get("status") == "ready":
                ready_count += 1
            if isinstance(current, dict) and step.get("id") == current.get("step_id"):
                current_matches += 1
            depends_on = step.get("depends_on")
            if not isinstance(depends_on, list):
                errors.append(f"{label}.depends_on: must be a list")

        if ready_count > 1:
            errors.append("steps: only one step may be ready at a time")
        if current_matches != 1:
            errors.append("current.step_id: must match exactly one step entry")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate plan-state YAML")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    try:
        errors = validate(args.path)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    if errors:
        print("FAIL: invalid plan state")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS: valid plan state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
