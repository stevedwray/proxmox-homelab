#!/usr/bin/env python3
"""Parse the Grafana provisioning files that deploy-monitoring-stack.yml writes inline.

`ansible-playbook --syntax-check` can't see inside a `content: |` string, so a
mis-indented datasource or contact point only fails when Grafana refuses to
start. This extracts the two inline files, replaces Jinja expressions with a
placeholder, parses them as YAML and checks the alerting wiring.

  scripts/check_grafana_provisioning.py [terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

DEFAULT_PLAYBOOK = "terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml"
DATASOURCES_TASK = "Write Grafana datasource provisioning"
CONTACTS_TASK = "Write Grafana Discord contact points and notification policy"


def render(content: str) -> str:
    """Drop Jinja statements and replace expressions with a placeholder."""
    content = re.sub(r"^[ \t]*\{%.*?%\}[ \t]*\n", "", content, flags=re.M)
    return re.sub(r"\{\{.*?\}\}", "x", content)


def inline_content(playbook: dict, task_name: str) -> str:
    for play in playbook:
        for task in play.get("tasks", []):
            if task.get("name") == task_name:
                return render(task["ansible.builtin.copy"]["content"])
    raise SystemExit(f"FAIL: task '{task_name}' not found")


def check(playbook_path: str) -> list[str]:
    problems: list[str] = []
    playbook = yaml.safe_load(Path(playbook_path).read_text())

    try:
        sources = yaml.safe_load(inline_content(playbook, DATASOURCES_TASK))["datasources"]
    except yaml.YAMLError as exc:
        return [f"datasources.yml does not parse: {exc}"]
    if not all(isinstance(s, dict) and "name" in s and "type" in s for s in sources):
        problems.append("a datasource entry is malformed (missing name/type)")
    alerting = [s for s in sources if s.get("uid") == "vm-alerting"]
    if len(alerting) != 1 or alerting[0].get("type") != "prometheus":
        problems.append("expected exactly one prometheus datasource with uid vm-alerting")

    try:
        contacts = yaml.safe_load(inline_content(playbook, CONTACTS_TASK))
    except yaml.YAMLError as exc:
        return [*problems, f"contact-points.yml does not parse: {exc}"]
    names = {c["name"] for c in contacts["contactPoints"]}
    policy = contacts["policies"][0]
    used = {policy["receiver"], *(r["receiver"] for r in policy.get("routes", []))}
    if used - names:
        problems.append(f"policy uses receivers that are not defined: {sorted(used - names)}")
    if len(names) != 3:
        problems.append(f"expected 3 contact points, found {len(names)}")
    return problems


def main(argv: list[str]) -> int:
    problems = check(argv[0] if argv else DEFAULT_PLAYBOOK)
    for problem in problems:
        print(f"FAIL: {problem}")
    if not problems:
        print("ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
