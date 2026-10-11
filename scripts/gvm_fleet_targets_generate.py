#!/usr/bin/env python3
"""Generate the GVM fleet-targets bind-mount directory for
setup_credentials.py's load_fleet_targets(), and (optionally) the Ansible
inventory deploy-gvm-scan-accounts.yml runs against
(docs/gvm-coverage-cleanup/plan.md; originally
docs/lxc-scan-and-monitoring-rollout/plan.md gvm-07).

  gvm_fleet_targets_generate.py --out-dir /path/to/tempdir/fleet
  gvm_fleet_targets_generate.py --emit-inventory /path/to/inventory.json

Two sources of scan hosts, one canonical list each:
  IN_SCOPE_STACKS -- stacks whose IP/zone resolve from their own
    terraform/lxc/stacks/<stack>/stack.yaml (literal "IP/prefix", or
    "${lab_ip_X}/prefix" resolved via env var LAB_IP_X).
  EXTRA_HOSTS -- scan hosts with no usable stack.yaml: the Proxmox nodes,
    framework, the operator workstation, the Raspberry Pis, and the
    flat-LAN LXCs on pve that have no deploy-*.yml playbook
    (management-stack, media-stack, proxmox-backup-server,
    omada-controller). IPs confirmed live 2026-10-11 via the Proxmox API
    / DNS, not assumed.

For every host it reads that host's GVM scan credentials via
gvm_scan_host_secret.py (skipping with a warning, not failing the whole
run, if the OpenBao entry doesn't exist yet) and, with --out-dir, writes:
  <out-dir>/targets.json   -- [{"name": str, "host": str, "zone": str}, ...]
  <out-dir>/<name>.key     -- SSH private key

No sudo password is written any more: GVM's "elevate privileges" feature
is su-based, not sudo-based (confirmed live 2026-10-11 from target sshd
logs -- every fleet scan ran `su -l gvm-scan`, switching to itself), so
credentialed scans now run as the unprivileged gvm-scan account with no
elevate credential at all (operator decision 2026-10-11).

Run from deploy-greenbone-stack.yml via delegate_to: localhost, or by
hand under ./with-secrets-prod for --emit-inventory; requires the same
OPENBAO_ADDR/OPENBAO_CACERT/OPENBAO_CRED_DIR/LAB_IP_OPENBAO env vars as
gvm_scan_host_secret.py (the with-secrets-prod wrapper already exports
LAB_IP_OPENBAO and every LAB_IP_* this file resolves).
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

# Operator-confirmed scope. History: 2026-09-29 first pass (25 stacks,
# see docs/lxc-scan-and-monitoring-rollout/plan.md); 2026-10-11 added the
# pve-tiny stacks that were missing (cse-code-eval, cse-controller,
# cse-panel-stack, technitium-tiny-stack -- cse_seg scanning explicitly
# approved by the operator). pentagi-stack/pentagi-upstream-control,
# harness-target*, cse-kali and other test/red-team fixtures stay out.
#
# This list is data, not a mechanical filter -- re-verify it by hand if
# the fleet changes. gvm_scan_credentials_bootstrap.py imports it (and
# EXTRA_HOSTS) directly, not a separate copy.
IN_SCOPE_STACKS = [
    "ai-services-stack",
    "apt-cacher-stack",
    "authentik-stack",
    "ci-runner-01",
    "cse-code-eval",
    "cse-controller",
    "cse-panel-stack",
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
    "technitium-tiny-stack",
    "torrent-stack-lab",
    "wazuh-stack",
]

# Hosts with no usable stack.yaml. "ansible_user" is how
# deploy-gvm-scan-accounts.yml connects (become: true is applied on top);
# "ansible_connection": "local" marks the operator workstation itself.
EXTRA_HOSTS = {
    "host-pve": {"host": "192.168.1.2", "zone": "lan", "ansible_user": "root"},
    "host-pve-tiny": {"host": "192.168.1.250", "zone": "lan", "ansible_user": "root"},
    "host-framework": {"host": "192.168.1.18", "zone": "lan", "ansible_user": "steve"},
    "host-workstation": {"host": "192.168.1.104", "zone": "lan", "ansible_connection": "local"},
    "host-pi-22": {"host": "192.168.1.22", "zone": "lan", "ansible_user": "ansible"},
    "host-pi-23": {"host": "192.168.1.23", "zone": "lan", "ansible_user": "ansible"},
    "management-stack": {"host": "192.168.1.4", "zone": "lan", "ansible_user": "root"},
    "media-stack": {"host": "192.168.1.6", "zone": "lan", "ansible_user": "root"},
    "proxmox-backup-server": {"host": "192.168.1.12", "zone": "lan", "ansible_user": "root"},
    "omada-controller": {"host": "192.168.1.252", "zone": "lan", "ansible_user": "root"},
}

ALL_SCAN_HOST_NAMES = IN_SCOPE_STACKS + sorted(EXTRA_HOSTS)

_TEMPLATE_RE = re.compile(r"^\$\{lab_ip_([a-z0-9_]+)\}/\d+$")
_LITERAL_RE = re.compile(r"^(\d+\.\d+\.\d+\.\d+)/\d+$")


def resolve_stack_zone(stack: str) -> str | None:
    """Reads terraform/lxc/stacks/<stack>/stack.yaml's zone field. Handles
    both the plain "zone: <name>" form and the nested
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


