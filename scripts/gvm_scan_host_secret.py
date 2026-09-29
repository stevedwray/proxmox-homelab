#!/usr/bin/env python3
"""Read one stack's GVM scan credentials from OpenBao, print as JSON.

  gvm_scan_host_secret.py --stack harbor-stack

Per-host secrets don't fit secrets_env.py's flat per-*profile* env-var
model (one profile can't hold 36 different values under one field name),
so this is a small, separate, single-purpose reader -- not a change to the
shared with-secrets loader. Reuses secrets_env.py's already-proven
OpenBaoClient/login() (same AppRole/env-var conventions, same read-only
deploy-<node> role every other secret read in this repo already uses).

Entry path: services/greenbone/scan-hosts/<stack>
Fields: GVM_SCAN_SSH_PRIVATE_KEY, GVM_SCAN_SSH_PUBLIC_KEY,
        GVM_SCAN_SUDO_PASSWORD

On success, prints one line of JSON to stdout (the three fields as a flat
dict) and exits 0. On any failure, prints nothing to stdout, prints
"ERROR: <message>" to stderr, and exits 1 -- callers may safely treat any
stdout output as valid JSON without checking exit status first, though
checking it too is still correct.

See docs/lxc-scan-and-monitoring-rollout/plan.md (gvm-02) for the design.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from secrets_env import (  # noqa: E402 -- sys.path must be set first
    DEFAULT_CACERT,
    DEFAULT_MANIFEST,
    OpenBaoClient,
    SecretsError,
    load_manifest,
    login,
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", required=True, help="Stack name, e.g. harbor-stack")
    parser.add_argument("--profile", default=os.environ.get("PVE_ENV", "pve"))
    args = parser.parse_args(argv)

    addr = os.environ.get("OPENBAO_ADDR", "").strip()
    if not addr:
        ip = os.environ.get("LAB_IP_OPENBAO", "").strip()
        if not ip:
            print("ERROR: neither OPENBAO_ADDR nor LAB_IP_OPENBAO is set", file=sys.stderr)
            return 1
        addr = f"https://{ip}:8200"
    cacert = os.environ.get("OPENBAO_CACERT", str(DEFAULT_CACERT))
    cred_dir = Path(os.environ.get("OPENBAO_CRED_DIR", str(Path.home() / ".config" / "openbao")))

    try:
        manifest = load_manifest(DEFAULT_MANIFEST)
        profiles = manifest.get("profiles", {})
        if args.profile not in profiles:
            raise SecretsError(f"unknown profile '{args.profile}'; known: {', '.join(sorted(profiles))}")
        prof = profiles[args.profile]

        client = OpenBaoClient(addr, cacert)
        try:
            login(client, prof, cred_dir)
            data = client.read_kv(f"services/greenbone/scan-hosts/{args.stack}")
        finally:
            client.revoke_self()
    except SecretsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
