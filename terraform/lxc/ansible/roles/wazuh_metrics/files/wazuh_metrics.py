#!/usr/bin/env python3
"""Wazuh metrics for node_exporter's textfile collector (docs/wazuh-tuning, Phase 6).

Writes /var/lib/node_exporter/textfile/wazuh.prom (atomically) from:
  * the Wazuh Indexer (read-only scoped user): alerts by rule/level, FIM volume, cluster health, heap, disk,
    alert index count and age, vulnerability findings by severity,
  * the manager container: agent_control (agent status), analysisd and remoted state files (counters, queues),
  * docker inspect: container state and health.

Run every minute by wazuh-metrics.timer. Stdlib only. Each collector fails on its own: wazuh_collector_ok{collector}
says which ones worked, so one broken source never blanks the rest. Metric meanings: docs/wazuh-tuning/README.md.
"""
from __future__ import annotations

import base64
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request

INDEXER_URL = os.environ.get("WAZUH_INDEXER_URL", "https://127.0.0.1:9200")
USER = os.environ.get("WAZUH_USER", "")
PASSWORD = os.environ.get("WAZUH_PASSWORD", "")
OUT_PATH = os.environ.get("WAZUH_METRICS_OUT", "/var/lib/node_exporter/textfile/wazuh.prom")
MANAGER = os.environ.get("WAZUH_MANAGER_CONTAINER", "wazuh-stack-manager")
CONTAINERS = ("wazuh-stack-manager", "wazuh-stack-indexer", "wazuh-stack-dashboard")
FIM_RULES = ["550", "551", "552", "553", "554"]
AGENT_STATUSES = ("Active", "Disconnected", "Never connected", "Pending")

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def esc(value) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def metric(name: str, value, **labels) -> str:
    lab = ",".join(f'{k}="{esc(v)}"' for k, v in labels.items())
    return f"{name}{{{lab}}} {value}" if lab else f"{name} {value}"


def header(name: str, help_: str, kind: str = "gauge") -> list[str]:
    return [f"# HELP {name} {help_}", f"# TYPE {name} {kind}"]


# ---- parsing (pure functions, unit tested) ------------------------------------------

def parse_agent_control(text: str) -> list[dict]:
    """Lines look like '   ID: 001, Name: authentik-stack, IP: any, Active' (manager: 'Active/Local')."""
    agents = []
    for line in text.splitlines():
        m = re.match(r"\s*ID:\s*(\d+),\s*Name:\s*([^,]+),\s*IP:\s*([^,]+),\s*(.+?)\s*$", line)
        if m:
            agents.append({"id": m.group(1), "name": m.group(2).strip(), "status": m.group(4).strip()})
    return agents


def parse_state(text: str) -> dict[str, float]:
    """analysisd/remoted state files: key='value' lines, '#' comments; keep the numeric ones."""
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            try:
                out[key.strip()] = float(value.strip().strip("'\""))
            except ValueError:
                pass
    return out


def status_counts(agents: list[dict]) -> dict[str, int]:
    counts = {s: 0 for s in AGENT_STATUSES}
    for a in agents:
        if a["id"] == "000":
            continue
        key = "Active" if a["status"].startswith("Active") else a["status"]
        counts[key] = counts.get(key, 0) + 1
    return counts


def top_share(buckets: list[tuple], total: int) -> float:
    return round(100.0 * buckets[0][1] / total, 2) if buckets and total else 0.0


def index_date(name: str):
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})$", name)
    return time.mktime((int(m[1]), int(m[2]), int(m[3]), 0, 0, 0, 0, 0, 0)) if m else None


# ---- collectors ---------------------------------------------------------------------

def indexer(path: str, body=None):
    auth = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    req = urllib.request.Request(f"{INDEXER_URL}/{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, context=_ctx, timeout=30))


def sh(*argv) -> str:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=True).stdout


