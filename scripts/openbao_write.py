#!/usr/bin/env python3
"""Write (create or rotate) one secret field in OpenBao, then snapshot.

  BAO_TOKEN=<write token> scripts/openbao_write.py services/graylog GRAYLOG_ROOT_PASSWORD
  BAO_TOKEN=<write token> scripts/openbao_write.py services/graylog GRAYLOG_ROOT_PASSWORD GRAYLOG_ROOT_PASSWORD_SHA2

Prompts for each value (hidden); if stdin is not a TTY, reads one value per
line instead. All fields named on one invocation are written in a single
KV v2 version (check-and-set against the version just read), so values that
rotate together (a password and its hash) change together.

Requires an explicit write token in BAO_TOKEN. It never reads ~/.vault-token
or any token helper -- that is what keeps agent sessions, which only ever get
the read-only deploy AppRoles through ./with-secrets, from writing secrets
(design doc 13.1).

After a successful write it triggers the post-write snapshot on the OpenBao
LXC (ssh root@LAB_IP_OPENBAO systemctl start openbao-snapshot@postwrite) and
exits non-zero with "WRITE OK, SNAPSHOT FAILED" if that fails.
Remember to add any NEW field name to secrets/manifest.json on your branch --
the loader only exports fields the manifest lists.
"""

from __future__ import annotations

import getpass
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACERT = REPO_ROOT / "certs" / "homelab-root.crt"
MANIFEST = REPO_ROOT / "secrets" / "manifest.json"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    entry, fields = argv[0].strip("/"), argv[1:]
    token = os.environ.get("BAO_TOKEN", "").strip()
    if not token:
        print("ERROR: BAO_TOKEN is not set. Log in explicitly (bao login -method=oidc -no-store) "
              "and export the token in this shell only.", file=sys.stderr)
        return 1
    ip = os.environ.get("LAB_IP_OPENBAO", "").strip()
    addr = os.environ.get("OPENBAO_ADDR", "").strip() or (f"https://{ip}:8200" if ip else "")
    if not addr or not ip:
        print("ERROR: LAB_IP_OPENBAO is not set (source .env.pve or run from ./with-secrets-prod's env)", file=sys.stderr)
        return 1

    manifest = json.loads(MANIFEST.read_text())
    listed = set(manifest["entries"].get(entry, {}).get("fields", []))
    for field in fields:
        if field not in listed:
            print(f"NOTE: {entry}:{field} is not in secrets/manifest.json yet -- add it on your branch "
                  "or the loader will not export it.", file=sys.stderr)

    values = {}
    for field in fields:
        if sys.stdin.isatty():
            first = getpass.getpass(f"{entry}:{field} value: ")
            if first != getpass.getpass(f"{entry}:{field} again: "):
                print("ERROR: values did not match; nothing written", file=sys.stderr)
                return 1
        else:
            first = sys.stdin.readline().rstrip("\n")
        if first == "":
            print(f"ERROR: empty value for {field}; nothing written", file=sys.stderr)
            return 1
        values[field] = first

    ctx = ssl.create_default_context(cafile=str(CACERT))
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(f"{addr}/v1/{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("X-Vault-Token", token)
        req.add_header("Content-Type", "application/json")
        try:
            with opener.open(req, timeout=15) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            return exc.code, {}

    status, current = call("GET", f"kv/data/{entry}")
    if status == 200:
        data = dict(current["data"]["data"])
        cas = current["data"]["metadata"]["version"]
    elif status == 404:
        data, cas = {}, 0
    else:
        print(f"ERROR: reading {entry} returned HTTP {status}; nothing written", file=sys.stderr)
        return 1
    data.update(values)
    status, resp = call("POST", f"kv/data/{entry}", {"options": {"cas": cas}, "data": data})
    if status not in (200, 204):
        print(f"ERROR: write to {entry} returned HTTP {status} (concurrent change? re-run)", file=sys.stderr)
        return 1
    version = (resp.get("data") or {}).get("version", "?")
    print(f"WRITE OK: {entry} now at version {version} ({', '.join(fields)})")

    snap = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", f"root@{ip}", "systemctl", "start", "openbao-snapshot@postwrite.service"],
        capture_output=True, text=True,
    )
    if snap.returncode != 0:
        print("WRITE OK, SNAPSHOT FAILED -- run it by hand: "
              f"ssh root@{ip} systemctl start openbao-snapshot@postwrite.service\n{snap.stderr.strip()}",
              file=sys.stderr)
        return 3
    print("SNAPSHOT OK (postwrite)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
