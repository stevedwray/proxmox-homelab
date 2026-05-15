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


def read_spec(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def ordered_executor(spec: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "session": spec["session"],
        "boundary": spec["boundary"],
        "approvals": spec["approvals"],
        "refs": spec["refs"],
        "env": spec["env"],
        "gates": spec["gates"],
        "output_report": spec["output_report"],
    }
    if "guardrails" in spec:
        result["guardrails"] = spec["guardrails"]
    if "model_hint" in spec:
        result["model_hint"] = spec["model_hint"]
    return result


def ordered_architect(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "session": spec["session"],
        "input": spec["input"],
        "refs": spec["refs"],
        "review": spec["review"],
        "gates": spec["gates"],
    }


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=False)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render canonical architect/executor handoff YAML from spec")
    parser.add_argument("kind", choices=["executor", "architect"])
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    try:
        spec = read_spec(args.input)
        data = ordered_executor(spec) if args.kind == "executor" else ordered_architect(spec)
        write_yaml(args.output, data)
    except KeyError as exc:
        print(f"FAIL: missing required spec key {exc}")
        return 1
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    print(f"PASS: wrote {args.kind} handoff to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
