#!/usr/bin/env python3
"""Greenbone metrics for node_exporter's textfile collector.

Writes /var/lib/node_exporter/textfile/gvm.prom (atomically) from:
  * gvm-bridge's /tasks/summary (loopback :8010): every Task, its status and
    last-report start/end/result counts (get_tasks only, never get_reports),
  * the redis-server container (memory, cap, keys per db),
  * the container's cgroup memory.events (oom_kill).

Run every minute by gvm-metrics.timer. Stdlib only. Metrics are documented in
docs/greenbone-stack/README.md ("Grafana").
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

BRIDGE_URL = os.environ.get("GVM_BRIDGE_URL", "http://127.0.0.1:8010")
OUT_PATH = os.environ.get("GVM_METRICS_OUT", "/var/lib/node_exporter/textfile/gvm.prom")
REDIS_CONTAINER = os.environ.get("GVM_REDIS_CONTAINER", "greenbone-community-edition-redis-server-1")
MEMORY_EVENTS = os.environ.get("GVM_MEMORY_EVENTS", "/sys/fs/cgroup/memory.events")
STATUSES = ("Running", "Requested", "Queued", "Done", "Interrupted", "Stopped", "Stop Requested", "New")


def kind_of(name: str) -> str:
    if name.startswith("Credentialed scan: "):
        return "credentialed"
    if name.startswith("LAN scan: "):
        if name.endswith(" discovery"):
            return "discovery"
        if name.endswith(" full-vuln"):
            return "full_vuln"
    return "other"


def esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def task_lines(tasks: list[dict]) -> list[str]:
    lines = [
        "# HELP gvm_tasks Greenbone tasks by kind and status.",
        "# TYPE gvm_tasks gauge",
    ]
    counts: dict[tuple[str, str], int] = {}
    kinds = {"credentialed", "discovery", "full_vuln", "other"}
    for t in tasks:
        key = (kind_of(t.get("name") or ""), t.get("status") or "Unknown")
        counts[key] = counts.get(key, 0) + 1
    for kind in sorted(kinds):
        for status in STATUSES:
            lines.append(f'gvm_tasks{{kind="{kind}",status="{esc(status)}"}} {counts.pop((kind, status), 0)}')
    for (kind, status), n in sorted(counts.items()):
        lines.append(f'gvm_tasks{{kind="{kind}",status="{esc(status)}"}} {n}')

    lines += [
        "# HELP gvm_task_running 1 while a task is Running.",
        "# TYPE gvm_task_running gauge",
        "# HELP gvm_task_progress_percent Progress of a running task.",
        "# TYPE gvm_task_progress_percent gauge",
        "# HELP gvm_task_scheduled 1 if the task has a schedule attached.",
        "# TYPE gvm_task_scheduled gauge",
        "# HELP gvm_task_last_scan_start_timestamp_seconds Start of the task's last report.",
        "# TYPE gvm_task_last_scan_start_timestamp_seconds gauge",
        "# HELP gvm_task_last_scan_duration_seconds Duration of the task's last finished report.",
        "# TYPE gvm_task_last_scan_duration_seconds gauge",
        "# HELP gvm_task_last_results Result count of the last report by severity class.",
        "# TYPE gvm_task_last_results gauge",
    ]
    for t in tasks:
        name = t.get("name") or ""
        labels = f'task="{esc(name)}",kind="{kind_of(name)}"'
        lines.append(f"gvm_task_running{{{labels}}} {1 if t.get('status') == 'Running' else 0}")
        lines.append(f"gvm_task_scheduled{{{labels}}} {1 if t.get('schedule') else 0}")
        try:
            progress = float(t.get("progress"))
        except (TypeError, ValueError):
            progress = None
        if progress is not None and progress >= 0 and t.get("status") == "Running":
            lines.append(f"gvm_task_progress_percent{{{labels}}} {progress:g}")
        start = parse_ts(t.get("last_scan_start"))
        end = parse_ts(t.get("last_scan_end"))
        if start:
            lines.append(f"gvm_task_last_scan_start_timestamp_seconds{{{labels}}} {start:.0f}")
            if end and end >= start:
                lines.append(f"gvm_task_last_scan_duration_seconds{{{labels}}} {end - start:.0f}")
        for severity, n in (t.get("last_counts") or {}).items():
            lines.append(f'gvm_task_last_results{{{labels},severity="{esc(severity)}"}} {n}')
    return lines


def parse_redis_info(info_memory: str, info_keyspace: str, maxmemory: str) -> dict:
    out = {"used": None, "maxmemory": None, "keys": {}}
    for line in info_memory.splitlines():
        if line.startswith("used_memory:"):
            out["used"] = int(line.split(":", 1)[1])
    try:
        out["maxmemory"] = int(maxmemory)
    except ValueError:
        pass
    for line in info_keyspace.splitlines():
        if line.startswith("db") and ":keys=" in line:
            db, rest = line.split(":", 1)
            out["keys"][db] = int(rest.split("keys=")[1].split(",")[0])
    return out


def redis_lines(info: dict) -> list[str]:
    lines = []
    if info["used"] is not None:
        lines += ["# TYPE gvm_redis_used_memory_bytes gauge", f"gvm_redis_used_memory_bytes {info['used']}"]
    if info["maxmemory"] is not None:
        lines += ["# TYPE gvm_redis_maxmemory_bytes gauge", f"gvm_redis_maxmemory_bytes {info['maxmemory']}"]
    lines.append("# TYPE gvm_redis_keys gauge")
    lines += [f'gvm_redis_keys{{db="{db}"}} {n}' for db, n in sorted(info["keys"].items())]
    # db0 holds the pubsub/state key, db1/db2 the VT cache and Notus: only db3+
    # are per-host scan KBs.
    scan_dbs = {d: n for d, n in info["keys"].items() if d[2:].isdigit() and int(d[2:]) >= 3}
    lines += ["# TYPE gvm_redis_scan_kbs gauge", f"gvm_redis_scan_kbs {len(scan_dbs)}"]
    return lines


def redis_cli(*args: str) -> str:
    return subprocess.run(
        ["docker", "exec", REDIS_CONTAINER, "redis-cli", "-s", "/run/redis/redis.sock", *args],
        check=True, capture_output=True, text=True, timeout=20,
    ).stdout


def oom_kills() -> int | None:
    try:
        for line in open(MEMORY_EVENTS):
            if line.startswith("oom_kill "):
                return int(line.split()[1])
    except OSError:
        pass
    return None


def collect() -> list[str]:
    lines: list[str] = []
    ok_bridge = ok_redis = 0
    try:
        with urllib.request.urlopen(f"{BRIDGE_URL}/tasks/summary", timeout=60) as resp:
            tasks = json.load(resp)["tasks"]
        lines += task_lines(tasks)
        ok_bridge = 1
    except Exception as exc:  # noqa: BLE001 -- report and carry on with the rest
        print(f"bridge: {exc}", file=sys.stderr)
    try:
        info = parse_redis_info(
            redis_cli("info", "memory"), redis_cli("info", "keyspace"),
            (redis_cli("config", "get", "maxmemory").split() + ["", ""])[1],
        )
        lines += redis_lines(info)
        ok_redis = 1
    except Exception as exc:  # noqa: BLE001
        print(f"redis: {exc}", file=sys.stderr)
    kills = oom_kills()
    if kills is not None:
        lines += ["# TYPE gvm_lxc_oom_kills_total counter", f"gvm_lxc_oom_kills_total {kills}"]
    lines += [
        "# TYPE gvm_metrics_source_up gauge",
        f'gvm_metrics_source_up{{source="bridge"}} {ok_bridge}',
        f'gvm_metrics_source_up{{source="redis"}} {ok_redis}',
        "# TYPE gvm_metrics_last_run_timestamp_seconds gauge",
        f"gvm_metrics_last_run_timestamp_seconds {datetime.now(timezone.utc).timestamp():.0f}",
    ]
    return lines


def main() -> int:
    body = "\n".join(collect()) + "\n"
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(body)
    os.chmod(tmp, 0o644)
    os.replace(tmp, OUT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
