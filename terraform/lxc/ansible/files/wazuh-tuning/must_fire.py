#!/usr/bin/env python3
"""Detection regression suite (must-fire) -- docs/wazuh-tuning/plan.md Phase 0.

Runs on the wazuh-stack host next to wazuh_tuning.py. Replays each case in
must_fire_cases.json through the manager's logtest endpoint (PUT /logtest, which
evaluates the event against the live ruleset and does NOT write an alert) and checks
that an expected rule id fires at or above the level floor. Also confirms that the
rules logtest cannot exercise still exist in the loaded ruleset.

Cases marked needs_sample take a real event from the indexer (the helper's `sample`
mode logic), so docker events are tested with the exact shape the agents send. A
case may also rewrite the command, to prove a non-health-check exec still alerts
after the 87907 suppression.

Exit status 0 only if every case passes. Prints PASS/FAIL per case.
"""
import json
import os
import sys
import urllib.request

import wazuh_tuning as wt

HERE = os.path.dirname(os.path.abspath(__file__))


def api_call(method, path, body=None):
    wt.api("/manager/info")  # ensures wt._token is set
    req = urllib.request.Request(
        f"{wt.API}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {wt._token}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, context=wt._ctx, timeout=60))["data"]


def logtest(event, log_format, location):
    d = api_call("PUT", "/logtest", {"event": event, "log_format": log_format, "location": location})
    out = d.get("output", {})
    rule = out.get("rule") or {}
    return str(rule.get("id", "")), int(rule.get("level", 0))


def sample_event(rule_id, replace_cmd=None):
    ev = wt.mode_sample([rule_id, "1"])["events"]
    if not ev:
        raise RuntimeError(f"no recent alert for rule {rule_id} to use as a sample")
    log = ev[0]["full_log"]
    if replace_cmd:
        doc = json.loads(log)
        doc["docker"]["Actor"]["Attributes"]["execID"] = "mustfire"
        doc["docker"]["Action"] = f"exec_start: {replace_cmd}"
        log = json.dumps(doc)
    return log


def check(case, fired_id, fired_level):
    return fired_id in case["ids"] and fired_level >= case["min_level"]


def run(cases_path=os.path.join(HERE, "must_fire_cases.json")):
    spec = json.load(open(cases_path))
    failures = 0
    for case in spec["cases"]:
        try:
            event = case.get("event") or sample_event(case["sample_rule"], case.get("replace_cmd_with"))
            rid, lvl = logtest(event, case["format"], case["location"])
            ok = check(case, rid, lvl)
            detail = f"fired {rid or 'none'} L{lvl}, want {case['ids']} >=L{case['min_level']}"
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"error: {exc}"
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['name']}: {detail}")
    for r in spec["ruleset_present"]["rules"]:
        try:
            items = wt.api(f"/rules?rule_ids={r['id']}")["affected_items"]
            ok = bool(items) and items[0]["level"] >= r["min_level"] and items[0].get("status", "enabled") == "enabled"
            detail = f"rule {r['id']} " + (f"L{items[0]['level']}" if items else "missing")
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"error: {exc}"
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  ruleset: {r['name']}: {detail}")
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    return failures


if __name__ == "__main__":
    sys.exit(1 if run(*sys.argv[1:2]) else 0)
