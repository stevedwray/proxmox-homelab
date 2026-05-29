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


TRANSITIONS = {
    "pending": {"ready"},
    "ready": {"in_progress", "skipped"},
    "in_progress": {"complete", "blocked"},
    "blocked": {"ready"},
    "complete": set(),
    "skipped": set(),
}


def load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def save(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")


def validate_state(path: Path) -> list[str]:
    doc = load(path)
    errors: list[str] = []
    for section in ("program", "current", "steps"):
        if section not in doc:
            errors.append(f"top-level: missing {section}")

    program = doc.get("program")
    if not isinstance(program, dict):
        errors.append("program: must be a mapping")

    current = doc.get("current")
    if not isinstance(current, dict):
        errors.append("current: must be a mapping")
    elif current.get("status") not in TRANSITIONS:
        errors.append("current.status: invalid status")

    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps: must be a non-empty list")
    else:
        ready_count = 0
        current_matches = 0
        ids: set[str] = set()
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"steps[{idx}]: must be a mapping")
                continue
            step_id = step.get("id")
            if not isinstance(step_id, str) or not step_id.strip():
                errors.append(f"steps[{idx}].id: invalid")
            elif step_id in ids:
                errors.append(f"steps[{idx}].id: duplicate {step_id!r}")
            else:
                ids.add(step_id)
            status = step.get("status")
            if status not in TRANSITIONS:
                errors.append(f"steps[{idx}].status: invalid")
            if status == "ready":
                ready_count += 1
            if isinstance(current, dict) and step_id == current.get("step_id"):
                current_matches += 1
        if ready_count > 1:
            errors.append("steps: only one step may be ready at a time")
        if current_matches != 1:
            errors.append("current.step_id: must match exactly one step")

    return errors


def next_ready_step(steps: list[dict[str, Any]], completed_id: str) -> str | None:
    completed = {step["id"] for step in steps if step.get("status") == "complete"} | {completed_id}
    for step in steps:
        if step.get("status") != "pending":
            continue
        deps = step.get("depends_on", [])
        if all(dep in completed for dep in deps):
            return step["id"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Update plan-state step status")
    parser.add_argument("path", type=Path)
    parser.add_argument("step_id")
    parser.add_argument("new_status", choices=["ready", "in_progress", "complete", "blocked", "skipped"])
    parser.add_argument("--report", dest="report_path")
    parser.add_argument("--blocker", dest="blocker_path")
    args = parser.parse_args()

    try:
        data = load(args.path)
        steps = data["steps"]
        step = next(item for item in steps if item["id"] == args.step_id)
    except StopIteration:
        print(f"FAIL: unknown step id {args.step_id}")
        return 1
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    old_status = step["status"]
    if args.new_status not in TRANSITIONS.get(old_status, set()):
        print(f"FAIL: illegal transition {old_status} -> {args.new_status}")
        return 1

    step["status"] = args.new_status
    data["current"]["step_id"] = args.step_id
    data["current"]["stage"] = step["stage"]
    data["current"]["status"] = args.new_status
    data["current"]["last_report"] = args.report_path if args.report_path is not None else data["current"].get("last_report")
    data["current"]["blocker_path"] = args.blocker_path if args.blocker_path is not None else None

    if args.new_status == "complete":
        next_id = next_ready_step(steps, args.step_id)
        if next_id:
            next_step = next(item for item in steps if item["id"] == next_id)
            next_step["status"] = "ready"
            data["current"]["step_id"] = next_id
            data["current"]["stage"] = next_step["stage"]
            data["current"]["status"] = "ready"
            data["current"]["blocker_path"] = None

    save(args.path, data)
    errors = validate_state(args.path)
    if errors:
        print("FAIL: updated state is invalid")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"PASS: updated {args.step_id} to {args.new_status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
