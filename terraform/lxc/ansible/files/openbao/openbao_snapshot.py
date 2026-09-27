#!/usr/bin/env python3
"""Take an OpenBao Raft snapshot, copy it to the NAS mount, prune, export metrics.

Runs ON the OpenBao LXC as root, from openbao-snapshot@<kind>.service:
  openbao_snapshot.py nightly     # nightly timer
  openbao_snapshot.py postwrite   # triggered by scripts/openbao_write.py

Auth: AppRole "snapshot" (policy: read+sudo on sys/storage/raft/snapshot only),
credentials in /etc/openbao-snapshot/{role-id,secret-id} (root 0600).
Destination: /srv/openbao-snapshots (host bind mount of
/mnt/nas-backup/openbao-snapshots on pve). Retention: design doc 27.0.1.
Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ADDR = "https://192.168.20.16:8200"
CACERT = "/usr/local/share/ca-certificates/homelab-root.crt"
CRED_DIR = Path("/etc/openbao-snapshot")
DEST = Path("/srv/openbao-snapshots")
TEXTFILE_DIR = Path("/var/lib/node_exporter/textfile")
KINDS = ("nightly", "postwrite")
NAME_RE = re.compile(r"^openbao-(\d{8}T\d{6}Z)-(nightly|postwrite)\.snap$")
DAY = 86400
KEEP_NEWEST = 7


def parse_name(name: str) -> tuple[datetime, str] | None:
    m = NAME_RE.match(name)
    if not m:
        return None
    ts = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return ts, m.group(2)


def keep_by_policy(ts: datetime, kind: str, now: datetime) -> bool:
    age_days = (now - ts).total_seconds() / DAY
    if kind == "postwrite":
        return age_days <= 90
    if age_days <= 14:
        return True
    if ts.weekday() == 6 and age_days <= 56:  # Sunday nightly -> weekly tier, 8 weeks
        return True
    if ts.day == 1 and age_days <= 365:  # 1st-of-month nightly -> monthly tier, 12 months
        return True
    return False


def prune_plan(names: list[str], now: datetime) -> list[str]:
    """Return the snapshot file names to delete. Never deletes the newest KEEP_NEWEST."""
    parsed = sorted(
        ((parse_name(n), n) for n in names if parse_name(n) is not None),
        key=lambda item: item[0][0],
        reverse=True,
    )
    protected = {n for _, n in parsed[:KEEP_NEWEST]}
    return sorted(
        n for (ts, kind), n in parsed if n not in protected and not keep_by_policy(ts, kind, now)
    )


def _request(opener, method: str, path: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{ADDR}/v1/{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Vault-Token", token)
    return opener.open(req, timeout=120)


def write_metrics(kind: str, success: bool, now: float) -> None:
    TEXTFILE_DIR.mkdir(parents=True, exist_ok=True)
    path = TEXTFILE_DIR / f"openbao_snapshot_{kind}.prom"
    last_success = None
    if path.exists():
        m = re.search(r"^openbao_snapshot_last_success_timestamp_seconds\{[^}]*\} (\S+)$", path.read_text(), re.M)
        if m:
            last_success = m.group(1)
    if success:
        last_success = f"{now:.0f}"
    lines = [
        "# HELP openbao_snapshot_last_run_success 1 if the most recent snapshot run of this kind succeeded.",
        "# TYPE openbao_snapshot_last_run_success gauge",
        f'openbao_snapshot_last_run_success{{kind="{kind}"}} {1 if success else 0}',
    ]
    if last_success is not None:
        lines += [
            "# HELP openbao_snapshot_last_success_timestamp_seconds Unix time of the last successful snapshot of this kind.",
            "# TYPE openbao_snapshot_last_success_timestamp_seconds gauge",
            f'openbao_snapshot_last_success_timestamp_seconds{{kind="{kind}"}} {last_success}',
        ]
    tmp = path.with_suffix(".prom.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, path)


def take_snapshot(kind: str) -> Path:
    ctx = ssl.create_default_context(cafile=CACERT)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    role_id = (CRED_DIR / "role-id").read_text().strip()
    secret_id = (CRED_DIR / "secret-id").read_text().strip()
    with _request(opener, "POST", "auth/approle/login", body={"role_id": role_id, "secret_id": secret_id}) as resp:
        token = json.loads(resp.read())["auth"]["client_token"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = DEST / f"openbao-{stamp}-{kind}.snap"
    partial = DEST / f".{final.name}.partial"
    try:
        with _request(opener, "GET", "sys/storage/raft/snapshot", token=token) as resp, open(partial, "wb") as out:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if partial.stat().st_size == 0:
            raise RuntimeError("snapshot download was empty")
        os.replace(partial, final)
    finally:
        if partial.exists():
            partial.unlink()
        try:
            _request(opener, "POST", "auth/token/revoke-self", token=token).close()
        except Exception:  # noqa: BLE001 -- token expires on its own (5m TTL)
            pass
    return final


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in KINDS:
        print(f"usage: openbao_snapshot.py {{{'|'.join(KINDS)}}}", file=sys.stderr)
        return 2
    kind = argv[0]
    try:
        if not DEST.is_dir():
            raise RuntimeError(f"{DEST} is not mounted/present")
        final = take_snapshot(kind)
        deleted = prune_plan([p.name for p in DEST.iterdir()], datetime.now(timezone.utc))
        for name in deleted:
            (DEST / name).unlink()
        write_metrics(kind, True, time.time())
        print(f"openbao-snapshot: OK {final.name} ({final.stat().st_size} bytes); pruned {len(deleted)}")
        return 0
    except Exception as exc:  # noqa: BLE001 -- any failure must be reported and exported
        write_metrics(kind, False, time.time())
        print(f"openbao-snapshot: FAILED ({kind}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
