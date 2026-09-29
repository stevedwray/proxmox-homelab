#!/usr/bin/env python3
"""One-time, operator-run generation of GVM fleet scan credentials.

  bao login -method=oidc -no-store
  export BAO_TOKEN=<the token bao login printed>
  scripts/gvm_scan_credentials_bootstrap.py --all
  # or, for just the stacks not yet done:
  scripts/gvm_scan_credentials_bootstrap.py harbor-stack netbox-stack

For each named stack: generates a fresh ed25519 SSH keypair and a random
32-char sudo password, then writes all three values to OpenBao at
services/greenbone/scan-hosts/<stack> via scripts/openbao_write.py (piped
via stdin, one value per line -- openbao_write.py reads stdin
non-interactively when it isn't a TTY). The private key is base64-encoded
before writing (openbao_write.py's stdin protocol is one value per LINE
via readline(), confirmed 2026-09-29 by reading its source -- a raw
multi-line PEM would silently truncate to its first line otherwise);
gvm_scan_host_secret.py decodes it back at the one place it's read, so
every other consumer still sees the real PEM.

Requires secrets/manifest.json to already declare, for each named stack,
an entry at services/greenbone/scan-hosts/<stack> listing fields
GVM_SCAN_SSH_PRIVATE_KEY, GVM_SCAN_SSH_PUBLIC_KEY, GVM_SCAN_SUDO_PASSWORD
-- see docs/lxc-scan-and-monitoring-rollout/plan.md's gvm-03 (a prose
step, not automatable in this session -- needs secrets/ access).

This script never logs in to OpenBao itself and never touches BAO_TOKEN
beyond reading it from the environment to pass through to
openbao_write.py's subprocess -- the OIDC login stays entirely the
operator's own, one-time action.

Running this twice for the same stack ROTATES that stack's credentials
(openbao_write.py always writes a fresh KV version) -- only pass stacks
that don't already have a working entry, unless a deliberate rotation is
intended.
"""

from __future__ import annotations

import argparse
import base64
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from gvm_fleet_targets_generate import IN_SCOPE_STACKS  # noqa: E402 -- same canonical list, not re-derived


def generate_keypair() -> tuple[str, str]:
    """Returns (private_key_pem, public_key_openssh) for a fresh ed25519
    keypair. Shells out to ssh-keygen (universally available, matches how
    every SSH key in this lab is normally created) rather than adding a
    new crypto library dependency for one call site."""
    with tempfile.TemporaryDirectory() as tmp:
        key_path = Path(tmp) / "key"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "gvm-scan", "-f", str(key_path)],
            check=True, capture_output=True,
        )
        return key_path.read_text(encoding="utf-8"), (key_path.with_suffix(".pub")).read_text(encoding="utf-8")


def generate_sudo_password() -> str:
    return secrets.token_urlsafe(24)


def write_to_openbao(stack: str, private_key: str, public_key: str, sudo_password: str) -> bool:
    """openbao_write.py reads exactly one stdin *line* per field
    (sys.stdin.readline().rstrip("\\n"), confirmed by reading its source
    2026-09-29) -- a multi-line SSH private key PEM would silently
    truncate to its first line if piped in as-is. Base64-encode it into a
    single line for the write; gvm_scan_host_secret.py decodes it back at
    the one place it's read, so every downstream consumer
    (gvm_fleet_targets_generate.py, setup_credentials.py) still sees the
    real PEM and never has to know base64 was involved. The public key
    and sudo password are naturally single-line already (SSH pubkey
    format; a token has no embedded newlines) so only the private key
    needs this treatment."""
    entry = f"services/greenbone/scan-hosts/{stack}"
    encoded_key = base64.b64encode(private_key.encode("utf-8")).decode("ascii")
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "openbao_write.py"), entry,
         "GVM_SCAN_SSH_PRIVATE_KEY", "GVM_SCAN_SSH_PUBLIC_KEY", "GVM_SCAN_SUDO_PASSWORD"],
        input=f"{encoded_key}\n{public_key.strip()}\n{sudo_password}\n",
        text=True, capture_output=True,
    )
    if proc.returncode != 0:
        print(f"ERROR writing {stack!r}: {proc.stderr.strip()}", file=sys.stderr)
        return False
    print(f"wrote {entry}")
    return True


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stacks", nargs="*", help="Stack names to generate credentials for")
    parser.add_argument("--all", action="store_true", help=f"Use the full in-scope list ({len(IN_SCOPE_STACKS)} stacks)")
    args = parser.parse_args(argv)

    if args.all:
        stacks = IN_SCOPE_STACKS
    elif args.stacks:
        unknown = [s for s in args.stacks if s not in IN_SCOPE_STACKS]
        if unknown:
            print(f"ERROR: not in the in-scope list: {', '.join(unknown)}", file=sys.stderr)
            return 1
        stacks = args.stacks
    else:
        parser.print_help()
        return 2

    succeeded = failed = 0
    for stack in stacks:
        print(f"-- {stack} --")
        private_key, public_key = generate_keypair()
        sudo_password = generate_sudo_password()
        if write_to_openbao(stack, private_key, public_key, sudo_password):
            succeeded += 1
        else:
            failed += 1

    print(f"done: {succeeded} succeeded, {failed} failed (of {len(stacks)})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
