#!/usr/bin/env python3
"""Generate the GVM fleet-targets bind-mount directory for
setup_credentials.py's load_fleet_targets() (docs/lxc-scan-and-monitoring-
rollout/plan.md, gvm-07).

  gvm_fleet_targets_generate.py --out-dir /path/to/tempdir/fleet

For each in-scope stack (see IN_SCOPE_STACKS below -- the operator-
confirmed 2026-09-29 list, corrected during execution to also exclude
pentagi-stack [CTs confirmed destroyed on pve 2026-09-28] and
pentagi-upstream-control [a vanilla-upstream comparison baseline, not a
real production workload, same spirit as the cse-*/harness-target
exclusions]): resolves its static IP from its own stack.yaml (some stacks
hardcode a literal ip_address, others template it as "${lab_ip_X}/24" and
need the matching LAB_IP_X env var -- both forms are real and in use,
confirmed live 2026-09-29 by reading stack.yaml files directly, not
assumed), reads that stack's GVM scan credentials via
gvm_scan_host_secret.py (skipping with a warning, not failing the whole
run, if that stack's OpenBao entry doesn't exist yet -- e.g. gvm-04's
bootstrap hasn't been run for it), and writes:
  <out-dir>/targets.json           -- [{"name": str, "host": str, "zone": str}, ...]
  <out-dir>/<name>.key              -- SSH private key
  <out-dir>/<name>.sudopass         -- plaintext sudo password

Run from deploy-greenbone-stack.yml via delegate_to: localhost, same
process-boundary shape as gvm_scan_host_secret.py itself; requires the
same OPENBAO_ADDR/OPENBAO_CACERT/OPENBAO_CRED_DIR/LAB_IP_OPENBAO env vars
(the with-secrets-prod wrapper already exports LAB_IP_OPENBAO; the others
have working defaults, see gvm_scan_host_secret.py).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Operator-confirmed scope (2026-09-29): the real production stacks on
# pve, corrected twice during execution:
#   1. Dropped pentagi-stack (CTs confirmed destroyed) and
#      pentagi-upstream-control (comparison baseline, not real
#      production) -- both were only in the plan's original "~36"
#      estimate because that estimate came from a directory listing
#      (terraform/lxc/environments/pve/), not live reality.
#   2. That same directory turned out to be an UNRELIABLE enumeration --
#      confirmed live via a read-only Proxmox API call (GET
#      /nodes/pve/lxc) that newt-connector, nextcloud-stack,
#      pterodactyl-lab, media-stack-lab, torrent-stack-lab, and
#      openbao-stack are all real, running production LXCs on pve that
#      simply don't have a terraform/lxc/environments/pve/<name>/
#      directory (nextcloud-stack, for one, has its terragrunt.hcl
#      directly under terraform/lxc/stacks/nextcloud-stack/ instead --
#      apparently a newer, different layout convention than the older
#      stacks use). Added below once each was confirmed to have both a
#      real deploy-*.yml playbook AND a resolvable stack.yaml IP.
#
# Known, deliberately NOT included despite being live on pve: media-stack
# (legacy, being replaced by media-stack-lab -- same "-legacy" rollback
# pattern as gaming-stack-legacy), management-stack, omada-controller,
# and proxmox-backup-server (confirmed live via the same Proxmox API
# call, but none of the three has ANY deploy-*.yml playbook in this repo
# to hook the gvm_scan_account/wazuh_agent rollout into -- not
# Ansible-managed here at all, a real gap that needs its own playbook
# work before it can join this list, not something this rollout can
# silently paper over).
#
# This list is data, not a mechanical filter -- re-verify it by hand if
# the fleet changes, same as gvm_scan_credentials_bootstrap.py's own
# exclusion list (which imports this list directly, not a separate copy).
IN_SCOPE_STACKS = [
    "ai-services-stack",
    "apt-cacher-stack",
    "authentik-stack",
    "ci-runner-01",
    "gaming-stack-lab",
    "graylog-stack",
    "greenbone-stack",
    "harbor-stack",
    "mcp-utility-stack",
    "media-stack-lab",
    "monitoring-stack",
    "netbox-stack",
    "newt-connector",
    "nextcloud-stack",
    "opensearch-stack",
    "openbao-stack",
    "pangolin-proxy",
    "portainer-stack",
    "proxy-stack",
    "pterodactyl-lab",
    "secpipe-stack",
    "step-ca-stack",
    "technitium-stack",
    "torrent-stack-lab",
    "wazuh-stack",
]

_TEMPLATE_RE = re.compile(r"^\$\{lab_ip_([a-z0-9_]+)\}/\d+$")
_LITERAL_RE = re.compile(r"^(\d+\.\d+\.\d+\.\d+)/\d+$")


def resolve_stack_zone(stack: str) -> str | None:
    """Reads terraform/lxc/stacks/<stack>/stack.yaml's zone field (used by
    setup_credentials.py to group fleet scan tasks by VLAN via a per-zone
    GVM Schedule + Tag -- see docs/lxc-scan-and-monitoring-rollout/plan.md).
    Handles both the plain "zone: <name>" form and the nested
    "network: { zone: <name> }" form seen live (nextcloud-stack). Returns
    None, not a guess, if neither form matches -- callers must skip."""
    stack_yaml = REPO_ROOT / "terraform" / "lxc" / "stacks" / stack / "stack.yaml"
    if not stack_yaml.exists():
        return None
    for line in stack_yaml.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("zone:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
        zone_match = re.search(r"zone:\s*(\w+)", stripped)
        if zone_match:
            return zone_match.group(1)
    return None


def resolve_stack_ip(stack: str) -> str | None:
    """Reads terraform/lxc/stacks/<stack>/stack.yaml's ip_address field.
    Handles both forms seen live: a literal IP/prefix, or a
    "${lab_ip_X}/prefix" template resolved via env var LAB_IP_X (upper).
    Returns None (not a guess) if the field is missing or in a form this
    function doesn't recognize -- callers must skip, not invent an IP."""
    stack_yaml = REPO_ROOT / "terraform" / "lxc" / "stacks" / stack / "stack.yaml"
    if not stack_yaml.exists():
        return None
    for line in stack_yaml.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("ip_address:"):
            continue
        value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        literal_match = _LITERAL_RE.match(value)
        if literal_match:
            return literal_match.group(1)
        template_match = _TEMPLATE_RE.match(value)
        if template_match:
            env_var = f"LAB_IP_{template_match.group(1).upper()}"
            return os.environ.get(env_var) or None
        return None
    return None


