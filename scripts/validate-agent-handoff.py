#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - tool bootstrap failure
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


EXECUTOR_TOP_LEVEL = [
    "session",
    "boundary",
    "approvals",
    "refs",
    "env",
    "gates",
    "output_report",
]
EXECUTOR_OPTIONAL = ["guardrails", "model_hint"]
ARCHITECT_TOP_LEVEL = ["session", "input", "refs", "review", "gates"]


def load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    docs = list(yaml.load_all(text, Loader=UniqueKeyLoader))
    if len(docs) != 1:
        raise ValueError(f"{path} must contain exactly one YAML document, found {len(docs)}")
    doc = docs[0]
    if not isinstance(doc, dict):
        raise ValueError(f"{path} must contain a top-level mapping")
    return doc


def expect_keys(section_name: str, data: dict[str, Any], required: list[str], optional: list[str] | None = None) -> list[str]:
    optional = optional or []
    allowed = set(required + optional)
    errors: list[str] = []
    missing = [key for key in required if key not in data]
    extra = [key for key in data if key not in allowed]
    if missing:
        errors.append(f"{section_name}: missing keys {missing}")
    if extra:
        errors.append(f"{section_name}: unexpected keys {extra}")
    return errors


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def validate_executor(doc: dict[str, Any]) -> list[str]:
    errors = expect_keys("top-level", doc, EXECUTOR_TOP_LEVEL, EXECUTOR_OPTIONAL)

    session = doc.get("session")
    if not isinstance(session, dict):
        errors.append("session: must be a mapping")
    else:
        errors.extend(expect_keys("session", session, ["id", "type", "goal", "branch", "issue"]))
        if not non_empty_string(session.get("id")):
            errors.append("session.id: must be a non-empty string")
        if session.get("type") not in {"bootstrap", "main_work", "closeout", "promote", "evidence"}:
            errors.append("session.type: must be one of bootstrap, main_work, closeout, promote, evidence")
        if not non_empty_string(session.get("goal")):
            errors.append("session.goal: must be a non-empty string")
        if not non_empty_string(session.get("branch")):
            errors.append("session.branch: must be a non-empty string")
        issue = session.get("issue")
        if issue == "":
            errors.append("session.issue: use null instead of empty string")

    boundary = doc.get("boundary")
    if not isinstance(boundary, dict):
        errors.append("boundary: must be a mapping")
    else:
        errors.extend(expect_keys("boundary", boundary, ["allowed", "not_allowed"]))
        for key in ("allowed", "not_allowed"):
            value = boundary.get(key)
            if not isinstance(value, list) or any(not non_empty_string(item) for item in value):
                errors.append(f"boundary.{key}: must be a list of non-empty strings")

    approvals = doc.get("approvals")
    if not isinstance(approvals, dict):
        errors.append("approvals: must be a mapping")
    else:
        errors.extend(expect_keys("approvals", approvals, ["destructive", "packet_path", "scope"]))

    refs = doc.get("refs")
    if not isinstance(refs, dict):
        errors.append("refs: must be a mapping")
    else:
        errors.extend(
            expect_keys(
                "refs",
                refs,
                ["base_branch", "baseline_sha", "runtime_validated_sha", "current_head_sha", "delta_type", "prior_report"],
            )
        )

    env = doc.get("env")
    if not isinstance(env, dict):
        errors.append("env: must be a mapping")
    else:
        errors.extend(expect_keys("env", env, ["disposable", "target_guard_cmd", "target_guard_expect", "scan_gate"]))
        if not non_empty_string(env.get("target_guard_cmd")):
            errors.append("env.target_guard_cmd: must be a non-empty string")
        if not non_empty_string(env.get("target_guard_expect")):
            errors.append("env.target_guard_expect: must be a non-empty string")

    if "model_hint" in doc and doc["model_hint"] not in {"lightweight", "heavy"}:
        errors.append("model_hint: must be lightweight or heavy")

    if "guardrails" in doc:
        guardrails = doc["guardrails"]
        if not isinstance(guardrails, list) or any(not non_empty_string(item) for item in guardrails):
            errors.append("guardrails: must be a list of non-empty strings")

    gates = doc.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append("gates: must be a non-empty list")
    else:
        seen_ids: set[str] = set()
        for idx, gate in enumerate(gates):
            label = f"gates[{idx}]"
            if not isinstance(gate, dict):
                errors.append(f"{label}: must be a mapping")
                continue
            errors.extend(expect_keys(label, gate, ["id", "cmd", "expect", "critical"]))
            gate_id = gate.get("id")
            if not non_empty_string(gate_id):
                errors.append(f"{label}.id: must be a non-empty string")
            elif gate_id in seen_ids:
                errors.append(f"{label}.id: duplicate gate id {gate_id!r}")
            else:
                seen_ids.add(gate_id)
            if not non_empty_string(gate.get("cmd")):
                errors.append(f"{label}.cmd: must be a non-empty string")
            else:
                cmd = gate["cmd"]
                if "|| true" in cmd:
                    errors.append(f"{label}.cmd: '|| true' is forbidden")
            if not non_empty_string(gate.get("expect")):
                errors.append(f"{label}.expect: must be a non-empty string")
            if not isinstance(gate.get("critical"), bool):
                errors.append(f"{label}.critical: must be boolean")

    output_report = doc.get("output_report")
    if not non_empty_string(output_report):
        errors.append("output_report: must be a non-empty string")

    return errors


