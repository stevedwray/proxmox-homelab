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


ORDER = ["step", "goal", "scope", "refs", "env", "gates", "report", "plan_state", "model_hint"]


def read_spec(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def ordered_step(spec: dict[str, Any]) -> dict[str, Any]:
    return {key: spec[key] for key in ORDER if key in spec}


def main() -> int:
    parser = argparse.ArgumentParser(description="Render canonical current-step YAML from spec")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    try:
        spec = read_spec(args.input)
        rendered = ordered_step(spec)
        text = yaml.safe_dump(rendered, sort_keys=False, allow_unicode=False)
        args.output.write_text(text, encoding="utf-8")
    except KeyError as exc:
        print(f"FAIL: missing required spec key {exc}")
        return 1
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    print(f"PASS: wrote current step to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
