#!/usr/bin/env python3
"""Read a GVM scan credential from OpenBao, print as JSON.

  gvm_scan_host_secret.py --stack harbor-stack   # that host's zone key
  gvm_scan_host_secret.py --zone infra_seg       # a zone's key directly

Credentials are per VLAN/zone (operator decision 2026-10-12,
docs/gvm-coverage-cleanup/): every scan host in a zone shares one gvm-scan
keypair. --stack resolves the host to its zone via
gvm_fleet_targets_generate.zone_for_name(), so every deploy-*.yml that
already calls this with --stack <name> gets its zone's key unchanged. A
small, separate reader rather than a change to the shared with-secrets
loader; reuses secrets_env.py's OpenBaoClient/login() (same read-only
deploy-<node> AppRole as every other secret read in this repo).

Entry path: services/greenbone/scan-zones/<zone>
Fields: GVM_SCAN_SSH_PRIVATE_KEY, GVM_SCAN_SSH_PUBLIC_KEY

GVM_SCAN_SSH_PRIVATE_KEY is stored base64-encoded (see
gvm_scan_credentials_bootstrap.py's docstring -- openbao_write.py's stdin
protocol is one value per line, which a multi-line PEM key doesn't fit).
This is the one place that gets decoded back to the real PEM -- every
downstream consumer (gvm_fleet_targets_generate.py, setup_credentials.py)
sees the real key, never the base64 form.

On success, prints one line of JSON to stdout (the fields as a flat
dict, private key already decoded) and exits 0. On any failure, prints
nothing to stdout, prints "ERROR: <message>" to stderr, and exits 1 --
callers may safely treat any stdout output as valid JSON without checking
exit status first, though checking it too is still correct.

Originally docs/lxc-scan-and-monitoring-rollout/plan.md (gvm-02).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gvm_fleet_targets_generate import zone_for_name  # noqa: E402 -- sys.path must be set first
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
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--stack", help="Scan host name, e.g. harbor-stack or host-pve; resolved to its zone")
    target.add_argument("--zone", help="Zone name, e.g. infra_seg")
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

    zone = args.zone
    if args.stack:
        zone = zone_for_name(args.stack)
        if zone is None:
            print(f"ERROR: {args.stack!r} is not a known scan host (IN_SCOPE_STACKS/EXTRA_HOSTS) "
                  f"or has no zone", file=sys.stderr)
            return 1

    try:
        manifest = load_manifest(DEFAULT_MANIFEST)
        profiles = manifest.get("profiles", {})
        if args.profile not in profiles:
            raise SecretsError(f"unknown profile '{args.profile}'; known: {', '.join(sorted(profiles))}")
        prof = profiles[args.profile]

        client = OpenBaoClient(addr, cacert)
        try:
            login(client, prof, cred_dir)
            data = client.read_kv(f"services/greenbone/scan-zones/{zone}")
        finally:
            client.revoke_self()

        if "GVM_SCAN_SSH_PRIVATE_KEY" in data:
            try:
                data["GVM_SCAN_SSH_PRIVATE_KEY"] = base64.b64decode(
                    data["GVM_SCAN_SSH_PRIVATE_KEY"], validate=True,
                ).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError) as exc:
                raise SecretsError(
                    f"GVM_SCAN_SSH_PRIVATE_KEY for zone {zone!r} is not valid base64 "
                    f"-- was it written by something other than "
                    f"gvm_scan_credentials_bootstrap.py? ({exc})"
                ) from exc
    except SecretsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