def resolve_all_hosts() -> list[dict]:
    """Every scan host as {"name", "host", "zone", plus EXTRA_HOSTS'
    connection keys}. Skips (with a warning) any stack whose IP or zone
    can't be resolved."""
    hosts: list[dict] = []
    for stack in IN_SCOPE_STACKS:
        host = resolve_stack_ip(stack)
        if host is None:
            print(f"WARN: could not resolve an IP for {stack!r}, skipping", file=sys.stderr)
            continue
        zone = resolve_stack_zone(stack)
        if zone is None:
            print(f"WARN: could not resolve a zone for {stack!r}, skipping", file=sys.stderr)
            continue
        hosts.append({"name": stack, "host": host, "zone": zone, "ansible_user": "root"})
    for name in sorted(EXTRA_HOSTS):
        hosts.append({"name": name, **EXTRA_HOSTS[name]})
    return hosts


def fetch_secret(name: str) -> dict | None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gvm_scan_host_secret.py"), "--stack", name],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(f"WARN: no GVM scan credentials for {name!r} yet ({result.stderr.strip()}), skipping", file=sys.stderr)
        return None
    return json.loads(result.stdout)


def write_fleet_dir(out_dir: Path, hosts: list[dict]) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, str]] = []
    for entry in hosts:
        secret = fetch_secret(entry["name"])
        if secret is None:
            continue
        key_path = out_dir / f"{entry['name']}.key"
        key_path.write_text(secret["GVM_SCAN_SSH_PRIVATE_KEY"], encoding="utf-8")
        key_path.chmod(0o644)
        manifest.append({"name": entry["name"], "host": entry["host"], "zone": entry["zone"]})
    (out_dir / "targets.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {len(manifest)}/{len(ALL_SCAN_HOST_NAMES)} fleet targets to {out_dir}")
    return 0


def write_inventory(path: Path, hosts: list[dict]) -> int:
    """JSON is valid YAML, so Ansible's yaml inventory plugin reads this
    directly (it accepts the .json extension). gvm_scan_name is the
    OpenBao entry name deploy-gvm-scan-accounts.yml reads."""
    inventory_hosts = {}
    for entry in hosts:
        host_vars = {"ansible_host": entry["host"], "gvm_scan_name": entry["name"]}
        if entry.get("ansible_connection") == "local":
            host_vars["ansible_connection"] = "local"
        else:
            host_vars["ansible_user"] = entry["ansible_user"]
            host_vars["ansible_ssh_common_args"] = "-o StrictHostKeyChecking=accept-new"
        inventory_hosts[entry["name"]] = host_vars
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"all": {"hosts": inventory_hosts}}, indent=2), encoding="utf-8")
    print(f"wrote inventory with {len(inventory_hosts)} hosts to {path}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", help="Write targets.json + <name>.key files here")
    parser.add_argument("--emit-inventory", help="Write an Ansible inventory (JSON) for deploy-gvm-scan-accounts.yml here")
    args = parser.parse_args(argv)
    if not args.out_dir and not args.emit_inventory:
        parser.print_help()
        return 2

    hosts = resolve_all_hosts()
    if args.emit_inventory:
        write_inventory(Path(args.emit_inventory), hosts)
    if args.out_dir:
        write_fleet_dir(Path(args.out_dir), hosts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
