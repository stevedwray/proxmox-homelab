#!/usr/bin/env python3
"""Compare what the SOPS and OpenBao backends export for one profile.

  scripts/secrets_parity_check.py pve
  scripts/secrets_parity_check.py pve-test-vm

Runs the profile's wrapper twice with `printenv -0` (read-only in
with-secrets-prod's classifier), once with SECRETS_BACKEND=sops and once
with SECRETS_BACKEND=openbao, and compares SHA-256 digests of every field
the manifest lists for that profile. Prints field NAMES and MATCH/MISMATCH/
MISSING only -- never values. Exit 0 only if every field matches.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "secrets" / "manifest.json"
PROD_WRAPPERS = {
    "pve": "with-secrets-prod",
    "pve-framework": "with-secrets-prod-framework",
    "pve-tiny": "with-secrets-prod-tiny",
}


def exported(profile: str, backend: str) -> dict[str, str]:
    env = dict(os.environ, SECRETS_BACKEND=backend)
    if profile in PROD_WRAPPERS:
        cmd = [str(REPO_ROOT / PROD_WRAPPERS[profile]), "printenv", "-0"]
    else:
        env["PVE_ENV"] = profile
        cmd = [str(REPO_ROOT / "with-secrets"), "printenv", "-0"]
    out = subprocess.run(cmd, check=True, capture_output=True, env=env, cwd=REPO_ROOT).stdout
    pairs = (item.split(b"=", 1) for item in out.split(b"\0") if b"=" in item)
    return {k.decode(): hashlib.sha256(v).hexdigest() for k, v in pairs}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    profile = argv[0]
    manifest = json.loads(MANIFEST.read_text())
    if profile not in manifest["profiles"] or profile.startswith("ci-"):
        print(f"ERROR: '{profile}' is not a wrapper profile in the manifest", file=sys.stderr)
        return 2
    fields = []
    for entry in manifest["profiles"][profile]["entries"]:
        for field in manifest["entries"][entry]["fields"]:
            if field not in fields:
                fields.append(field)
    sops = exported(profile, "sops")
    bao = exported(profile, "openbao")
    bad = 0
    for field in fields:
        if field not in sops or field not in bao:
            state = f"MISSING(sops={'y' if field in sops else 'n'},openbao={'y' if field in bao else 'n'})"
        else:
            state = "MATCH" if sops[field] == bao[field] else "MISMATCH"
        bad += state != "MATCH"
        print(f"{state:9} {field}")
    print(f"{profile}: {len(fields) - bad}/{len(fields)} fields match")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