def validate_architect(doc: dict[str, Any]) -> list[str]:
    errors = expect_keys("top-level", doc, ARCHITECT_TOP_LEVEL)

    session = doc.get("session")
    if not isinstance(session, dict):
        errors.append("session: must be a mapping")
    else:
        errors.extend(expect_keys("session", session, ["id", "branch", "issue"]))
        if not non_empty_string(session.get("id")):
            errors.append("session.id: must be a non-empty string")
        if not non_empty_string(session.get("branch")):
            errors.append("session.branch: must be a non-empty string")
        if session.get("issue") == "":
            errors.append("session.issue: use null instead of empty string")

    input_block = doc.get("input")
    if not isinstance(input_block, dict):
        errors.append("input: must be a mapping")
    else:
        errors.extend(expect_keys("input", input_block, ["report"], ["prior_architect_review"]))
        if not non_empty_string(input_block.get("report")):
            errors.append("input.report: must be a non-empty string")

    refs = doc.get("refs")
    if not isinstance(refs, dict):
        errors.append("refs: must be a mapping")
    else:
        errors.extend(
            expect_keys(
                "refs",
                refs,
                ["baseline_sha", "runtime_validated_sha", "current_head_sha", "delta_type"],
            )
        )

    review = doc.get("review")
    if not isinstance(review, dict):
        errors.append("review: must be a mapping")
    else:
        errors.extend(expect_keys("review", review, ["model_hint", "rationale"]))
        if review.get("model_hint") not in {"lightweight", "full"}:
            errors.append("review.model_hint: must be lightweight or full")
        if not non_empty_string(review.get("rationale")):
            errors.append("review.rationale: must be a non-empty string")

    gates = doc.get("gates")
    if not isinstance(gates, list) or not gates:
        errors.append("gates: must be a non-empty list")
    else:
        for idx, gate in enumerate(gates):
            label = f"gates[{idx}]"
            if not isinstance(gate, dict):
                errors.append(f"{label}: must be a mapping")
                continue
            errors.extend(expect_keys(label, gate, ["id", "status", "notes"]))
            if not non_empty_string(gate.get("id")):
                errors.append(f"{label}.id: must be a non-empty string")
            if gate.get("status") not in {"PASS", "FAIL", "SKIP"}:
                errors.append(f"{label}.status: must be PASS, FAIL, or SKIP")
            if not non_empty_string(gate.get("notes")):
                errors.append(f"{label}.notes: must be a non-empty string")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate architect/executor AI handoff YAML")
    parser.add_argument("kind", choices=["executor", "architect"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    try:
        doc = load_yaml(args.path)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    errors = validate_executor(doc) if args.kind == "executor" else validate_architect(doc)
    if errors:
        print(f"FAIL: invalid {args.kind} handoff")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"PASS: valid {args.kind} handoff")
    return 0


if __name__ == "__main__":
    sys.exit(main())
