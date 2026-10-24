#!/usr/bin/env python3
"""Create or update the lab's Graylog log alerts: Discord notifications and event definitions.

  TASK_APPROVAL=<task> ./with-secrets-prod python3 scripts/graylog_alerts.py             # show what exists (read-only)
  TASK_APPROVAL=<task> ./with-secrets-prod python3 scripts/graylog_alerts.py --validate  # ask Graylog to check each definition (saves nothing)
  TASK_APPROVAL=<task> ./with-secrets-prod python3 scripts/graylog_alerts.py --apply     # create or update, matching by title
  TASK_APPROVAL=<task> ./with-secrets-prod python3 scripts/graylog_alerts.py --test      # send Graylog's own test message to each Discord channel

The rules live in terraform/lxc/stacks/graylog-stack/alerting/log-alerts.yml. Re-running is safe: objects are
matched by title and updated in place. Graylog keeps them in its database, so a graylog-stack rebuild loses them:
run --apply again afterwards (docs/alerting/plan.md, Phase 2).

Needs GRAYLOG_ROOT_PASSWORD, LAB_IP_GRAYLOG (or GRAYLOG_API) and the two Discord webhook URLs
(DISCORD_WEBHOOK_CRITICAL / DISCORD_WEBHOOK_WARNING, OpenBao services/grafana). Never prints a webhook URL.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import yaml

DATA = Path(__file__).resolve().parent.parent / "terraform/lxc/stacks/graylog-stack/alerting/log-alerts.yml"
EVENTS_STREAM = "000000000000000000000002"  # "All events"
PLACEHOLDER_ID = "000000000000000000000000"  # stands in for a notification that does not exist yet (validate only)
WEBHOOK_PREFIX = "https://discord.com/api/webhooks/"

# ${...} is Graylog's own template syntax. The backlog lines are the matching log messages.
CUSTOM_MESSAGE = "${event_definition_title}\n${event.message}\n${foreach backlog message}> ${message.message}\n${end}"

Call = Callable[..., tuple[int, Any]]


def load_data(path: Path = DATA) -> dict:
    data = yaml.safe_load(path.read_text())
    for spec in data["definitions"]:
        if spec["notification"] not in data["notifications"]:
            raise SystemExit(f"{spec['title']!r} uses unknown notification {spec['notification']!r}")
    return data


def notification_body(spec: dict, env: dict[str, str]) -> dict:
    """Graylog's Slack notification, pointed at a Discord webhook's /slack endpoint."""
    url = env.get(spec["webhook_env"], "").strip()
    if not url.startswith(WEBHOOK_PREFIX):
        raise SystemExit(f"{spec['webhook_env']} is missing or is not a Discord webhook URL")
    return {
        "title": spec["title"],
        "description": spec["description"],
        "config": {
            "type": "slack-notification-v1",
            "color": spec["color"],
            "webhook_url": url.rstrip("/") + "/slack",
            "channel": "#alerts",  # ignored by Discord, required by Graylog
            "user_name": "Graylog",
            "custom_message": CUSTOM_MESSAGE,
            "notify_channel": False,
            "notify_here": False,
            "link_names": False,
            "icon_url": "",
            "icon_emoji": "",
            "time_zone": "Pacific/Auckland",
            "include_title": True,
        },
    }


def definition_body(spec: dict, notification_id: str) -> dict:
    minutes_ms = int(spec["every_minutes"]) * 60_000
    field = spec["group_by"]
    return {
        "title": spec["title"],
        "description": " ".join(spec["description"].split()),
        "priority": int(spec["priority"]),
        "alert": True,
        "config": {
            "type": "aggregation-v1",
            "query": " ".join(spec["query"].split()),
            "query_parameters": [],
            "streams": [],
            "group_by": [field],
            "series": [{"id": "count()", "type": "count", "field": None}],
            "conditions": {
                "expression": {
                    "expr": ">",
                    "left": {"expr": "number-ref", "ref": "count()"},
                    "right": {"expr": "number", "value": 0},
                }
            },
            "search_within_ms": minutes_ms,
            "execute_every_ms": minutes_ms,
            "use_cron_scheduling": False,
            "event_limit": 100,
        },
        "field_spec": {
            field: {
                "data_type": "string",
                "providers": [{"type": "template-v1", "template": "${source." + field + "}", "require_values": False}],
            }
        },
        "key_spec": [field],
        "notification_settings": {"grace_period_ms": int(spec["grace_hours"]) * 3_600_000, "backlog_size": 3},
        "notifications": [{"notification_id": notification_id}],
        "storage": [{"type": "persist-to-streams-v1", "streams": [EVENTS_STREAM]}],
    }


def make_call(base: str, password: str) -> Call:
    token = base64.b64encode(f"admin:{password}".encode()).decode()

    def call(method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
        req = urllib.request.Request(
            base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Basic {token}", "Accept": "application/json", "Content-Type": "application/json", "X-Requested-By": "cli"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode(errors="replace")[:600]

    return call


def existing(call: Call, kind: str) -> dict[str, dict]:
    """title -> object, for notifications or event definitions."""
    path, key = {"notifications": ("/events/notifications", "notifications"), "definitions": ("/events/definitions", "event_definitions")}[kind]
    status, data = call("GET", f"{path}?per_page=200")
    if status != 200:
        raise SystemExit(f"GET {path} -> {status}: {data}")
    return {item["title"]: item for item in data[key]}


def run(call: Call, data: dict, env: dict[str, str], mode: str) -> int:
    notes, defs = existing(call, "notifications"), existing(call, "definitions")
    ids: dict[str, str] = {}
    failures = 0

    print("notifications:")
    for key, spec in data["notifications"].items():
        found = notes.get(spec["title"])
        ids[key] = found["id"] if found else PLACEHOLDER_ID
        if mode == "apply":
            body = notification_body(spec, env)
            status, resp = call("PUT", f"/events/notifications/{found['id']}", body) if found else call("POST", "/events/notifications", body)
            ok = status in (200, 201)
            if ok and not found:
                ids[key] = resp["id"]
            print(f"  {'updated' if found else 'created'} {spec['title']}: {status}" + ("" if ok else f" {resp}"))
            failures += not ok
        elif mode == "test":
            if not found:
                print(f"  {spec['title']}: not created yet, run --apply first")
                failures += 1
                continue
            status, resp = call("POST", f"/events/notifications/{found['id']}", {})
            print(f"  test message to {spec['title']}: {status}" + ("" if status in (200, 202, 204) else f" {resp}"))
            failures += status not in (200, 202, 204)
        else:
            print(f"  {'exists' if found else 'MISSING'}: {spec['title']}")

    if mode == "test":
        return failures

    print("event definitions:")
    for spec in data["definitions"]:
        found = defs.get(spec["title"])
        body = definition_body(spec, ids[spec["notification"]])
        if mode == "validate":
            body["id"] = found["id"] if found else PLACEHOLDER_ID  # the endpoint 500s ("hexString can not be null") without one
            status, resp = call("POST", "/events/definitions/validate", body)
            ok = status == 200 and not (isinstance(resp, dict) and (resp.get("failed") or resp.get("errors")))
            print(f"  {'ok' if ok else 'REJECTED'}: {spec['title']}" + ("" if ok else f" ({status}) {json.dumps(resp)[:400]}"))
            failures += not ok
        elif mode == "apply":
            suffix = "?schedule=true"
            status, resp = call("PUT", f"/events/definitions/{found['id']}{suffix}", body) if found else call("POST", f"/events/definitions{suffix}", body)
            ok = status in (200, 201)
            print(f"  {'updated' if found else 'created'} {spec['title']}: {status}" + ("" if ok else f" {json.dumps(resp)[:400]}"))
            failures += not ok
        else:
            print(f"  {'exists' if found else 'MISSING'}: {spec['title']}")
    return failures


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--validate", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--test", action="store_true")
    args = parser.parse_args(argv)
    mode = "validate" if args.validate else "apply" if args.apply else "test" if args.test else "list"

    base = os.environ.get("GRAYLOG_API") or f"http://{os.environ['LAB_IP_GRAYLOG']}:9000/api"
    call = make_call(base, os.environ["GRAYLOG_ROOT_PASSWORD"])
    failures = run(call, load_data(), dict(os.environ), mode)
    print("\nOK" if not failures else f"\n{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
