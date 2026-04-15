#!/usr/bin/env python3
"""Validate documentation-only stack metadata for active platform stacks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


ACTIVE_STACKS = (
    "harbor-stack",
    "apt-cacher-stack",
    "netbox-stack-test",
    "portainer-stack",
    "authentik-stack",
    "step-ca-stack",
    "ci-runner-01",
)

REQUIRED_PROVIDES_KEYS = ("service", "port", "protocol")
REQUIRED_CONTRACT_SECTIONS = ("## Provides", "## Dependencies")
LAYER_METADATA = "metadata"
LAYER_CONTRACT_SECTIONS = "contract-sections"
LAYER_CONTRACT_DOCS = "contract-docs"


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    stacks_dir = script_dir / "stacks"
    known_stacks = {
        path.parent.name
        for path in stacks_dir.glob("*/stack.yaml")
        if ".hold" not in path.parts
    }

    enabled_layers = get_enabled_layers(args)
    errors_by_layer: dict[str, list[str]] = {
        layer: [] for layer in enabled_layers
    }
    stack_results: dict[str, dict[str, list[str]]] = {}

    for stack_name in ACTIVE_STACKS:
        stack_path = stacks_dir / stack_name / "stack.yaml"
        stack_errors = validate_stack(
            stack_name=stack_name,
            stack_path=stack_path,
            known_stacks=known_stacks,
            check_contract_docs=args.check_contract_docs,
            check_contract_sections=args.check_contract_sections,
        )
        stack_results[stack_name] = stack_errors
        for layer, layer_errors in stack_errors.items():
            errors_by_layer[layer].extend(layer_errors)

    total_errors = sum(len(errors) for errors in errors_by_layer.values())
    payload = build_json_payload(
        enabled_layers=enabled_layers,
        stack_results=stack_results,
        errors_by_layer=errors_by_layer,
        total_errors=total_errors,
    )

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1 if total_errors else 0

    if total_errors:
        print("Stack validation failed.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Validation layers:", file=sys.stderr)
        for layer in enabled_layers:
            layer_errors = errors_by_layer[layer]
            status = "failed" if layer_errors else "passed"
            print(
                f"  - {layer}: {status} ({len(layer_errors)} issue(s))",
                file=sys.stderr,
            )
        print("", file=sys.stderr)
        for layer in enabled_layers:
            layer_errors = errors_by_layer[layer]
            if not layer_errors:
                continue
            print(f"[{layer}]", file=sys.stderr)
            for error in layer_errors:
                print(f"  - {error}", file=sys.stderr)
            print("", file=sys.stderr)
        return 1

    print(
        "Stack validation passed. "
        f"Layers checked: {', '.join(enabled_layers)}. "
        f"Stacks: {', '.join(ACTIVE_STACKS)}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate documentation-only stack metadata for active platform stacks."
        )
    )
    parser.add_argument(
        "--check-contract-docs",
        action="store_true",
        help=(
            "Also verify active stacks have STACK_CONTRACT.md and that each "
            "declared dependency and provided service is mentioned in the contract text."
        ),
    )
    parser.add_argument(
        "--check-contract-sections",
        action="store_true",
        help=(
            "Also verify active stacks have STACK_CONTRACT.md with the required "
            "top-level boundary sections used by the current contracts."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit machine-readable JSON output with validation layers, per-stack "
            "results, and aggregate issue counts."
        ),
    )
    return parser.parse_args()


def get_enabled_layers(args: argparse.Namespace) -> tuple[str, ...]:
    layers = [LAYER_METADATA]
    if args.check_contract_sections:
        layers.append(LAYER_CONTRACT_SECTIONS)
    if args.check_contract_docs:
        layers.append(LAYER_CONTRACT_DOCS)
    return tuple(layers)


def build_json_payload(
    enabled_layers: tuple[str, ...],
    stack_results: dict[str, dict[str, list[str]]],
    errors_by_layer: dict[str, list[str]],
    total_errors: int,
) -> dict:
    stack_payload: dict[str, dict] = {}
    for stack_name, result in stack_results.items():
        layer_payload = {
            layer: {
                "status": "failed" if issues else "passed",
                "issues": issues,
                "issue_count": len(issues),
            }
            for layer, issues in result.items()
        }
        stack_payload[stack_name] = {
            "status": (
                "failed"
                if any(layer["issue_count"] for layer in layer_payload.values())
                else "passed"
            ),
            "layers": layer_payload,
        }

    layers_payload = {
        layer: {
            "status": "failed" if errors_by_layer[layer] else "passed",
            "issue_count": len(errors_by_layer[layer]),
            "issues": errors_by_layer[layer],
        }
        for layer in enabled_layers
    }

    return {
        "status": "failed" if total_errors else "passed",
        "enabled_layers": list(enabled_layers),
        "active_stacks": list(ACTIVE_STACKS),
        "layers": layers_payload,
        "stacks": stack_payload,
        "total_issue_count": total_errors,
    }


def validate_stack(
    stack_name: str,
    stack_path: Path,
    known_stacks: set[str],
    check_contract_docs: bool,
    check_contract_sections: bool,
) -> dict[str, list[str]]:
    errors_by_layer: dict[str, list[str]] = {
        LAYER_METADATA: [],
    }
    if check_contract_sections:
        errors_by_layer[LAYER_CONTRACT_SECTIONS] = []
    if check_contract_docs:
        errors_by_layer[LAYER_CONTRACT_DOCS] = []

    if not stack_path.exists():
        errors_by_layer[LAYER_METADATA].append(
            f"{stack_name}: missing stack file at {stack_path}"
        )
        return errors_by_layer

    try:
        with stack_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        errors_by_layer[LAYER_METADATA].append(
            f"{stack_name}: failed to parse YAML: {exc}"
        )
        return errors_by_layer

    if not isinstance(data, dict):
        errors_by_layer[LAYER_METADATA].append(
            f"{stack_name}: top-level YAML must be a mapping"
        )
        return errors_by_layer

    depends_on = data.get("depends_on")
    if not isinstance(depends_on, list):
        errors_by_layer[LAYER_METADATA].append(
            f"{stack_name}: depends_on must be present and must be a list"
        )
    else:
        for index, dependency in enumerate(depends_on):
            location = f"{stack_name}: depends_on[{index}]"
            if not isinstance(dependency, str) or not dependency.strip():
                errors_by_layer[LAYER_METADATA].append(
                    f"{location} must be a non-empty stack name"
                )
                continue
            if dependency == stack_name:
                errors_by_layer[LAYER_METADATA].append(
                    f"{location} must not reference itself"
                )
                continue
            if dependency not in known_stacks:
                errors_by_layer[LAYER_METADATA].append(
                    f"{location} references unknown stack directory "
                    f"'{dependency}'"
                )

    provides = data.get("provides")
    if not isinstance(provides, list):
        errors_by_layer[LAYER_METADATA].append(
            f"{stack_name}: provides must be present and must be a list"
        )
    else:
        for index, service in enumerate(provides):
            location = f"{stack_name}: provides[{index}]"
            if not isinstance(service, dict):
                errors_by_layer[LAYER_METADATA].append(
                    f"{location} must be a mapping"
                )
                continue

            for key in REQUIRED_PROVIDES_KEYS:
                if key not in service:
                    errors_by_layer[LAYER_METADATA].append(
                        f"{location} is missing required key '{key}'"
                    )

            service_name = service.get("service")
            if "service" in service and (
                not isinstance(service_name, str) or not service_name.strip()
            ):
                errors_by_layer[LAYER_METADATA].append(
                    f"{location}.service must be a non-empty string"
                )

            port = service.get("port")
            if "port" in service and not isinstance(port, int):
                errors_by_layer[LAYER_METADATA].append(
                    f"{location}.port must be an integer"
                )

            protocol = service.get("protocol")
            if "protocol" in service and (
                not isinstance(protocol, str) or not protocol.strip()
            ):
                errors_by_layer[LAYER_METADATA].append(
                    f"{location}.protocol must be a non-empty string"
                )

    if check_contract_docs or check_contract_sections:
        contract_errors_by_layer = validate_contract_doc(
            stack_name=stack_name,
            stack_path=stack_path,
            data=data,
            check_mentions=check_contract_docs,
            check_sections=check_contract_sections,
        )
        for layer, layer_errors in contract_errors_by_layer.items():
            errors_by_layer[layer].extend(layer_errors)

    return errors_by_layer


def validate_contract_doc(
    stack_name: str,
    stack_path: Path,
    data: dict,
    check_mentions: bool,
    check_sections: bool,
) -> dict[str, list[str]]:
    errors_by_layer: dict[str, list[str]] = {}
    if check_sections:
        errors_by_layer[LAYER_CONTRACT_SECTIONS] = []
    if check_mentions:
        errors_by_layer[LAYER_CONTRACT_DOCS] = []

    contract_path = stack_path.with_name("STACK_CONTRACT.md")
    if not contract_path.exists():
        if check_sections:
            errors_by_layer[LAYER_CONTRACT_SECTIONS].append(
                f"{stack_name}: missing STACK_CONTRACT.md at {contract_path}"
            )
        if check_mentions:
            errors_by_layer[LAYER_CONTRACT_DOCS].append(
                f"{stack_name}: missing STACK_CONTRACT.md at {contract_path}"
            )
        return errors_by_layer

    contract_text = contract_path.read_text(encoding="utf-8")
    contract_lower = contract_text.lower()

    if check_sections:
        for section in REQUIRED_CONTRACT_SECTIONS:
            if section not in contract_text:
                errors_by_layer[LAYER_CONTRACT_SECTIONS].append(
                    f"{stack_name}: STACK_CONTRACT.md is missing required section "
                    f"'{section}'"
                )

    if check_mentions:
        for dependency in data.get("depends_on", []):
            if dependency not in contract_text:
                errors_by_layer[LAYER_CONTRACT_DOCS].append(
                    f"{stack_name}: dependency '{dependency}' is declared in stack.yaml "
                    f"but not mentioned in STACK_CONTRACT.md"
                )

        for service in data.get("provides", []):
            service_name = service.get("service")
            if (
                isinstance(service_name, str)
                and service_name.lower() not in contract_lower
            ):
                errors_by_layer[LAYER_CONTRACT_DOCS].append(
                    f"{stack_name}: provided service '{service_name}' is declared in stack.yaml "
                    f"but not mentioned in STACK_CONTRACT.md"
                )

    return errors_by_layer


if __name__ == "__main__":
    raise SystemExit(main())