def fetch_secret(stack: str) -> dict | None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gvm_scan_host_secret.py"), "--stack", stack],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(f"WARN: no GVM scan credentials for {stack!r} yet ({result.stderr.strip()}), skipping", file=sys.stderr)
        return None
    return json.loads(result.stdout)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, str]] = []
    for stack in IN_SCOPE_STACKS:
        host = resolve_stack_ip(stack)
        if host is None:
            print(f"WARN: could not resolve an IP for {stack!r}, skipping", file=sys.stderr)
            continue
        zone = resolve_stack_zone(stack)
        if zone is None:
            print(f"WARN: could not resolve a zone for {stack!r}, skipping", file=sys.stderr)
            continue
        secret = fetch_secret(stack)
        if secret is None:
            continue
        (out_dir / f"{stack}.key").write_text(secret["GVM_SCAN_SSH_PRIVATE_KEY"], encoding="utf-8")
        (out_dir / f"{stack}.key").chmod(0o644)
        (out_dir / f"{stack}.sudopass").write_text(secret["GVM_SCAN_SUDO_PASSWORD"], encoding="utf-8")
        (out_dir / f"{stack}.sudopass").chmod(0o644)
        manifest.append({"name": stack, "host": host, "zone": zone})

    (out_dir / "targets.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {len(manifest)}/{len(IN_SCOPE_STACKS)} fleet targets to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