def collect_alerts() -> list[str]:
    day = {"range": {"@timestamp": {"gte": "now-24h"}}}
    r = indexer("wazuh-alerts-4.x-*/_search", {
        "size": 0, "track_total_hits": True, "query": day,
        "aggs": {"rules": {"terms": {"field": "rule.id", "size": 10},
                           "aggs": {"d": {"terms": {"field": "rule.description", "size": 1}}, "l": {"terms": {"field": "rule.level", "size": 1}}}},
                 "levels": {"terms": {"field": "rule.level", "size": 16}},
                 "hour": {"filter": {"range": {"@timestamp": {"gte": "now-1h"}}}},
                 "fim": {"filter": {"bool": {"filter": [{"range": {"@timestamp": {"gte": "now-1h"}}}, {"terms": {"rule.id": FIM_RULES}}]}}}}})
    total = r["hits"]["total"]["value"]
    rules = [(b["key"], b["doc_count"], b["l"]["buckets"][0]["key"] if b["l"]["buckets"] else "", b["d"]["buckets"][0]["key"][:60] if b["d"]["buckets"] else "")
             for b in r["aggregations"]["rules"]["buckets"]]
    lines = header("wazuh_alerts_24h", "Alerts indexed in the last 24 hours.") + [metric("wazuh_alerts_24h", total)]
    lines += header("wazuh_alerts_1h", "Alerts indexed in the last hour.") + [metric("wazuh_alerts_1h", r["aggregations"]["hour"]["doc_count"])]
    lines += header("wazuh_fim_events_1h", "FIM alerts (rules 550-554) in the last hour.") + [metric("wazuh_fim_events_1h", r["aggregations"]["fim"]["doc_count"])]
    lines += header("wazuh_alerts_top_rule_share_percent", "Share of the 24h alert volume taken by the single noisiest rule (target: under 10).")
    lines.append(metric("wazuh_alerts_top_rule_share_percent", top_share(rules, total)))
    lines += header("wazuh_alerts_by_rule_24h", "Alerts in the last 24h for the ten noisiest rules.")
    lines += [metric("wazuh_alerts_by_rule_24h", n, rule=rid, level=lvl, description=desc) for rid, n, lvl, desc in rules]
    lines += header("wazuh_alerts_by_level_24h", "Alerts in the last 24h by rule level.")
    lines += [metric("wazuh_alerts_by_level_24h", b["doc_count"], level=b["key"]) for b in r["aggregations"]["levels"]["buckets"]]
    return lines


def collect_indexer() -> list[str]:
    h = indexer("_cluster/health")
    node = next(iter(indexer("_nodes/stats/jvm,fs")["nodes"].values()))
    idx = indexer("_cat/indices/wazuh-alerts-4.x-*?format=json&bytes=b&h=index,store.size,docs.count")
    dates = [d for d in (index_date(i["index"]) for i in idx) if d]
    oldest_days = round((time.time() - min(dates)) / 86400, 1) if dates else 0
    status = {"green": 0, "yellow": 1, "red": 2}.get(h["status"], 2)
    lines = header("wazuh_indexer_cluster_status", "Indexer cluster status: 0 green, 1 yellow, 2 red.") + [metric("wazuh_indexer_cluster_status", status)]
    lines += header("wazuh_indexer_shards", "Indexer shards by state.")
    for state, key in (("active", "active_shards"), ("unassigned", "unassigned_shards"), ("relocating", "relocating_shards"), ("initializing", "initializing_shards")):
        lines.append(metric("wazuh_indexer_shards", h[key], state=state))
    mem = node["jvm"]["mem"]
    lines += header("wazuh_indexer_heap_used_percent", "Indexer JVM heap in use (stop condition above 85).") + [metric("wazuh_indexer_heap_used_percent", mem["heap_used_percent"])]
    lines += header("wazuh_indexer_heap_max_bytes", "Indexer JVM heap ceiling.") + [metric("wazuh_indexer_heap_max_bytes", mem["heap_max_in_bytes"])]
    fs = node["fs"]["total"]
    lines += header("wazuh_indexer_disk_total_bytes", "Disk size of the indexer data path.") + [metric("wazuh_indexer_disk_total_bytes", fs["total_in_bytes"])]
    lines += header("wazuh_indexer_disk_available_bytes", "Free disk of the indexer data path.") + [metric("wazuh_indexer_disk_available_bytes", fs["available_in_bytes"])]
    lines += header("wazuh_alert_indices", "Daily alert indices kept.") + [metric("wazuh_alert_indices", len(idx))]
    lines += header("wazuh_alert_indices_bytes", "Disk used by the alert indices.") + [metric("wazuh_alert_indices_bytes", sum(int(i["store.size"] or 0) for i in idx))]
    lines += header("wazuh_alert_index_oldest_age_days", "Age of the oldest daily alert index (retention is 90).") + [metric("wazuh_alert_index_oldest_age_days", oldest_days)]
    return lines


