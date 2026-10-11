#!/usr/bin/env python3
"""One-time, operator-run generation of GVM scan credentials.

  bao login -method=oidc -no-store
  export BAO_TOKEN=<the token bao login printed>
  scripts/gvm_scan_credentials_bootstrap.py --all
  # or, for just the hosts not yet done:
  scripts/gvm_scan_credentials_bootstrap.py host-pve cse-panel-stack

For each named scan host: generates a fresh ed25519 SSH keypair and writes
both halves to OpenBao at services/greenbone/scan-hosts/<name> via
scripts/openbao_write.py (piped via stdin, one value per line --
openbao_write.py reads stdin non-interactively when it isn't a TTY). The
private key is base64-encoded before writing (openbao_write.py's stdin
protocol is one value per LINE via readline() -- a raw multi-line PEM
would silently truncate to its first line otherwise);
gvm_scan_host_secret.py decodes it back at the one place it's read.

No sudo password is generated any more (docs/gvm-coverage-cleanup/plan.md):
GVM's elevate-privileges feature is su-based, never sudo, so the gvm-scan
account is SSH-key-only and unprivileged.

Requires secrets/manifest.json to already declare, for each named host, an
entry at services/greenbone/scan-hosts/<name> listing fields
GVM_SCAN_SSH_PRIVATE_KEY and GVM_SCAN_SSH_PUBLIC_KEY.

This script never logs in to OpenBao itself and never touches BAO_TOKEN
beyond reading it from the environment to pass through to
openbao_write.py's subprocess -- the OIDC login stays entirely the
operator's own, one-time action.

Running this twice for the same host ROTATES that host's credentials
(openbao_write.py always writes a fresh KV version). setup_credentials.py
detects the changed key on the next greenbone-stack deploy and rebuilds
that host's GVM credential/target/task, and deploy-gvm-scan-accounts.yml
must be re-run so the host's authorized_keys matches.
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

from gvm_fleet_targets_generate import ALL_SCAN_HOST_NAMES  # noqa: E402 -- same canonical list, not re-derived


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
    entry = f"services/greenbone/scan-hosts/{name}"
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
    parser.add_argument("names", nargs="*", help="Scan host names to generate credentials for")
    parser.add_argument("--all", action="store_true", help=f"Use the full list ({len(ALL_SCAN_HOST_NAMES)} hosts)")
    args = parser.parse_args(argv)

    if args.all:
        names = ALL_SCAN_HOST_NAMES
    elif args.names:
        unknown = [n for n in args.names if n not in ALL_SCAN_HOST_NAMES]
        if unknown:
            print(f"ERROR: not in the scan host list: {', '.join(unknown)}", file=sys.stderr)
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
