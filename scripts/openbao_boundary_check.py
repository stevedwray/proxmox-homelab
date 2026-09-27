#!/usr/bin/env python3
"""Prove the OpenBao access boundaries (design doc 12-13, 31) for every
deploy AppRole whose credentials are installed on this workstation.

  LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_boundary_check.py

For each ~/.config/openbao/deploy-*.role-id it logs in and checks:
  - it CAN read every entry of each manifest profile that uses the role;
  - it CANNOT read any other node's hosts/* entry (expects 403);
  - it CANNOT write, even to an entry it can read (expects 403).
Needs at least one entry to exist to test reads, so run after the cutover
import; before that it still proves the deny rules. Prints only paths and
PASS/FAIL. Exit 0 only if every check passes.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "secrets" / "manifest.json"
CACERT = REPO_ROOT / "certs" / "homelab-root.crt"


def main() -> int:
    ip = os.environ.get("LAB_IP_OPENBAO", "").strip()
    if not ip:
        print("ERROR: LAB_IP_OPENBAO is not set", file=sys.stderr)
        return 2
    addr = f"https://{ip}:8200"
    cred_dir = Path(os.environ.get("OPENBAO_CRED_DIR", "") or Path.home() / ".config" / "openbao")
    ctx = ssl.create_default_context(cafile=str(CACERT))
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    manifest = json.loads(MANIFEST.read_text())
    hosts = sorted(e for e in manifest["entries"] if e.startswith("hosts/"))

    def call(method, path, token=None, body=None) -> tuple[int, dict]:
        req = urllib.request.Request(f"{addr}/v1/{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("X-Vault-Token", token)
        try:
            with opener.open(req, timeout=15) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            return exc.code, {}

    failures = 0
    roles = sorted(p.name[: -len(".role-id")] for p in cred_dir.glob("deploy-*.role-id"))
    if not roles:
        print(f"ERROR: no deploy-*.role-id files in {cred_dir}", file=sys.stderr)
        return 2
    for role in roles:
        status, resp = call("POST", "auth/approle/login", body={
            "role_id": (cred_dir / f"{role}.role-id").read_text().strip(),
            "secret_id": (cred_dir / f"{role}.secret-id").read_text().strip(),
        })
        if status != 200:
            print(f"FAIL {role}: login HTTP {status}")
            failures += 1
            continue
        token = resp["auth"]["client_token"]
        allowed = set()
        for prof in manifest["profiles"].values():
            if prof.get("role") == role:
                allowed.update(prof["entries"])
        for entry in sorted(allowed):
            status, _ = call("GET", f"kv/data/{entry}", token)
            ok = status in (200, 404)  # 404 = allowed but not imported yet
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'} {role} read  {entry}  (HTTP {status}, want 200/404)")
        for entry in hosts:
            if entry in allowed:
                continue
            status, _ = call("GET", f"kv/data/{entry}", token)
            ok = status == 403
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'} {role} deny  {entry}  (HTTP {status}, want 403)")
        target = sorted(allowed)[0]
        status, _ = call("POST", f"kv/data/{target}", token, {"data": {"BOUNDARY_CHECK": "x"}})
        ok = status == 403
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'} {role} write {target}  (HTTP {status}, want 403)")
        call("POST", "auth/token/revoke-self", token)
    print(f"boundary check: {'OK' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