def collect_vulns() -> list[str]:
    r = indexer("wazuh-states-vulnerabilities-*/_search", {"size": 0, "track_total_hits": True, "aggs": {"s": {"terms": {"field": "vulnerability.severity", "size": 6}}}})
    lines = header("wazuh_vulnerabilities", "Open vulnerability findings by severity.")
    lines += [metric("wazuh_vulnerabilities", b["doc_count"], severity=b["key"]) for b in r["aggregations"]["s"]["buckets"]]
    lines += header("wazuh_vulnerabilities_total", "Open vulnerability findings.") + [metric("wazuh_vulnerabilities_total", r["hits"]["total"]["value"])]
    return lines


def collect_agents() -> list[str]:
    agents = parse_agent_control(sh("docker", "exec", MANAGER, "/var/ossec/bin/agent_control", "-l"))
    lines = header("wazuh_agents", "Enrolled agents by status (the manager's own agent 000 excluded).")
    lines += [metric("wazuh_agents", n, status=s) for s, n in status_counts(agents).items()]
    lines += header("wazuh_agent_up", "1 when the agent is Active.")
    lines += [metric("wazuh_agent_up", 1 if a["status"].startswith("Active") else 0, agent=a["name"], id=a["id"]) for a in agents if a["id"] != "000"]
    return lines


def collect_manager_state() -> list[str]:
    lines = []
    for name, path in (("analysisd", "wazuh-analysisd.state"), ("remoted", "wazuh-remoted.state")):
        state = parse_state(sh("docker", "exec", MANAGER, "cat", f"/var/ossec/var/run/{path}"))
        lines += header(f"wazuh_{name}_state", f"Numeric values of {path} (counters since the daemon started; use increase()).")
        lines += [metric(f"wazuh_{name}_state", v, key=k) for k, v in sorted(state.items()) if not k.endswith("_usage")]
        if name == "analysisd":
            lines += header("wazuh_analysisd_queue_usage", "analysisd queue fill, 0 to 1 (stop condition above 0.5).")
            lines += [metric("wazuh_analysisd_queue_usage", v, queue=k[:-len("_queue_usage")]) for k, v in sorted(state.items()) if k.endswith("_queue_usage")]
    return lines


def collect_containers() -> list[str]:
    lines = header("wazuh_container_up", "1 when the container is running.") + header("wazuh_container_healthy", "1 when running and healthy (or no healthcheck).")
    for c in CONTAINERS:
        try:
            state, health = sh("docker", "inspect", "-f", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}", c).split()
        except Exception:  # noqa: BLE001 -- a missing container is a metric value, not a crash
            state, health = "missing", "none"
        lines.append(metric("wazuh_container_up", 1 if state == "running" else 0, container=c))
        lines.append(metric("wazuh_container_healthy", 1 if state == "running" and health in ("healthy", "none") else 0, container=c))
    return lines


COLLECTORS = {"alerts": collect_alerts, "indexer": collect_indexer, "vulns": collect_vulns, "agents": collect_agents,
              "manager_state": collect_manager_state, "containers": collect_containers}


def main() -> int:
    started = time.time()
    lines, ok = [], {}
    for name, fn in COLLECTORS.items():
        try:
            lines += fn()
            ok[name] = 1
        except Exception as exc:  # noqa: BLE001
            ok[name] = 0
            print(f"collector {name} failed: {exc}", file=sys.stderr)
    lines += header("wazuh_collector_ok", "1 when that collector ran cleanly this time.")
    lines += [metric("wazuh_collector_ok", v, collector=k) for k, v in ok.items()]
    lines += header("wazuh_metrics_scrape_duration_seconds", "How long one run took.") + [metric("wazuh_metrics_scrape_duration_seconds", round(time.time() - started, 2))]
    lines += header("wazuh_metrics_last_run_timestamp_seconds", "Unix time of this run.") + [metric("wazuh_metrics_last_run_timestamp_seconds", int(time.time()))]
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, OUT_PATH)   # the collector only reads *.prom, and never sees a half-written file
    return 0 if all(ok.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
