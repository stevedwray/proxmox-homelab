#!/usr/bin/env python3
"""Validate documentation-only stack metadata for active platform stacks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml


ACTIVE_STACKS = (
    "harbor-stack",
    "apt-cacher-stack",
    "netbox-stack",
    "portainer-stack",
    "authentik-stack",
    "step-ca-stack",
    "ci-runner-01",
)
ACTIVE_STACK_SET = frozenset(ACTIVE_STACKS)

REQUIRED_PROVIDES_KEYS = ("service", "port", "protocol")
REQUIRED_CONTRACT_SECTIONS = ("## Provides", "## Dependencies")
SERVICE_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_PROTOCOLS = ("tcp", "udp")

# Required now per terraform/lxc/PLATFORM_CONTRACT.md's "Platform API —
# stack.yaml fields" table. All four are flat top-level keys — none of them
# belong under a nested block. The only legitimate nested network key is
# `network.zone` / `network.access_path`.
REQUIRED_TOP_LEVEL_FIELDS = ("hostname", "ip_address", "deployment_tier", "dns_server")
ALLOWED_DEPLOYMENT_TIERS = ("platform", "apps")
# Active stacks use either a literal CIDR or a ${lab_ip_*}-style template
# reference resolved by the selected LAB_IP_* overlay before Terraform reads
# it (e.g. authentik-stack: "${lab_ip_authentik}/24") — both are valid.
IP_ADDRESS_CIDR_PATTERN = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}$")
IP_ADDRESS_TEMPLATE_PATTERN = re.compile(r"^\$\{[^}]+\}/\d{1,2}$")
LAYER_METADATA = "metadata"
LAYER_CONTRACT_SECTIONS = "contract-sections"
LAYER_CONTRACT_DOCS = "contract-docs"
ISSUE_SEVERITY_ERROR = "error"


def make_issue(
    *,
    stack_name: str,
    code: str,
    message: str,
    field: str | None = None,
    value: object | None = None,
) -> dict[str, object]:
    issue = {
        "stack": stack_name,
        "severity": ISSUE_SEVERITY_ERROR,
        "code": code,
        "message": message,
    }
    if field is not None:
        issue["field"] = field
    if value is not None:
        issue["value"] = value
    return issue


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
    errors_by_layer: dict[str, list[dict[str, object]]] = {
        layer: [] for layer in enabled_layers
    }
    stack_results: dict[str, dict[str, object]] = {}

    for stack_name in ACTIVE_STACKS:
        stack_path = stacks_dir / stack_name / "stack.yaml"
        stack_result = validate_stack(
            stack_name=stack_name,
            stack_path=stack_path,
            known_stacks=known_stacks,
            check_contract_docs=args.check_contract_docs,
            check_contract_sections=args.check_contract_sections,
        )
        stack_results[stack_name] = stack_result
        for layer, layer_issues in stack_result["issues_by_layer"].items():
            errors_by_layer[layer].extend(layer_issues)

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
            for issue in layer_errors:
                print(f"  - {issue['message']}", file=sys.stderr)
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
    stack_results: dict[str, dict[str, object]],
    errors_by_layer: dict[str, list[dict[str, object]]],
    total_errors: int,
) -> dict:
    stack_payload: dict[str, dict[str, object]] = {}
    passed_stacks: list[str] = []
    failed_stacks: list[str] = []

    for stack_name, result in stack_results.items():
        layer_payload = {
            layer: {
                "status": "failed" if result["issues_by_layer"][layer] else "passed",
                "issues": [
                    issue["message"] for issue in result["issues_by_layer"][layer]
                ],
                "issue_details": result["issues_by_layer"][layer],
                "issue_count": len(issues),
            }
            for layer, issues in result["issues_by_layer"].items()
        }
        stack_status = (
            "failed"
            if any(layer["issue_count"] for layer in layer_payload.values())
            else "passed"
        )
        if stack_status == "passed":
            passed_stacks.append(stack_name)
        else:
            failed_stacks.append(stack_name)

        stack_payload[stack_name] = {
            "status": stack_status,
            "metadata": result["metadata"],
            "layers": layer_payload,
        }

    layers_payload = {
        layer: {
            "status": "failed" if errors_by_layer[layer] else "passed",
            "issue_count": len(errors_by_layer[layer]),
            "issues": [issue["message"] for issue in errors_by_layer[layer]],
            "issue_details": errors_by_layer[layer],
        }
        for layer in enabled_layers
    }

    return {
        "status": "failed" if total_errors else "passed",
        "enabled_layers": list(enabled_layers),
        "validation_scope": "active-pve-test-stacks-only",
        "active_stacks": list(ACTIVE_STACKS),
        "active_stack_summary": {
            "count": len(ACTIVE_STACKS),
            "passed": passed_stacks,
            "failed": failed_stacks,
        },
        "layers": layers_payload,
        "stacks": stack_payload,
        "total_issue_count": total_errors,
    }


def validate_required_top_level_fields(
    stack_name: str, data: dict
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []

    for field in REQUIRED_TOP_LEVEL_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                make_issue(
                    stack_name=stack_name,
                    code="missing_required_field",
                    field=field,
                    message=(
                        f"{stack_name}: missing required top-level field "
                        f"'{field}' (see terraform/lxc/PLATFORM_CONTRACT.md "
                        "'Required now' table — must be a flat top-level "
                        "key, not nested under a custom 'network:' block)"
                    ),
                )
            )

    ip_address = data.get("ip_address")
    if (
        isinstance(ip_address, str)
        and not IP_ADDRESS_CIDR_PATTERN.fullmatch(ip_address)
        and not IP_ADDRESS_TEMPLATE_PATTERN.fullmatch(ip_address)
    ):
        issues.append(
            make_issue(
                stack_name=stack_name,
                code="ip_address_not_cidr",
                field="ip_address",
                value=ip_address,
                message=(
                    f"{stack_name}: ip_address must be CIDR notation, e.g. "
                    "'192.168.1.60/24'"
                ),
            )
        )

    deployment_tier = data.get("deployment_tier")
    if (
        isinstance(deployment_tier, str)
        and deployment_tier not in ALLOWED_DEPLOYMENT_TIERS
    ):
        issues.append(
            make_issue(
                stack_name=stack_name,
                code="invalid_deployment_tier",
                field="deployment_tier",
                value=deployment_tier,
                message=(
                    f"{stack_name}: deployment_tier must be one of "
                    f"{', '.join(ALLOWED_DEPLOYMENT_TIERS)}"
                ),
            )
        )

    return issues


def validate_stack(
    stack_name: str,
    stack_path: Path,
    known_stacks: set[str],
    check_contract_docs: bool,
    check_contract_sections: bool,
) -> dict[str, object]:
    issues_by_layer: dict[str, list[dict[str, object]]] = {
        LAYER_METADATA: [],
    }
    if check_contract_sections:
        issues_by_layer[LAYER_CONTRACT_SECTIONS] = []
    if check_contract_docs:
        issues_by_layer[LAYER_CONTRACT_DOCS] = []

    metadata = {
        "stack_file": str(stack_path),
        "declared_dependencies": [],
        "declared_services": [],
    }

    if not stack_path.exists():
        issues_by_layer[LAYER_METADATA].append(
            make_issue(
                stack_name=stack_name,
                code="missing_stack_file",
                field="stack.yaml",
                value=str(stack_path),
                message=f"{stack_name}: missing stack file at {stack_path}",
            )
        )
        return {"metadata": metadata, "issues_by_layer": issues_by_layer}

    try:
        with stack_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        issues_by_layer[LAYER_METADATA].append(
            make_issue(
                stack_name=stack_name,
                code="invalid_yaml",
                field="stack.yaml",
                message=f"{stack_name}: failed to parse YAML: {exc}",
            )
        )
        return {"metadata": metadata, "issues_by_layer": issues_by_layer}

    if not isinstance(data, dict):
        issues_by_layer[LAYER_METADATA].append(
            make_issue(
                stack_name=stack_name,
                code="top_level_not_mapping",
                field="stack.yaml",
                message=f"{stack_name}: top-level YAML must be a mapping",
            )
        )
        return {"metadata": metadata, "issues_by_layer": issues_by_layer}

    issues_by_layer[LAYER_METADATA].extend(
        validate_required_top_level_fields(stack_name=stack_name, data=data)
    )

    depends_on = data.get("depends_on")
    if not isinstance(depends_on, list):
        issues_by_layer[LAYER_METADATA].append(
            make_issue(
                stack_name=stack_name,
                code="depends_on_not_list",
                field="depends_on",
                message=f"{stack_name}: depends_on must be present and must be a list",
            )
        )
    else:
        metadata["declared_dependencies"] = depends_on
        seen_dependencies: set[str] = set()
        for index, dependency in enumerate(depends_on):
            location = f"{stack_name}: depends_on[{index}]"
            if not isinstance(dependency, str) or not dependency.strip():
                issues_by_layer[LAYER_METADATA].append(
                    make_issue(
                        stack_name=stack_name,
                        code="dependency_not_non_empty_string",
                        field=f"depends_on[{index}]",
                        value=dependency,
                        message=f"{location} must be a non-empty stack name",
                    )
                )
                continue
            if dependency in seen_dependencies:
                issues_by_layer[LAYER_METADATA].append(
                    make_issue(
                        stack_name=stack_name,
                        code="duplicate_dependency",
                        field=f"depends_on[{index}]",
                        value=dependency,
                        message=(
                            f"{location} duplicates declared dependency "
                            f"'{dependency}'"
                        ),
                    )
                )
                continue
            seen_dependencies.add(dependency)
            if dependency == stack_name:
                issues_by_layer[LAYER_METADATA].append(
                    make_issue(
                        stack_name=stack_name,
                        code="self_dependency",
                        field=f"depends_on[{index}]",
                        value=dependency,
                        message=f"{location} must not reference itself",
                    )
                )
                continue
            if dependency not in known_stacks:
                issues_by_layer[LAYER_METADATA].append(
                    make_issue(
                        stack_name=stack_name,
                        code="unknown_dependency_stack",
                        field=f"depends_on[{index}]",
                        value=dependency,
                        message=(
                            f"{location} references unknown stack directory "
                            f"'{dependency}'"
                        ),
                    )
                )
                continue
            if dependency not in ACTIVE_STACK_SET:
                issues_by_layer[LAYER_METADATA].append(
                    make_issue(
                        stack_name=stack_name,
                        code="inactive_dependency_stack",
                        field=f"depends_on[{index}]",
                        value=dependency,
                        message=(
                            f"{location} references '{dependency}', which is a real "
                            "stack directory but is outside the active pve-test "
                            "validation set"
                        ),
                    )
                )

    provides = data.get("provides")
    if not isinstance(provides, list):
        issues_by_layer[LAYER_METADATA].append(
            make_issue(
                stack_name=stack_name,
                code="provides_not_list",
                field="provides",
                message=f"{stack_name}: provides must be present and must be a list",
            )
        )
    else:
        seen_service_names: set[str] = set()
        for index, service in enumerate(provides):
            location = f"{stack_name}: provides[{index}]"
            if not isinstance(service, dict):
                issues_by_layer[LAYER_METADATA].append(
                    make_issue(
                        stack_name=stack_name,
                        code="provided_service_not_mapping",
                        field=f"provides[{index}]",
                        value=service,
                        message=f"{location} must be a mapping",
                    )
                )
                continue

            for key in REQUIRED_PROVIDES_KEYS:
                if key not in service:
                    issues_by_layer[LAYER_METADATA].append(
                        make_issue(
                            stack_name=stack_name,
                            code="missing_provides_key",
                            field=f"provides[{index}].{key}",
                            message=(
                                f"{location} is missing required key '{key}'"
                            ),
                        )
                    )

            service_name = service.get("service")
            if isinstance(service_name, str):
                metadata["declared_services"].append(service_name)
            if "service" in service and (
                not isinstance(service_name, str) or not service_name.strip()
            ):
                issues_by_layer[LAYER_METADATA].append(
                    make_issue(
                        stack_name=stack_name,
                        code="service_name_not_non_empty_string",
                        field=f"provides[{index}].service",
                        value=service_name,
                        message=(
                            f"{location}.service must be a non-empty string"
                        ),
                    )
                )
            elif isinstance(service_name, str):
                if not SERVICE_NAME_PATTERN.fullmatch(service_name):
                    issues_by_layer[LAYER_METADATA].append(
                        make_issue(
                            stack_name=stack_name,
                            code="invalid_service_name_format",
                            field=f"provides[{index}].service",
                            value=service_name,
                            message=(
                                f"{location}.service must use lowercase kebab-case "
                                "(for example 'registry-http')"
                            ),
                        )
                    )
                if service_name in seen_service_names:
                    issues_by_layer[LAYER_METADATA].append(
                        make_issue(
                            stack_name=stack_name,
                            code="duplicate_service_name",
                            field=f"provides[{index}].service",
                            value=service_name,
                            message=(
                                f"{location}.service duplicates declared service "
                                f"'{service_name}'"
                            ),
                        )
                    )
                else:
                    seen_service_names.add(service_name)

            port = service.get("port")
            if "port" in service and not (
                isinstance(port, int) and not isinstance(port, bool)
            ):
                issues_by_layer[LAYER_METADATA].append(
                    make_issue(
                        stack_name=stack_name,
                        code="service_port_not_integer",
                        field=f"provides[{index}].port",
                        value=port,
                        message=f"{location}.port must be an integer",
                    )
                )
            elif isinstance(port, int) and not 1 <= port <= 65535:
                issues_by_layer[LAYER_METADATA].append(
                    make_issue(
                        stack_name=stack_name,
                        code="service_port_out_of_range",
                        field=f"provides[{index}].port",
                        value=port,
                        message=(
                            f"{location}.port must be between 1 and 65535"
                        ),
                    )
                )

            protocol = service.get("protocol")
            if "protocol" in service and (
                not isinstance(protocol, str) or not protocol.strip()
            ):
                issues_by_layer[LAYER_METADATA].append(
                    make_issue(
                        stack_name=stack_name,
                        code="service_protocol_not_non_empty_string",
                        field=f"provides[{index}].protocol",
                        value=protocol,
                        message=(
                            f"{location}.protocol must be a non-empty string"
                        ),
                    )
                )
            elif isinstance(protocol, str):
                if protocol != protocol.lower():
                    issues_by_layer[LAYER_METADATA].append(
                        make_issue(
                            stack_name=stack_name,
                            code="service_protocol_not_lowercase",
                            field=f"provides[{index}].protocol",
                            value=protocol,
                            message=(
                                f"{location}.protocol must be lowercase "
                                f"({', '.join(ALLOWED_PROTOCOLS)})"
                            ),
                        )
                    )
                elif protocol not in ALLOWED_PROTOCOLS:
                    issues_by_layer[LAYER_METADATA].append(
                        make_issue(
                            stack_name=stack_name,
                            code="unsupported_service_protocol",
                            field=f"provides[{index}].protocol",
                            value=protocol,
                            message=(
                                f"{location}.protocol must be one of "
                                f"{', '.join(ALLOWED_PROTOCOLS)}"
                            ),
                        )
                    )

    if check_contract_docs or check_contract_sections:
        contract_issues_by_layer = validate_contract_doc(
            stack_name=stack_name,
            stack_path=stack_path,
            data=data,
            check_mentions=check_contract_docs,
            check_sections=check_contract_sections,
        )
        for layer, layer_issues in contract_issues_by_layer.items():
            issues_by_layer[layer].extend(layer_issues)

    return {"metadata": metadata, "issues_by_layer": issues_by_layer}


def validate_contract_doc(
    stack_name: str,
    stack_path: Path,
    data: dict,
    check_mentions: bool,
    check_sections: bool,
) -> dict[str, list[dict[str, object]]]:
    issues_by_layer: dict[str, list[dict[str, object]]] = {}
    if check_sections:
        issues_by_layer[LAYER_CONTRACT_SECTIONS] = []
    if check_mentions:
        issues_by_layer[LAYER_CONTRACT_DOCS] = []

    contract_path = stack_path.with_name("STACK_CONTRACT.md")
    if not contract_path.exists():
        if check_sections:
            issues_by_layer[LAYER_CONTRACT_SECTIONS].append(
                make_issue(
                    stack_name=stack_name,
                    code="missing_contract_file",
                    field="STACK_CONTRACT.md",
                    value=str(contract_path),
                    message=(
                        f"{stack_name}: missing STACK_CONTRACT.md at {contract_path}"
                    ),
                )
            )
        if check_mentions:
            issues_by_layer[LAYER_CONTRACT_DOCS].append(
                make_issue(
                    stack_name=stack_name,
                    code="missing_contract_file",
                    field="STACK_CONTRACT.md",
                    value=str(contract_path),
                    message=(
                        f"{stack_name}: missing STACK_CONTRACT.md at {contract_path}"
                    ),
                )
            )
        return issues_by_layer

    contract_text = contract_path.read_text(encoding="utf-8")
    contract_lower = contract_text.lower()

    if check_sections:
        for section in REQUIRED_CONTRACT_SECTIONS:
            if section not in contract_text:
                issues_by_layer[LAYER_CONTRACT_SECTIONS].append(
                    make_issue(
                        stack_name=stack_name,
                        code="missing_contract_section",
                        field="STACK_CONTRACT.md",
                        value=section,
                        message=(
                            f"{stack_name}: STACK_CONTRACT.md is missing required "
                            f"section '{section}'"
                        ),
                    )
                )

    if check_mentions:
        for dependency in data.get("depends_on", []):
            if dependency not in contract_text:
                issues_by_layer[LAYER_CONTRACT_DOCS].append(
                    make_issue(
                        stack_name=stack_name,
                        code="dependency_not_mentioned_in_contract",
                        field="STACK_CONTRACT.md",
                        value=dependency,
                        message=(
                            f"{stack_name}: dependency '{dependency}' is declared in "
                            "stack.yaml but not mentioned in STACK_CONTRACT.md"
                        ),
                    )
                )

        for service in data.get("provides", []):
            service_name = service.get("service")
            if (
                isinstance(service_name, str)
                and service_name.lower() not in contract_lower
            ):
                issues_by_layer[LAYER_CONTRACT_DOCS].append(
                    make_issue(
                        stack_name=stack_name,
                        code="service_not_mentioned_in_contract",
                        field="STACK_CONTRACT.md",
                        value=service_name,
                        message=(
                            f"{stack_name}: provided service '{service_name}' is "
                            "declared in stack.yaml but not mentioned in "
                            "STACK_CONTRACT.md"
                        ),
                    )
                )

    return issues_by_layer


if __name__ == "__main__":
    raise SystemExit(main())
