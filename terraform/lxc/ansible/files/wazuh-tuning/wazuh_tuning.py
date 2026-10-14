#!/usr/bin/env python3
"""Wazuh measurement helper -- docs/wazuh-tuning/runbook.md.

Runs ON the wazuh-stack host (the playbook wazuh-tuning.yml copies it to
/opt/wazuh-stack and runs it with the secrets in the environment). It talks to the
indexer on 127.0.0.1:9200 and the manager API on 127.0.0.1:55000, and to docker for
container facts. Every mode is read-only: GET requests and search queries only.

Modes:
  health                  containers (state/health/RSS), indexer heap, disk, analysisd
                          counters and queues, manager and agent versions
  alerts [hours]          alerts by rule, agent, level and group (default 24 h)
  noise <rule> [hours]    one rule broken down by agent and its most useful fields
  commands [hours]        every distinct docker exec command behind rule 87907 (1d pattern list)
  fimpaths [hours]        fleet-wide FIM events by path (Phase 2a review list)
  sample <rule> [n]       n real documents of a rule (full_log) -- logtest inputs
  agents                  agent status, versions, groups, manager daemons, config validation
  vulns                   open vulnerability findings by severity, agent, package, CVE
  retention               ISM policies, alert index ages/sizes, shard count, disk
  fim <agent> [hours]     FIM events (rules 550-554) of one agent by path
  sampler-line            one line of resource numbers (the playbook loops over this)

Options: --json PATH writes the structured result next to the printed summary, so two
runs can be diffed (see diff_json below).
"""
import base64
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter

INDEXER = os.environ.get("WAZUH_INDEXER_URL", "https://127.0.0.1:9200")
API = os.environ.get("WAZUH_API_URL", "https://127.0.0.1:55000")
MANAGER = "wazuh-stack-manager"
CONTAINERS = ("wazuh-stack-manager", "wazuh-stack-indexer", "wazuh-stack-dashboard")
ALERTS = "wazuh-alerts-4.x-*"
VULNS = "wazuh-states-vulnerabilities-*"
FIM_RULES = ["550", "551", "552", "553", "554"]

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _basic(user, secret_env):
    return "Basic " + base64.b64encode(f"{user}:{os.environ[secret_env]}".encode()).decode()


def indexer(path, body=None):
    req = urllib.request.Request(
        f"{INDEXER}/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": _basic("admin", "WAZUH_INDEXER_ADMIN_PASSWORD"),
                 "Content-Type": "application/json"})
    try:
        raw = urllib.request.urlopen(req, context=_ctx, timeout=90).read().decode()
    except urllib.error.HTTPError as exc:  # keep the indexer's reason, a bare "400" says nothing
        raise RuntimeError(f"{exc.code} from {path}: {exc.read().decode()[:600]}") from None
    try:
        return json.loads(raw)
    except ValueError:
        return raw


_token = None


def api(path):
    global _token
    if _token is None:
        req = urllib.request.Request(
            f"{API}/security/user/authenticate?raw=true", method="POST",
            headers={"Authorization": _basic("wazuh-wui", "WAZUH_API_PASSWORD")})
        _token = urllib.request.urlopen(req, context=_ctx, timeout=30).read().decode()
    req = urllib.request.Request(f"{API}{path}", headers={"Authorization": f"Bearer {_token}"})
    return json.load(urllib.request.urlopen(req, context=_ctx, timeout=60))["data"]


def sh(*argv):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    return p.stdout.strip()


def window(arg):
    """'24' -> 24 hours, '10m' -> 10 minutes (kept as given so the output says which)."""
    return arg if arg.endswith(("m", "h")) else int(arg)


def day(hours):
    """Range filter for the last `hours` hours, or a string like '10m'."""
    return {"range": {"@timestamp": {"gte": f"now-{hours}{'' if isinstance(hours, str) else 'h'}"}}}


def rule_q(rule_id, hours):
    return {"bool": {"filter": [day(hours), {"term": {"rule.id": rule_id}}]}}


def search(index, query, aggs=None, size=0):
    body = {"size": size, "track_total_hits": True, "query": query}  # default caps at 10,000
    if aggs:
        body["aggs"] = aggs
    return indexer(f"{index}/_search", body)


def total(r):
    return r["hits"]["total"]["value"]


def terms(field, size=10, **sub):
    agg = {"terms": {"field": field, "size": size}}
    if sub:
        agg["aggs"] = sub
    return agg


def buckets(r, name):
    return [(b["key"], b["doc_count"]) for b in r["aggregations"][name]["buckets"]]


# ---- modes -----------------------------------------------------------------------

