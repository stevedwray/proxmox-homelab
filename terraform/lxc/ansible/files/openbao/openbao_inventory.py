#!/usr/bin/env python3
"""Export a secrets INVENTORY (never values) for the Grafana "OpenBao" dashboard.

Runs ON the OpenBao LXC from openbao-inventory.timer (every 15 minutes).

Auth: AppRole "metrics" (policy: list+read on kv/metadata/* only), credentials
in /etc/openbao-metrics/{role-id,secret-id} (root 0600). KV v2 metadata holds
version numbers and timestamps only; secret values live under kv/data/*, which
that policy does not grant.

Field counts come from /etc/openbao-metrics/manifest.json (a copy of the repo's
secrets/manifest.json -- field NAMES only), which also gives manifest-vs-OpenBao
drift. Output: node_exporter textfile /var/lib/node_exporter/textfile/openbao_inventory.prom.
Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ADDR = "https://192.168.20.16:8200"
CACERT = "/usr/local/share/ca-certificates/homelab-root.crt"
CRED_DIR = Path("/etc/openbao-metrics")
MANIFEST = CRED_DIR / "manifest.json"
OUT = Path("/var/lib/node_exporter/textfile/openbao_inventory.prom")


def parse_rfc3339(value: str) -> float:
    """OpenBao timestamps carry nanoseconds; Python parses at most microseconds."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$", value)
    if not m:
        raise ValueError(f"unparseable timestamp: {value!r}")
    base, frac, tz = m.groups()
    dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    offset = timezone.utc if tz == "Z" else datetime.strptime(tz.replace(":", ""), "%z").tzinfo
    ts = dt.replace(tzinfo=offset).timestamp()
    return ts + (float(frac) if frac else 0.0)


def category(entry: str) -> str:
    return entry.split("/", 1)[0]


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def build_metrics(live: dict[str, dict], manifest_entries: dict[str, dict], now: float) -> str:
    """live: entry -> {"version": int, "updated": float}; manifest_entries: entry -> {"fields": [...]}."""
    lines: list[str] = []

    def metric(name: str, help_text: str, samples: list[tuple[dict, float]]) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        for labels, value in samples:
            lab = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
            lines.append(f"{name}{{{lab}}} {value:g}" if lab else f"{name} {value:g}")

    cats = sorted({category(e) for e in live} | {category(e) for e in manifest_entries})
    metric("openbao_kv_entries", "KV entries present in OpenBao, by category.",
           [({"category": c}, sum(1 for e in live if category(e) == c)) for c in cats])
    metric("openbao_kv_fields", "Fields (from the repo manifest) of entries present in OpenBao, by category.",
           [({"category": c}, sum(len(manifest_entries[e]["fields"]) for e in live
                                   if category(e) == c and e in manifest_entries)) for c in cats])
    rows = sorted(live)
    metric("openbao_kv_entry_fields", "Fields per entry, from the repo manifest (0 if not in the manifest).",
           [({"entry": e, "category": category(e)}, len(manifest_entries.get(e, {}).get("fields", []))) for e in rows])
    metric("openbao_kv_entry_version", "Current KV v2 version of each entry (increments on every write).",
           [({"entry": e, "category": category(e)}, live[e]["version"]) for e in rows])
    metric("openbao_kv_entry_updated_timestamp_seconds", "Unix time of each entry's latest version.",
           [({"entry": e, "category": category(e)}, live[e]["updated"]) for e in rows])
    missing_in_bao = sorted(set(manifest_entries) - set(live))
    missing_in_manifest = sorted(set(live) - set(manifest_entries))
    metric("openbao_kv_manifest_drift", "Entries listed in the manifest but absent from OpenBao, and vice versa.",
           [({"kind": "missing_in_openbao"}, len(missing_in_bao)),
            ({"kind": "missing_in_manifest"}, len(missing_in_manifest))])
    metric("openbao_inventory_last_success_timestamp_seconds", "Unix time of the last successful inventory run.",
           [({}, now)])
    return "\n".join(lines) + "\n"


class Client:
    def __init__(self) -> None:
        ctx = ssl.create_default_context(cafile=CACERT)
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        self.token: str | None = None

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(f"{ADDR}/v1/{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("X-Vault-Token", self.token)
        with self.opener.open(req, timeout=15) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}

    def list_keys(self, path: str) -> list[str]:
        try:
            return self.call("LIST", f"kv/metadata/{path}")["data"]["keys"]
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            raise


def walk(client: Client, prefix: str = "") -> list[str]:
    entries = []
    for key in client.list_keys(prefix):
        if key.endswith("/"):
            entries.extend(walk(client, prefix + key))
        else:
            entries.append(prefix + key)
    return entries


def main() -> int:
    client = Client()
    try:
        resp = client.call("POST", "auth/approle/login", {
            "role_id": (CRED_DIR / "role-id").read_text().strip(),
            "secret_id": (CRED_DIR / "secret-id").read_text().strip(),
        })
        client.token = resp["auth"]["client_token"]
        live = {}
        for entry in walk(client):
            meta = client.call("GET", f"kv/metadata/{entry}")["data"]
            live[entry] = {"version": int(meta["current_version"]), "updated": parse_rfc3339(meta["updated_time"])}
        manifest_entries = json.loads(MANIFEST.read_text())["entries"]
        text = build_metrics(live, manifest_entries, time.time())
        OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT.with_suffix(".prom.tmp")
        tmp.write_text(text)
        os.replace(tmp, OUT)
        print(f"openbao-inventory: OK {len(live)} entries")
        return 0
    except Exception as exc:  # noqa: BLE001 -- report and leave the previous file in place
        print(f"openbao-inventory: FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if client.token:
            try:
                client.call("POST", "auth/token/revoke-self")
            except Exception:  # noqa: BLE001 -- token expires on its own
                pass


if __name__ == "__main__":
    sys.exit(main())
