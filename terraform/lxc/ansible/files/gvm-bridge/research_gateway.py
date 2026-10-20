#!/usr/bin/env python3
"""Forced-command gateway for the single Metasploitable3 research target.

The registry survives client disconnects. An ambiguous start is never retried
automatically: an operator must reconcile it against GVM first.
"""

import fcntl
import json
import os
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

TARGET = "192.168.70.214"
PORTS = [21, 22, 80, 445, 631, 3306, 8080]
BRIDGE = "http://127.0.0.1:8010"
REGISTRY = Path("/var/lib/gvm-research")
REQUEST_ID = re.compile(r"[a-f0-9]{32}")
UUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
MAX_RESPONSE = 100 * 1024 * 1024
# A requested deletion is not evidence that the scanner has stopped.
TERMINAL = {"Done", "Stopped", "Interrupted"}


class GatewayError(Exception):
    pass


def bridge_call(path, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(BRIDGE + path, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise GatewayError("response_too_large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise GatewayError("invalid_bridge_response")
    return value


def save(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".state-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def execute(request, registry=REGISTRY):
    if not isinstance(request, dict) or set(request) != {"operation", "request_id"}:
        raise GatewayError("invalid_request")
    operation, request_id = request["operation"], request["request_id"]
    if operation not in {"start", "status", "results"} or not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise GatewayError("invalid_request")
    registry.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (registry / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = registry / f"{request_id}.json"
        if operation == "start":
            if path.exists():
                record = json.loads(path.read_text())
                if record.get("state") == "starting":
                    raise GatewayError("start_unknown")
                return record
            for other in registry.glob("*.json"):
                record = json.loads(other.read_text())
                if record.get("state") != "terminal":
                    raise GatewayError("previous_scan_unresolved")
            record = {"request_id": request_id, "state": "starting"}
            save(path, record)
            result = bridge_call("/scan/start", {"target_ip": TARGET, "ports": PORTS})
            task_id, report_id = result.get("task_id"), result.get("report_id")
            if not isinstance(task_id, str) or not UUID.fullmatch(task_id) or not isinstance(report_id, str) or not UUID.fullmatch(report_id):
                raise GatewayError("start_unknown")
            record.update(state="started", task_id=task_id, report_id=report_id)
            save(path, record)
            return record
        if not path.exists():
            raise GatewayError("request_not_found")
        record = json.loads(path.read_text())
        task_id = record.get("task_id")
        if not isinstance(task_id, str) or not UUID.fullmatch(task_id):
            raise GatewayError("start_unknown")
        if operation == "status":
            result = bridge_call(f"/scan/status/{task_id}")
            if result.get("status") in TERMINAL:
                record.update(state="terminal", status=result["status"])
                save(path, record)
            return {"request_id": request_id, "task_id": task_id, "report_id": record.get("report_id"), **result}
        if record.get("state") != "terminal" or record.get("status") != "Done":
            raise GatewayError("scan_not_done")
        result = bridge_call(f"/scan/results/{task_id}")
        if result.get("complete") is not True or not isinstance(result.get("results"), list):
            raise GatewayError("incomplete_results")
        if any(item.get("host") != TARGET for item in result["results"] if isinstance(item, dict)) or any(not isinstance(item, dict) for item in result["results"]):
            raise GatewayError("wrong_target")
        return result


def main():
    try:
        raw = sys.stdin.buffer.read(4097)
        if len(raw) > 4096:
            raise GatewayError("invalid_request")
        request = json.loads(raw)
        result = execute(request)
        print(json.dumps({"ok": True, "result": result}, separators=(",", ":")))
        return 0
    except GatewayError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
    except Exception:
        print(json.dumps({"ok": False, "error": "gateway_failure"}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
