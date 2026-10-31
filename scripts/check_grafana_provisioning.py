#!/usr/bin/env python3
"""Parse the Grafana provisioning files that deploy-monitoring-stack.yml writes inline, and check the routing.

`ansible-playbook --syntax-check` can't see inside a `content: |` string, so a mis-indented
datasource or contact point only fails when Grafana refuses to start. This extracts the two
inline files, replaces Jinja expressions with a placeholder, parses them as YAML, then walks
every alert rule in the stack's alerting/ directory through the notification policy to prove
each one lands somewhere, and that anything labelled to page reaches Telegram.

  scripts/check_grafana_provisioning.py [terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

DEFAULT_PLAYBOOK = "terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml"
RULES_DIR = "terraform/lxc/stacks/monitoring-stack/alerting"
TEMPLATES_FILE = "templates/homelab-templates.yml"
DATASOURCES_TASK = "Write Grafana datasource provisioning"
CONTACTS_TASK = "Write Grafana Discord contact points and notification policy"


def render(content: str) -> str:
    """Drop Jinja statements and replace expressions with a placeholder."""
    content = re.sub(r"^[ \t]*\{%.*?%\}[ \t]*\n", "", content, flags=re.M)
    return re.sub(r"\{\{.*?\}\}", "x", content)


def inline_content(playbook: list, task_name: str) -> str:
    for play in playbook:
        for task in play.get("tasks", []):
            if task.get("name") == task_name:
                return render(task["ansible.builtin.copy"]["content"])
    raise SystemExit(f"FAIL: task '{task_name}' not found")


def matches(route: dict, labels: dict[str, str]) -> bool:
    for key, op, value in route.get("object_matchers", []):
        if op != "=":
            raise SystemExit(f"FAIL: checker only understands '=' matchers, got {op!r}")
        if labels.get(key) != value:
            return False
    return True


def receivers_for(policy: dict, labels: dict[str, str]) -> list[str]:
    """First matching route wins unless it says continue; no match falls back to the default receiver."""
    hit: list[str] = []
    for route in policy.get("routes", []):
        if matches(route, labels):
            hit.append(route["receiver"])
            if not route.get("continue"):
                return hit
    return hit or [policy["receiver"]]


def check(playbook_path: str, rules_dir: str = RULES_DIR) -> list[str]:
    problems: list[str] = []
    playbook = yaml.safe_load(Path(playbook_path).read_text())

    try:
        sources = yaml.safe_load(inline_content(playbook, DATASOURCES_TASK))["datasources"]
    except yaml.YAMLError as exc:
        return [f"datasources.yml does not parse: {exc}"]
    if not all(isinstance(s, dict) and "name" in s and "type" in s for s in sources):
        problems.append("a datasource entry is malformed (missing name/type)")
    uids = {s.get("uid") for s in sources if s.get("uid")}
    if sum(1 for s in sources if s.get("uid") == "vm-alerting" and s.get("type") == "prometheus") != 1:
        problems.append("expected exactly one prometheus datasource with uid vm-alerting")

    try:
        contacts = yaml.safe_load(inline_content(playbook, CONTACTS_TASK))
    except yaml.YAMLError as exc:
        return [*problems, f"contact-points.yml does not parse: {exc}"]
    points = {c["name"]: c["receivers"] for c in contacts["contactPoints"]}
    policy = contacts["policies"][0]
    used = {policy["receiver"], *(r["receiver"] for r in policy.get("routes", []))}
    if used - set(points):
        problems.append(f"policy uses receivers that are not defined: {sorted(used - set(points))}")
    for name, receivers in points.items():
        for rec in receivers:
            settings = rec.get("settings", {})
            if rec["type"] == "telegram" and not {"bottoken", "chatid"} <= set(settings):
                problems.append(f"{name}/{rec['uid']}: telegram needs bottoken and chatid")
            if rec["type"] == "discord" and "url" not in settings:
                problems.append(f"{name}/{rec['uid']}: discord needs url")

    defined = set()
    template_path = Path(rules_dir) / TEMPLATES_FILE
    if not template_path.exists():
        problems.append(f"{template_path} is missing")
    else:
        try:
            body = yaml.safe_load(template_path.read_text())["templates"][0]["template"]
            defined = set(re.findall(r'\{\{-?\s*define "([^"]+)"', body))
        except (yaml.YAMLError, KeyError, IndexError, TypeError) as exc:
            problems.append(f"{template_path} is not a valid Grafana templates file: {exc}")
    for match in re.finditer(r'template \\?"([^"\\]+)\\?"', Path(playbook_path).read_text()):
        if match.group(1) not in defined:
            problems.append(f"contact points use template {match.group(1)!r}, which {TEMPLATES_FILE} does not define")

    for rec in points.get("homelab-tripwire", []):
        if rec.get("disableResolveMessage") is not True:
            problems.append(f"homelab-tripwire/{rec['uid']}: a honeypot hit is an event, so resolve messages must be disabled")

    def has_telegram(point: str) -> bool:
        return any(r["type"] == "telegram" for r in points[point])

    for path in sorted(Path(rules_dir).glob("*.yml")):
        for group in yaml.safe_load(path.read_text())["groups"]:
            for rule in group["rules"]:
                labels = {k: str(v) for k, v in rule["labels"].items()}
                for query in rule["data"]:
                    uid = query["datasourceUid"]
                    if uid != "__expr__" and uid not in uids:
                        problems.append(f"{rule['uid']}: datasource {uid!r} is not provisioned")
                paged = any(has_telegram(r) for r in receivers_for(policy, labels))
                if labels.get("page") == "true" and not paged:
                    problems.append(f"{rule['uid']}: labelled page=true but does not reach Telegram")
                if labels.get("page") != "true" and paged:
                    problems.append(f"{rule['uid']}: reaches Telegram without page=true")
                for synthetic in ("DatasourceError", "DatasourceNoData"):
                    # Grafana's own "this rule cannot query" alert inherits the rule's labels (page=true included).
                    if any(has_telegram(r) for r in receivers_for(policy, {**labels, "alertname": synthetic})):
                        problems.append(f"{rule['uid']}: a {synthetic} alert would page Telegram")
                if labels.get("event") == "true":
                    # An event ages out; it does not recover. A "Resolved" message for it is noise.
                    for name in receivers_for(policy, labels):
                        for rec in points[name]:
                            if rec.get("disableResolveMessage") is not True:
                                problems.append(f"{rule['uid']}: event=true must not send a resolve message, but {name}/{rec['uid']} does")
                if labels.get("findings") == "new":
                    # "New findings" ages out after its look-back; a "Resolved" message would read as "fixed".
                    for name in receivers_for(policy, labels):
                        for rec in points[name]:
                            if rec.get("disableResolveMessage") is not True:
                                problems.append(f"{rule['uid']}: findings=new must not send a resolve message, but {name}/{rec['uid']} does")
                if labels.get("category") == "hardware" and labels.get("severity") == "critical" and not paged:
                    problems.append(f"{rule['uid']}: a critical hardware fault must page Telegram")
                if labels.get("tripwire") == "honeypot" and receivers_for(policy, labels) != ["homelab-tripwire"]:
                    problems.append(f"{rule['uid']}: tripwire must route only to homelab-tripwire")
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
