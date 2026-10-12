#!/usr/bin/env python3
"""One-time, operator-run generation of GVM scan credentials -- one
shared keypair per VLAN/zone (operator decision 2026-10-12,
docs/gvm-coverage-cleanup/).

  export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
  export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
  LAB_IP_OPENBAO=192.168.20.16 scripts/gvm_scan_credentials_bootstrap.py --all
  # or, for just some zones:
  LAB_IP_OPENBAO=192.168.20.16 scripts/gvm_scan_credentials_bootstrap.py lan mgmt_seg

For each named zone: generates a fresh ed25519 SSH keypair and writes
both halves to OpenBao at services/greenbone/scan-zones/<zone> via
scripts/openbao_write.py (piped via stdin, one value per line --
openbao_write.py reads stdin non-interactively when it isn't a TTY). The
private key is base64-encoded before writing (openbao_write.py's stdin
protocol is one value per LINE via readline() -- a raw multi-line PEM
would silently truncate to its first line otherwise);
gvm_scan_host_secret.py decodes it back at the one place it's read.

No sudo password is generated any more (docs/gvm-coverage-cleanup/plan.md):
GVM's elevate-privileges feature is su-based, never sudo, so the gvm-scan
account is SSH-key-only and unprivileged.

Requires secrets/manifest.json to already declare, for each named zone, an
entry at services/greenbone/scan-zones/<zone> listing fields
GVM_SCAN_SSH_PRIVATE_KEY and GVM_SCAN_SSH_PUBLIC_KEY.

This script never logs in to OpenBao itself and never touches BAO_TOKEN
beyond reading it from the environment to pass through to
openbao_write.py's subprocess -- the OIDC login stays entirely the
operator's own, one-time action.

Running this twice for the same zone ROTATES that zone's key (openbao_write.py
always writes a fresh KV version). Then re-run deploy-gvm-scan-accounts.yml
(--limit to that zone's hosts) so their authorized_keys match, and redeploy
greenbone-stack's credential program, which detects the changed key and
rebuilds that zone's GVM credential/target/task.
"""

from __future__ import annotations

import argparse
import base64
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from gvm_fleet_targets_generate import all_scan_zones  # noqa: E402 -- same canonical list, not re-derived


def generate_keypair() -> tuple[str, str]:
    """Returns (private_key_pem, public_key_openssh) for a fresh ed25519
    keypair via ssh-keygen (matches how every SSH key in this lab is
    normally created) rather than a new crypto library dependency."""
    with tempfile.TemporaryDirectory() as tmp:
        key_path = Path(tmp) / "key"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "gvm-scan", "-f", str(key_path)],
            check=True, capture_output=True,
        )
        return key_path.read_text(encoding="utf-8"), (key_path.with_suffix(".pub")).read_text(encoding="utf-8")


def write_to_openbao(name: str, private_key: str, public_key: str) -> bool:
    entry = f"services/greenbone/scan-zones/{name}"
    encoded_key = base64.b64encode(private_key.encode("utf-8")).decode("ascii")
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "openbao_write.py"), entry,
         "GVM_SCAN_SSH_PRIVATE_KEY", "GVM_SCAN_SSH_PUBLIC_KEY"],
        input=f"{encoded_key}\n{public_key.strip()}\n",
        text=True, capture_output=True,
    )
    if proc.returncode != 0:
        print(f"ERROR writing {name!r}: {proc.stderr.strip()}", file=sys.stderr)
        return False
    print(f"wrote {entry}")
    return True


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    zones = all_scan_zones()
    parser.add_argument("names", nargs="*", help="Zone names to generate credentials for")
    parser.add_argument("--all", action="store_true", help=f"Use every zone ({len(zones)} zones)")
    args = parser.parse_args(argv)

    if args.all:
        names = zones
    elif args.names:
        unknown = [n for n in args.names if n not in zones]
        if unknown:
            print(f"ERROR: not a scan zone: {', '.join(unknown)}", file=sys.stderr)
            return 1
        names = args.names
    else:
        parser.print_help()
        return 2

    succeeded = failed = 0
    for name in names:
        print(f"-- {name} --")
        private_key, public_key = generate_keypair()
        if write_to_openbao(name, private_key, public_key):
            succeeded += 1
        else:
            failed += 1

    print(f"done: {succeeded} succeeded, {failed} failed (of {len(names)})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
