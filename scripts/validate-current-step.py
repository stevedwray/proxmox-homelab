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


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def construct_mapping(loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key ({key!r})",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(  # type: ignore[arg-type]
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_mapping,
)


def load_yaml(path: Path) -> dict[str, Any]:
    docs = list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader))
    if len(docs) != 1:
        raise ValueError(f"{path} must contain exactly one YAML document, found {len(docs)}")
    doc = docs[0]
    if not isinstance(doc, dict):
        raise ValueError(f"{path} must contain a top-level mapping")
    return doc


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def expect_keys(name: str, data: dict[str, Any], required: list[str], optional: list[str] | None = None) -> list[str]:
    optional = optional or []
    allowed = set(required + optional)
    errors: list[str] = []
    missing = [key for key in required if key not in data]
    extra = [key for key in data if key not in allowed]
    if missing:
        errors.append(f"{name}: missing keys {missing}")
    if extra:
        errors.append(f"{name}: unexpected keys {extra}")
    return errors


def validate(doc: dict[str, Any]) -> list[str]:
    errors = expect_keys("top-level", doc, ["step", "goal", "scope", "refs", "env", "gates", "report", "plan_state"], ["model_hint"])

    step = doc.get("step")
    if not isinstance(step, dict):
        errors.append("step: must be a mapping")
    else:
        errors.extend(expect_keys("step", step, ["id", "stage", "type", "title", "branch"]))
        if step.get("type") not in {"bootstrap", "main_work", "closeout", "promote", "validate"}:
            errors.append("step.type: must be bootstrap, main_work, closeout, promote, or validate")
        for key in ("id", "stage", "title", "branch"):
            if not non_empty_string(step.get(key)):
                errors.append(f"step.{key}: must be a non-empty string")

    goal = doc.get("goal")
    if not isinstance(goal, dict):
        errors.append("goal: must be a mapping")
    else:
        errors.extend(expect_keys("goal", goal, ["summary"]))
        if not non_empty_string(goal.get("summary")):
            errors.append("goal.summary: must be a non-empty string")

    scope = doc.get("scope")
    if not isinstance(scope, dict):
        errors.append("scope: must be a mapping")
    else:
        errors.extend(expect_keys("scope", scope, ["allowed_paths", "forbidden_actions"]))
        for key in ("allowed_paths", "forbidden_actions"):
            value = scope.get(key)
            if not isinstance(value, list) or any(not non_empty_string(item) for item in value):
                errors.append(f"scope.{key}: must be a list of non-empty strings")

    refs = doc.get("refs")
    if not isinstance(refs, dict):
        errors.append("refs: must be a mapping")
    else:
        errors.extend(expect_keys("refs", refs, ["base_branch", "baseline_sha", "starting_sha"]))

    env = doc.get("env")
    if not isinstance(env, dict):
        errors.append("env: must be a mapping")
    else:
        errors.extend(expect_keys("env", env, ["target_guard_cmd", "target_guard_expect", "approvals_required", "disposable", "scan_gate"]))
        for key in ("target_guard_cmd", "target_guard_expect"):
            if not non_empty_string(env.get(key)):
                errors.append(f"env.{key}: must be a non-empty string")

    gates = doc.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append("gates: must be a non-empty list")
    else:
        seen_ids: set[str] = set()
        for idx, gate in enumerate(gates):
            name = f"gates[{idx}]"
            if not isinstance(gate, dict):
                errors.append(f"{name}: must be a mapping")
                continue
            errors.extend(expect_keys(name, gate, ["id", "cmd", "expect", "critical"]))
            gate_id = gate.get("id")
            if not non_empty_string(gate_id):
                errors.append(f"{name}.id: must be a non-empty string")
            elif gate_id in seen_ids:
                errors.append(f"{name}.id: duplicate gate id {gate_id!r}")
            else:
                seen_ids.add(gate_id)
            if not non_empty_string(gate.get("cmd")):
                errors.append(f"{name}.cmd: must be a non-empty string")
            else:
                cmd = gate["cmd"]
                if "|| true" in cmd:
                    errors.append(f"{name}.cmd: '|| true' is forbidden")
            if not non_empty_string(gate.get("expect")):
                errors.append(f"{name}.expect: must be a non-empty string")
            if not isinstance(gate.get("critical"), bool):
                errors.append(f"{name}.critical: must be boolean")

    report = doc.get("report")
    if not isinstance(report, dict):
        errors.append("report: must be a mapping")
    else:
        errors.extend(expect_keys("report", report, ["path"]))
        if not non_empty_string(report.get("path")):
            errors.append("report.path: must be a non-empty string")

    plan_state = doc.get("plan_state")
    if not isinstance(plan_state, dict):
        errors.append("plan_state: must be a mapping")
    else:
        errors.extend(expect_keys("plan_state", plan_state, ["path"]))
        if not non_empty_string(plan_state.get("path")):
            errors.append("plan_state.path: must be a non-empty string")

    if "model_hint" in doc and doc["model_hint"] not in {"lightweight", "heavy"}:
        errors.append("model_hint: must be lightweight or heavy")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate current-step YAML")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    try:
        doc = load_yaml(args.path)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    errors = validate(doc)
    if errors:
        print("FAIL: invalid current-step packet")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS: valid current-step packet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