def analysisd_state():
    """Counters from analysisd's state file (events received/dropped, queue usage 0-1)."""
    out = {}
    text = sh("docker", "exec", MANAGER, "cat", "/var/ossec/var/run/wazuh-analysisd.state")
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            try:
                out[k.strip()] = float(v.strip("' "))
            except ValueError:
                pass
    return out


def heap():
    j = indexer("_nodes/stats/jvm")["nodes"]
    n = next(iter(j.values()))["jvm"]["mem"]
    return {"heap_used_pct": n["heap_used_percent"], "heap_max_mb": n["heap_max_in_bytes"] // 2**20}


def mem_available_mb():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return -1


def mode_health(_args):
    r = {"containers": {}, "analysisd": analysisd_state(), "heap": heap(),
         "mem_available_mb": mem_available_mb(), "load": open("/proc/loadavg").read().split()[0]}
    for c in CONTAINERS:
        r["containers"][c] = {
            "health": sh("docker", "inspect", "-f", "{{.State.Health.Status}}", c),
            "state": sh("docker", "inspect", "-f", "{{.State.Status}}", c),
            "mem": sh("docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", c)}
    r["disk"] = sh("df", "-h", "--output=target,size,used,pcent", "/var/lib/docker", "/").splitlines()
    ag = api("/agents?limit=500&select=status,version")["affected_items"]
    r["agents"] = {"status": Counter(a["status"] for a in ag), "version": Counter(a.get("version") for a in ag)}
    r["manager_version"] = api("/manager/info")["affected_items"][0]["version"]
    r["cluster"] = indexer("_cluster/health")["status"]
    return r


def mode_alerts(args):
    hours = window(args[0]) if args else 24
    r = search(ALERTS, day(hours), {
        "rules": terms("rule.id", 15, d=terms("rule.description", 1), lvl=terms("rule.level", 1),
                       agents={"cardinality": {"field": "agent.name"}}),
        "agents": terms("agent.name", 40), "levels": terms("rule.level", 16),
        "groups": terms("rule.groups", 14)})
    n = total(r)
    rules = [{"rule": b["key"], "count": b["doc_count"], "pct": round(100 * b["doc_count"] / max(n, 1), 1),
              "level": b["lvl"]["buckets"][0]["key"], "agents": b["agents"]["value"],
              "description": b["d"]["buckets"][0]["key"][:80]} for b in r["aggregations"]["rules"]["buckets"]]
    return {"hours": hours, "total": n, "top_rule_pct": rules[0]["pct"] if rules else 0, "rules": rules,
            "agents": buckets(r, "agents"), "levels": buckets(r, "levels"), "groups": buckets(r, "groups")}


NOISE_FIELDS = {
    "87907": ["data.docker.Actor.Attributes.name", "data.docker.Action"],
    "550": ["syscheck.path"],
    "2501": ["data.srcip", "data.srcuser"],
    "510": ["data.title", "data.file"],
    "5710": ["data.srcip", "data.srcuser"],
    "5712": ["data.srcip", "data.srcuser"],
    "5716": ["data.srcip", "data.srcuser"],
    "5740": ["data.srcip", "data.srcuser"],
    "5760": ["data.srcip", "data.srcuser"],
}


def mode_noise(args):
    rid, hours = args[0], int(args[1]) if len(args) > 1 else 24
    aggs = {"agent": terms("agent.name", 15)}
    fields = NOISE_FIELDS.get(rid, ["rule.description", "location"])
    for i, f in enumerate(fields):
        aggs[f"f{i}"] = terms(f, 80, a=terms("agent.name", 3))
    r = search(ALERTS, rule_q(rid, hours), aggs)
    out = {"rule": rid, "hours": hours, "total": total(r), "agent": buckets(r, "agent")}
    for i, f in enumerate(fields):
        out[f] = [(b["key"], b["doc_count"], [x["key"] for x in b["a"]["buckets"]])
                  for b in r["aggregations"][f"f{i}"]["buckets"]]
    return out


def mode_commands(args):
    """Distinct docker exec commands behind rule 87907, with the containers and agents running them."""
    hours = int(args[0]) if args else 24
    r = search(ALERTS, rule_q("87907", hours), {"c": terms("data.docker.Action", 300, ct=terms("data.docker.Actor.Attributes.name", 3),
                                                       ag=terms("agent.name", 3))})
    return {"hours": hours, "total": total(r), "distinct": len(r["aggregations"]["c"]["buckets"]),
            "other": r["aggregations"]["c"]["sum_other_doc_count"],
            "commands": [(b["key"], b["doc_count"], [x["key"] for x in b["ct"]["buckets"]], [x["key"] for x in b["ag"]["buckets"]])
                         for b in r["aggregations"]["c"]["buckets"]]}


def mode_fimpaths(args):
    """Fleet-wide FIM events (rules 550-554) by path, with the agents and rule ids behind each."""
    hours = window(args[0]) if args else 24
    q = {"bool": {"filter": [day(hours), {"terms": {"rule.id": FIM_RULES}}]}}
    r = search(ALERTS, q, {"p": terms("syscheck.path", int(args[1]) if len(args) > 1 else 150, a=terms("agent.name", 4), r=terms("rule.id", 3))})
    return {"hours": hours, "total": total(r), "other": r["aggregations"]["p"]["sum_other_doc_count"],
            "paths": [(b["key"], b["doc_count"], [x["key"] for x in b["a"]["buckets"]], [x["key"] for x in b["r"]["buckets"]])
                      for b in r["aggregations"]["p"]["buckets"]]}


def mode_hist(args):
    """Hourly histogram of one rule, plus how many events do / do not contain a phrase in full_log."""
    rid, hours = args[0], window(args[1]) if len(args) > 1 else 24
    phrase = args[2] if len(args) > 2 else None
    r = search(ALERTS, rule_q(rid, hours), {"h": {"date_histogram": {"field": "@timestamp", "fixed_interval": "1h"}}})
    out = {"rule": rid, "total": total(r), "hourly": [(b["key_as_string"][5:13], b["doc_count"]) for b in r["aggregations"]["h"]["buckets"] if b["doc_count"]]}
    if phrase:
        q = {"bool": {"filter": [day(hours), {"term": {"rule.id": rid}}, {"match_phrase": {"full_log": phrase}}]}}
        out["with_phrase"] = total(search(ALERTS, q))
        out["without_phrase"] = out["total"] - out["with_phrase"]
    return out


def mode_agentrules(args):
    """Every rule one agent produced in a window, with a sample message each (for 'why did X not alert?')."""
    agent, hours = args[0], window(args[1]) if len(args) > 1 else 24
    q = {"bool": {"filter": [day(hours), {"term": {"agent.name": agent}}]}}
    r = search(ALERTS, q, {"r": terms("rule.id", 40, d=terms("rule.description", 1), l=terms("rule.level", 1),
                                      loc=terms("location", 1))}, size=0)
    return {"agent": agent, "hours": hours, "total": total(r),
            "rules": [(b["key"], b["doc_count"], "L%s" % b["l"]["buckets"][0]["key"], b["loc"]["buckets"][0]["key"],
                       b["d"]["buckets"][0]["key"][:70]) for b in r["aggregations"]["r"]["buckets"]]}


def mode_sample(args):
    rid, n = args[0], int(args[1]) if len(args) > 1 else 5
    q = rule_q(rid, window(args[3]) if len(args) > 3 else 24)
    if len(args) > 2 and args[2] != "-":   # optional: only this agent
        q["bool"]["filter"].append({"term": {"agent.name": args[2]}})
    r = search(ALERTS, q, size=n)
    return {"rule": rid, "events": [{"agent": h["_source"]["agent"]["name"], "time": h["_source"].get("@timestamp"), "location": h["_source"].get("location"),
                                      "full_log": h["_source"].get("full_log"), "data": h["_source"].get("data")} for h in r["hits"]["hits"]]}


def mode_agents(_args):
    ag = api("/agents?limit=500&select=id,name,status,version,group,lastKeepAlive,os.name")["affected_items"]
    mgr = api("/manager/info")["affected_items"][0]
    st = api("/manager/status")["affected_items"][0]
    return {"manager_version": mgr["version"], "count": len(ag),
            "status": Counter(a["status"] for a in ag), "version": Counter(a.get("version") for a in ag),
            "group": Counter(",".join(a.get("group", [])) for a in ag),
            "agent_groups": sorted((a["name"], a["id"], ",".join(a.get("group", []))) for a in ag),
            "not_active": [(a["name"], a["status"], a.get("lastKeepAlive")) for a in ag if a["status"] != "active"],
            "daemons_not_running": [k for k, v in st.items() if v != "running"],
            "config_validation": api("/manager/configuration/validation")["affected_items"][0]}


def mode_vulns(_args):
    q = {"match_all": {}}
    r = search(VULNS, q, {"sev": terms("vulnerability.severity", 6), "agent": terms("agent.name", 40),
                          "pkg": terms("package.name", 10), "cve": terms("vulnerability.id", 10)})
    return {"total": total(r), "severity": buckets(r, "sev"), "agent": buckets(r, "agent"),
            "package": buckets(r, "pkg"), "top_cve": buckets(r, "cve")}


def mode_retention(_args):
    try:
        pol = [p["_id"] for p in indexer("_plugins/_ism/policies")["policies"]]
    except Exception as exc:  # noqa: BLE001 -- 404 when the ISM plugin has no policies
        pol = [f"none ({exc})"]
    try:
        managed = indexer("_plugins/_ism/explain/wazuh-alerts-4.x-*")["total_managed_indices"]
    except Exception as exc:  # noqa: BLE001
        managed = f"unknown ({exc})"
    idx = indexer("_cat/indices/wazuh-alerts-4.x-*?format=json&h=index,creation.date,store.size,docs.count&bytes=mb&s=index")
    shards = indexer("_cluster/health")
    return {"ism_policies": pol, "alert_indices": len(idx), "ism_managed_alert_indices": managed, "oldest": idx[0]["index"] if idx else None,
            "newest": idx[-1]["index"] if idx else None, "alert_mb": sum(int(i["store.size"] or 0) for i in idx),
            "shards": shards["active_shards"], "indices": [(i["index"], int(i["docs.count"]), int(i["store.size"] or 0)) for i in idx], "allocation": indexer("_cat/allocation?format=json&bytes=mb")}


def mode_fim(args):
    agent, hours = args[0], int(args[1]) if len(args) > 1 else 24
    q = {"bool": {"filter": [day(hours), {"term": {"agent.name": agent}}, {"terms": {"rule.id": FIM_RULES}}]}}
    r = search(ALERTS, q, {"path": terms("syscheck.path", 30), "rule": terms("rule.id", 5)})
    return {"agent": agent, "hours": hours, "total": total(r), "rule": buckets(r, "rule"), "path": buckets(r, "path")}


def mode_sampler_line(_args):
    a = analysisd_state()
    h = heap()
    q = max([v for k, v in a.items() if k.endswith("_queue_usage")] or [0])
    rss = sh("docker", "stats", "--no-stream", "--format", "{{.Name}}={{.MemUsage}}", *CONTAINERS).replace("\n", " ")
    disk = sh("df", "--output=pcent", "/var/lib/docker").splitlines()[-1].strip()
    return (f"heap={h['heap_used_pct']}% mem_avail_mb={mem_available_mb()} load={open('/proc/loadavg').read().split()[0]} "
            f"events={int(a.get('total_events_decoded', 0))} dropped={int(a.get('events_dropped', 0))} "
            f"max_queue_usage={q:.2f} disk={disk} {rss}")


MODES = {"health": mode_health, "alerts": mode_alerts, "noise": mode_noise, "sample": mode_sample, "commands": mode_commands, "hist": mode_hist, "agentrules": mode_agentrules, "fimpaths": mode_fimpaths,
         "agents": mode_agents, "vulns": mode_vulns, "retention": mode_retention, "fim": mode_fim,
         "sampler-line": mode_sampler_line}

# Stop conditions from plan.md -- evaluated against `health` output.
def stop_conditions(h, baseline_dropped=None):
    bad = []
    if h["heap"]["heap_used_pct"] > 85:
        bad.append("indexer heap above 85%")
    if h["mem_available_mb"] < 800:
        bad.append("free RAM under 800MB")
    if any(v > 0.5 for k, v in h["analysisd"].items() if k.endswith("_queue_usage")):
        bad.append("a queue above 50%")
    if baseline_dropped is not None and h["analysisd"].get("events_dropped", 0) > baseline_dropped:
        bad.append("events_dropped increased")
    if h["agents"]["status"].get("active", 0) != sum(h["agents"]["status"].values()):
        bad.append("an agent is not active")
    return bad


def diff_json(before, after, path=""):
    """Flat list of (path, before, after) for every differing leaf of two result dicts."""
    out = []
    if isinstance(before, dict) and isinstance(after, dict):
        for k in sorted(set(before) | set(after)):
            out += diff_json(before.get(k), after.get(k), f"{path}/{k}")
    elif before != after:
        out.append((path, before, after))
    return out


def main(argv):
    args = list(argv[1:])
    out_path = None
    if "--json" in args:
        i = args.index("--json")
        out_path = args[i + 1]
        del args[i:i + 2]
    if not args or args[0] not in MODES:
        sys.exit(__doc__)
    result = MODES[args[0]](args[1:])
    if isinstance(result, str):
        print(result)
        return
    text = json.dumps(result, indent=1, default=lambda o: dict(o) if isinstance(o, Counter) else str(o))
    print(text)
    if out_path:
        with open(out_path, "w") as f:
            f.write(text)


if __name__ == "__main__":
    main(sys.argv)
