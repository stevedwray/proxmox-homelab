# gvm-coverage-cleanup plan

Context, evidence and operator decisions: [README.md](README.md). Step
shape: [docs/agent-design/step-packet-schema.md](../agent-design/step-packet-schema.md).

**How to run this plan.**

- Steps `gvmcov-01`…`gvmcov-16` are file edits only. Each step's `change`
  is one literal shell block (heredoc file writes, or a Python edit script
  that asserts every anchor it replaces). Run it exactly as written from
  the repo root, then run the gates. No step touches production.
- Every block was run in order against a clean copy of this branch on
  2026-10-11, and every gate below passed.
- The **Operator runbook** at the end is the production work. It is plain
  prose, not step blocks, because it needs an OIDC login, `TASK_APPROVAL`
  under the production approval flow, and become passwords.
- Run `ansible-playbook --syntax-check` gates with `</dev/null`. Without it,
  Ansible can fail with "requires blocking IO" under some shells.

Validation tier (CLAUDE.md): Ansible role/task changes go through
`scripts/provision.sh` / targeted playbooks directly on `pve` under the
production approval flow. The MikroTik change is an additive
narrowly-scoped allow rule. pve-test-vm is retired, so it is applied
directly, with an explicit rule-order check afterwards.

## Steps

### gvmcov-01-role-unprivileged

```yaml
id: gvmcov-01-role-unprivileged
title: Make the gvm-scan account key-only and drop its sudo grant
depends_on: []

change: >
  Overwrite terraform/lxc/ansible/roles/gvm_scan_account/defaults/main.yml and
  tasks/main.yml with the exact content in the block below: remove the
  gvm_scan_account_sudo_password_hash variable and its assert, set the
  account password to "*", and replace the sudoers drop-in task with one
  that deletes /etc/sudoers.d/gvm-scan.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/gvm_scan_account/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any ansible-playbook run other than --syntax-check"

gates:
  - id: no-sudo-grant
    cmd: "grep -c 'ALL=(ALL)' terraform/lxc/ansible/roles/gvm_scan_account/tasks/main.yml"
    expect: "prints 0"
    critical: true
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-apt-cacher-stack.yml </dev/null"
    expect: "exit 0"
    critical: true
```

```bash
cat > terraform/lxc/ansible/roles/gvm_scan_account/defaults/main.yml <<'EOF'
---
# Defaults for gvm_scan_account -- see docs/gvm-coverage-cleanup/plan.md.
# Creates the dedicated "gvm-scan" local account GVM's credentialed (LSC)
# scans log in as: SSH key only, no usable password, no sudo.
#
# GVM's "elevate privileges" feature is su-based, not sudo-based --
# confirmed live 2026-10-11 from target sshd logs (every fleet scan ran
# `su -l gvm-scan`, switching to itself), so the original password-gated
# sudo grant was never used and made every scheduled scan report "SSH Login
# Failed For Authenticated Checks". Operator decision 2026-10-11: scan
# unprivileged. This role now removes the old sudoers drop-in.

# Deliberately no real default -- a security-relevant, per-host, unique
# value that must come from that host's own OpenBao entry via
# scripts/gvm_scan_host_secret.py, never guessed or shared across hosts.
gvm_scan_account_public_key: ""
EOF
cat > terraform/lxc/ansible/roles/gvm_scan_account/tasks/main.yml <<'EOF'
---
# gvm_scan_account -- see defaults/main.yml and docs/gvm-coverage-cleanup/
# plan.md for the design. Uses ansible.builtin modules only (ansible.posix
# isn't a declared collection dependency in this repo).

- name: Fail closed if this host's GVM scan public key wasn't supplied
  ansible.builtin.assert:
    that:
      - gvm_scan_account_public_key | length > 0
    fail_msg: >-
      gvm_scan_account_public_key must be set by the including playbook
      (from this host's own OpenBao entry via
      scripts/gvm_scan_host_secret.py) -- never guessed or defaulted.

# password "*" = no password can ever match, so no password login and no
# `su gvm-scan`, but (unlike a "!"-prefixed locked password) sshd still
# accepts public-key logins for the account.
- name: Create the gvm-scan system account (key-only, no usable password)
  ansible.builtin.user:
    name: gvm-scan
    shell: /bin/bash
    create_home: true
    password: "*"

- name: Ensure gvm-scan's .ssh directory exists
  ansible.builtin.file:
    path: /home/gvm-scan/.ssh
    state: directory
    owner: gvm-scan
    group: gvm-scan
    mode: "0700"

- name: Write gvm-scan's authorized_keys (exclusive -- this is the only key it should ever trust)
  ansible.builtin.copy:
    dest: /home/gvm-scan/.ssh/authorized_keys
    content: "{{ gvm_scan_account_public_key }}\n"
    owner: gvm-scan
    group: gvm-scan
    mode: "0600"

- name: Remove the old gvm-scan sudo grant (GVM never uses sudo)
  ansible.builtin.file:
    path: /etc/sudoers.d/gvm-scan
    state: absent
EOF
```

### gvmcov-02-playbooks-drop-sudo-var

```yaml
id: gvmcov-02-playbooks-drop-sudo-var
title: Remove the now-unused sudo password var from every deploy playbook
depends_on: [gvmcov-01-role-unprivileged]

change: >
  Delete the single line "    gvm_scan_account_sudo_password_hash: ..." from
  every terraform/lxc/ansible/playbooks/deploy-*.yml that has it (25 files)
  with the one sed command below. No other line changes.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/
  forbidden_actions:
    - "Any edit other than deleting that one line per file"

gates:
  - id: var-gone
    cmd: "grep -rl gvm_scan_account_sudo_password_hash terraform/lxc/ansible/playbooks | wc -l"
    expect: "prints 0"
    critical: true
  - id: syntax-check-all
    cmd: "cd terraform/lxc/ansible && for f in $(grep -l gvm_scan_account playbooks/*.yml); do ansible-playbook --syntax-check -i localhost, $f </dev/null >/dev/null || echo FAIL $f; done"
    expect: "prints nothing"
    critical: true
```

```bash
sed -i '/^    gvm_scan_account_sudo_password_hash: /d' terraform/lxc/ansible/playbooks/deploy-*.yml
```

### gvmcov-03-host-registry

```yaml
id: gvmcov-03-host-registry
title: One host registry for every credentialed scan host, plus inventory output
depends_on: []

change: >
  Overwrite scripts/gvm_fleet_targets_generate.py with the exact content below.
  It adds the four missing pve-tiny stacks to IN_SCOPE_STACKS and a new
  EXTRA_HOSTS dict (Proxmox nodes, framework, workstation, Pis, and 4 flat-LAN
  LXCs). It also stops writing .sudopass files and adds
  --emit-inventory for deploy-gvm-scan-accounts.yml.

scope:
  allowed_paths:
    - scripts/gvm_fleet_targets_generate.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running it with --out-dir (that reads OpenBao)"

gates:
  - id: compile
    cmd: "python3 -m py_compile scripts/gvm_fleet_targets_generate.py"
    expect: "exit 0"
    critical: true
  - id: inventory-resolves-all-39
    cmd: "bash -c 'set -a; . ./.env >/dev/null 2>&1; python3 scripts/gvm_fleet_targets_generate.py --emit-inventory /tmp/gvmcov-inv.json'"
    expect: "prints 'wrote inventory with 39 hosts' and no WARN lines"
    critical: true
```

```bash
cat > scripts/gvm_fleet_targets_generate.py <<'GVMCOV_EOF'
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
GVMCOV_EOF
```

### gvmcov-04-bootstrap-key-only

```yaml
id: gvmcov-04-bootstrap-key-only
title: Credential bootstrap writes keys only, accepts every registry name
depends_on: [gvmcov-03-host-registry]

change: >
  Overwrite scripts/gvm_scan_credentials_bootstrap.py with the exact content
  below (validates names against ALL_SCAN_HOST_NAMES, writes only
  GVM_SCAN_SSH_PRIVATE_KEY/GVM_SCAN_SSH_PUBLIC_KEY). Then run the Python
  edit block that fixes the field list in gvm_scan_host_secret.py's docstring.

scope:
  allowed_paths:
    - scripts/gvm_scan_credentials_bootstrap.py
    - scripts/gvm_scan_host_secret.py
  forbidden_actions:
    - "Running the bootstrap script (it writes to OpenBao -- operator only)"

gates:
  - id: compile
    cmd: "python3 -m py_compile scripts/gvm_scan_credentials_bootstrap.py scripts/gvm_scan_host_secret.py"
    expect: "exit 0"
    critical: true
  - id: help-runs
    cmd: "python3 scripts/gvm_scan_credentials_bootstrap.py --help"
    expect: "exit 0, mentions '(39 hosts)'"
    critical: true
```

```bash
cat > scripts/gvm_scan_credentials_bootstrap.py <<'GVMCOV_EOF'
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
GVMCOV_EOF
python3 - <<'PYEOF'
from pathlib import Path

path = Path("scripts/gvm_scan_host_secret.py")
text = path.read_text(encoding="utf-8")
old = "Fields: GVM_SCAN_SSH_PRIVATE_KEY, GVM_SCAN_SSH_PUBLIC_KEY,\n        GVM_SCAN_SUDO_PASSWORD\n"
new = ("Fields: GVM_SCAN_SSH_PRIVATE_KEY, GVM_SCAN_SSH_PUBLIC_KEY\n"
       "(entries written before 2026-10-11 also still hold an unused\n"
       "GVM_SCAN_SUDO_PASSWORD -- see docs/gvm-coverage-cleanup/plan.md)\n")
assert text.count(old) == 1
path.write_text(text.replace(old, new), encoding="utf-8")
print("gvm_scan_host_secret.py docstring updated")
PYEOF
```

### gvmcov-05-manifest

```yaml
id: gvmcov-05-manifest
title: Declare the 14 new scan-host entries; drop unused fields
depends_on: []

change: >
  Run the Python edit block below against secrets/manifest.json. It drops
  GVM_SCAN_SUDO_PASSWORD from all 25 existing scan-hosts entries, adds 14 new
  services/greenbone/scan-hosts/<name> entries after wazuh-stack's, and drops
  GREENBONE_STEVE_SSH_PRIVATE_KEY and
  GREENBONE_OPENVAS_WORKSTATION_SSH_PRIVATE_KEY from services/greenbone.

scope:
  allowed_paths:
    - secrets/manifest.json
  forbidden_actions:
    - "Any OpenBao read or write"

gates:
  - id: json-valid
    cmd: "python3 -m json.tool secrets/manifest.json >/dev/null"
    expect: "exit 0"
    critical: true
  - id: entry-count
    cmd: "grep -c 'scan-hosts/' secrets/manifest.json; grep -c GVM_SCAN_SUDO_PASSWORD secrets/manifest.json"
    expect: "prints 39 then 0"
    critical: true
  - id: unit-tests
    cmd: "python3 -m unittest discover -s scripts -p 'test_*.py'"
    expect: "OK"
    critical: true
```

```bash
python3 - <<'EOF'
from pathlib import Path

path = Path("secrets/manifest.json")
text = path.read_text(encoding="utf-8")

old_fields = '"fields": ["GVM_SCAN_SSH_PRIVATE_KEY", "GVM_SCAN_SSH_PUBLIC_KEY", "GVM_SCAN_SUDO_PASSWORD"]'
new_fields = '"fields": ["GVM_SCAN_SSH_PRIVATE_KEY", "GVM_SCAN_SSH_PUBLIC_KEY"]'
assert text.count(old_fields) == 25, text.count(old_fields)
text = text.replace(old_fields, new_fields)

anchor = '    "services/greenbone/scan-hosts/wazuh-stack": {\n      ' + new_fields + '\n    },\n'
assert text.count(anchor) == 1
new_names = [
    "cse-code-eval", "cse-controller", "cse-panel-stack", "technitium-tiny-stack",
    "host-framework", "host-pi-22", "host-pi-23", "host-pve", "host-pve-tiny", "host-workstation",
    "management-stack", "media-stack", "omada-controller", "proxmox-backup-server",
]
block = "".join(
    f'    "services/greenbone/scan-hosts/{name}": {{\n      {new_fields}\n    }},\n' for name in new_names
)
text = text.replace(anchor, anchor + block)

old_greenbone = '"GREENBONE_MIKROTIK_SSH_PRIVATE_KEY", "GREENBONE_OCI_PANGOLIN_AUDIT_SSH_PRIVATE_KEY", "GREENBONE_OPENVAS_WORKSTATION_SSH_PRIVATE_KEY", "GREENBONE_PENTAGI_PASSWORD", "GREENBONE_STEVE_SSH_PRIVATE_KEY"'
new_greenbone = '"GREENBONE_MIKROTIK_SSH_PRIVATE_KEY", "GREENBONE_OCI_PANGOLIN_AUDIT_SSH_PRIVATE_KEY", "GREENBONE_PENTAGI_PASSWORD"'
assert text.count(old_greenbone) == 1
text = text.replace(old_greenbone, new_greenbone)

path.write_text(text, encoding="utf-8")
print("manifest updated")
EOF
```

### gvmcov-06-pve-tiny-playbooks

```yaml
id: gvmcov-06-pve-tiny-playbooks
title: Add the gvm_scan_account play to the four pve-tiny stack playbooks
depends_on: [gvmcov-01-role-unprivileged]

change: >
  Append the "Provision the dedicated GVM credentialed-scan account" play
  (same shape as deploy-apt-cacher-stack.yml's, without the sudo var) to
  deploy-cse-code-eval.yml, deploy-cse-controller.yml,
  deploy-cse-panel-stack.yml and deploy-technitium-tiny-stack.yml, using the
  loop below verbatim.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-cse-code-eval.yml
    - terraform/lxc/ansible/playbooks/deploy-cse-controller.yml
    - terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml
    - terraform/lxc/ansible/playbooks/deploy-technitium-tiny-stack.yml
  forbidden_actions:
    - "Any edit to existing plays in those files"

gates:
  - id: appended-once
    cmd: "for s in cse-code-eval cse-controller cse-panel-stack technitium-tiny-stack; do grep -c '^    - gvm_scan_account$' terraform/lxc/ansible/playbooks/deploy-$s.yml; done"
    expect: "prints 1 four times"
    critical: true
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && for s in cse-code-eval cse-controller cse-panel-stack technitium-tiny-stack; do ansible-playbook --syntax-check -i localhost, playbooks/deploy-$s.yml </dev/null >/dev/null || echo FAIL $s; done"
    expect: "prints nothing"
    critical: true
```

```bash
for stack in cse-code-eval cse-controller cse-panel-stack technitium-tiny-stack; do
  file="terraform/lxc/ansible/playbooks/deploy-${stack}.yml"
  grep -q "gvm_scan_account" "$file" && { echo "SKIP $file (already has gvm_scan_account)"; continue; }
  cat >> "$file" <<EOF

- name: Provision the dedicated GVM credentialed-scan account (docs/gvm-coverage-cleanup/plan.md)
  hosts: all
  become: true
  gather_facts: false
  pre_tasks:
    - name: Read this stack's GVM scan credentials from OpenBao
      ansible.builtin.command:
        argv:
          - python3
          - "{{ playbook_dir }}/../../../../scripts/gvm_scan_host_secret.py"
          - --stack
          - ${stack}
      register: gvm_scan_secret_raw
      delegate_to: localhost
      become: false
      changed_when: false
    - name: Parse the credentials JSON
      ansible.builtin.set_fact:
        gvm_scan_secret: "{{ gvm_scan_secret_raw.stdout | from_json }}"
  vars:
    gvm_scan_account_public_key: "{{ gvm_scan_secret.GVM_SCAN_SSH_PUBLIC_KEY }}"
  roles:
    - gvm_scan_account
EOF
  echo "appended to $file"
done
```

### gvmcov-07-standalone-playbook

```yaml
id: gvmcov-07-standalone-playbook
title: Targeted playbook that applies only gvm_scan_account to any scan host
depends_on: [gvmcov-01-role-unprivileged]

change: >
  Create terraform/lxc/ansible/playbooks/deploy-gvm-scan-accounts.yml with the
  exact content below. Each host reads its own OpenBao entry by the
  gvm_scan_name host var that gvm_fleet_targets_generate.py --emit-inventory
  writes.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-gvm-scan-accounts.yml
  forbidden_actions:
    - "Running the playbook (operator runbook only)"

gates:
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-gvm-scan-accounts.yml </dev/null"
    expect: "exit 0"
    critical: true
```

```bash
cat > terraform/lxc/ansible/playbooks/deploy-gvm-scan-accounts.yml <<'EOF'
---
# Applies ONLY the gvm_scan_account role to every GVM credentialed-scan
# host -- docs/gvm-coverage-cleanup/plan.md. Covers hosts that have no
# deploy-*.yml of their own (Proxmox nodes, framework, the workstation, the
# Raspberry Pis, management-stack, media-stack, proxmox-backup-server,
# omada-controller) and is the targeted way to roll a role change out to
# the stack fleet without a full per-stack redeploy.
#
# The inventory is generated, never hand-typed:
#   ./with-secrets-prod python3 scripts/gvm_fleet_targets_generate.py \
#     --emit-inventory /tmp/gvm-scan-inventory.json
# Each host's gvm_scan_name is its OpenBao entry name
# (services/greenbone/scan-hosts/<gvm_scan_name>).
- name: Provision the GVM credentialed-scan account on every scan host
  hosts: all
  become: true
  gather_facts: false
  pre_tasks:
    - name: Read this host's GVM scan credentials from OpenBao
      ansible.builtin.command:
        argv:
          - python3
          - "{{ playbook_dir }}/../../../../scripts/gvm_scan_host_secret.py"
          - --stack
          - "{{ gvm_scan_name }}"
      register: gvm_scan_secret_raw
      delegate_to: localhost
      become: false
      changed_when: false
    - name: Parse the credentials JSON
      ansible.builtin.set_fact:
        gvm_scan_secret: "{{ gvm_scan_secret_raw.stdout | from_json }}"
  vars:
    gvm_scan_account_public_key: "{{ gvm_scan_secret.GVM_SCAN_SSH_PUBLIC_KEY }}"
  roles:
    - gvm_scan_account
EOF
```

### gvmcov-08-setup-credentials

```yaml
id: gvmcov-08-setup-credentials
title: Reconciling credential program -- no elevate, legacy cleanup, schedules for all
depends_on: []

change: >
  Overwrite terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py
  with the exact content below. Changes: no ssh_elevate_credential; each
  fleet host is rebuilt when its managed-fp fingerprint (host, key, port list,
  alive test, version) changes; legacy root/openvas/Pi targets and credentials
  are deleted; MikroTik gets the lan schedule; cse_seg and lan get schedule
  times.

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: compile
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py"
    expect: "exit 0"
    critical: true
  - id: no-elevate
    cmd: "grep -c 'ssh_elevate\\|GREENBONE_STEVE\\|OPENVAS_WORKSTATION' terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py"
    expect: "prints 0"
    critical: true
```

```bash
cat > terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py <<'GVMCOV_EOF'
#!/usr/bin/env python3
"""Reconcile Greenbone's credentialed scan objects
(docs/gvm-coverage-cleanup/plan.md; originally
docs/lxc-scan-and-monitoring-rollout/plan.md gvm-07/gvm-08).

Two kinds of credentialed target:

1. Fleet hosts (every LXC, Proxmox node, framework, the workstation and the
   Raspberry Pis): one unique "gvm-scan" SSH keypair per host, read from
   OpenBao (services/greenbone/scan-hosts/<name>) by
   scripts/gvm_fleet_targets_generate.py and delivered as a single
   bind-mounted directory (GVM_FLEET_DIR, default /tmp/fleet): one
   targets.json manifest (list of {"name", "host", "zone"} -- no secret
   content) plus one "<name>.key" per host. Each host gets its own "usk"
   login credential, Target and Task. There is NO elevate-privileges
   credential: GVM's elevate feature is su-based, not sudo-based --
   confirmed live 2026-10-11 from target sshd logs, every fleet scan ran
   `su -l gvm-scan` (switching to itself) and every one of ~170 scheduled
   runs since 2026-09-30 reported "SSH Login Failed For Authenticated
   Checks" with zero Local Security Check results. Operator decision
   2026-10-11: scan as the unprivileged gvm-scan account (Debian/Ubuntu
   package checks don't need root).

2. The MikroTik router: its own RouterOS "gvm-scan" user and key
   (GREENBONE_MIKROTIK_KEY_PATH), created by
   ansible/00-initial-setup/mikrotik-gvm-scan-user.yml.

Reconciliation, not create-only: every fleet Target carries a
"managed-fp:<hash>" marker in its comment, a hash of (host, private key,
port list, alive test, RECONCILE_VERSION). If the marker is missing or
differs -- a rotated key in OpenBao, a changed IP, a changed scan
setting -- the host's Task, Target and credentials are deleted and
recreated. Delete-and-recreate rather than modify_target because gvmd
refuses to change hosts/credentials on a Target that is in use by a Task.
A Task that is currently running is left alone with a WARN and picked up
on the next run. Deleting a Task deletes its reports in GVM; findings
already ingested into OpenSearch (gvm-findings) are unaffected.

Credentialed Targets are explicit single-host lists so a credential can
never be applied accidentally to an arbitrary host discovered on a
subnet.

VLAN-organized scheduling: a GVM Target can only carry one
ssh_credential_id for every host it contains, so each host keeps its own
Target/Task and gets its zone's daily Schedule (ZONE_SCHEDULE_TIMES) plus
a zone Tag (zone:<name>) for GSA-side grouping and filtering.
"""
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

# Daily, staggered ~45min apart overnight in the operator's own local time
# (Pacific/Auckland, a real IANA zone so NZ DST transitions resolve
# correctly -- see the 2026-09-30 UTC-vs-NZT fix in git history).
ZONE_SCHEDULE_TIMES = {
    "cse_seg": "23:30",
    "lan": "00:15",
    "mgmt_seg": "01:00",
    "infra_seg": "01:45",
    "ai_seg": "02:30",
    "media_seg": "03:15",
    "game_seg": "04:00",
    "edge_seg": "04:45",
    "pentest_seg": "05:30",
    "connector_seg": "06:15",
    "build_seg": "07:00",
    "apps_seg": "07:45",
}
SCHEDULE_TIMEZONE = "Pacific/Auckland"

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]
START_TASK_NAME = os.environ.get("GREENBONE_START_TASK_NAME", "")
STATUS_TASK_NAME = os.environ.get("GREENBONE_STATUS_TASK_NAME", "")

GVM_FLEET_DIR = os.environ.get("GVM_FLEET_DIR", "/tmp/fleet")  # nosonar: python:S5443 -- container-internal /tmp inside an isolated `docker compose run --rm` gvm-tools container, not a shared host path
GVM_FLEET_LOGIN = "gvm-scan"

FULL_CONFIG_NAME = "Full and fast"
SCANNER_NAME = "OpenVAS Default"
PORT_LIST_NAME = "All TCP and Nmap top 100 UDP"
ALIVE_TESTS = "ICMP, TCP-ACK Service & ARP Ping"

# Bump to force every fleet host's GVM objects to be rebuilt on the next
# run, e.g. after changing how targets are built. "2" = no elevate
# credential (2026-10-11).
RECONCILE_VERSION = "2"
FP_MARKER = "managed-fp:"
ACTIVE_TASK_STATUSES = {"Running", "Requested", "Queued", "Stop Requested", "Delete Requested"}

MIKROTIK_CREDENTIAL = {
    "name": "MikroTik gvm-scan SSH key",
    "login": "gvm-scan",
    "key_path": os.environ["GREENBONE_MIKROTIK_KEY_PATH"],
}
MIKROTIK_TARGET = {
    "name": "Credentialed scan: MikroTik router",
    "hosts": ["192.168.1.1"],
    "zone": "lan",
}

# Retired 2026-10-11 (docs/gvm-coverage-cleanup/plan.md): the hand-picked
# root-key targets (stale pve-test-vm "+100" IPs, a destroyed dns-stack),
# the pve/workstation/Pi targets now covered by per-host gvm-scan fleet
# targets, and the credentials only they used. Deleted (ultimate) if
# present; a no-op once gone.
LEGACY_TASKS_AND_TARGETS = [
    "Credentialed scan: managed Debian services",
    "Credentialed scan: pve hypervisor",
    "Credentialed scan: Linux workstation",
    "Credentialed scan: Raspberry Pis",
]
LEGACY_CREDENTIALS = [
    "Lab root SSH key (Steve)",
    "Workstation openvas SSH key",
    "Raspberry Pi ansible SSH key (Steve)",
]


def find_by_name(gmp, getter, tag, name):
    response = getter(filter_string=f'name="{name}"')
    element = response.find(tag)
    return element.get("id") if element is not None else None


def resolve_id(gmp, getter, name, tag):
    object_id = find_by_name(gmp, getter, tag, name)
    if not object_id:
        raise RuntimeError(f"{tag} {name!r} not found on this gvmd")
    return object_id


def fingerprint(*parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def task_status(gmp, task_id):
    return gmp.get_task(task_id).findtext("task/status", default="unknown")


def delete_if_present(gmp, kind, name):
    """kind is "task", "target" or "credential". Returns False only when a
    task exists but is active (running/queued) and so was left alone."""
    getter = {"task": gmp.get_tasks, "target": gmp.get_targets, "credential": gmp.get_credentials}[kind]
    deleter = {"task": gmp.delete_task, "target": gmp.delete_target, "credential": gmp.delete_credential}[kind]
    object_id = find_by_name(gmp, getter, kind, name)
    if not object_id:
        return True
    if kind == "task":
        status = task_status(gmp, object_id)
        if status in ACTIVE_TASK_STATUSES:
            print(f"WARN: task {name!r} is {status}, leaving it alone this run")
            return False
    deleter(object_id, ultimate=True)
    print(f"deleted {kind} {name!r} ({object_id})")
    return True


def cleanup_legacy(gmp):
    for name in LEGACY_TASKS_AND_TARGETS:
        if delete_if_present(gmp, "task", name):
            delete_if_present(gmp, "target", name)
    for name in LEGACY_CREDENTIALS:
        delete_if_present(gmp, "credential", name)


def ensure_credential(gmp, name, login, key_path):
    existing = find_by_name(gmp, gmp.get_credentials, "credential", name)
    if existing:
        print(f"credential {name!r} already exists ({existing}), skipping")
        return existing
    response = gmp.create_credential(
        name=name,
        credential_type="usk",
        login=login,
        private_key=Path(key_path).read_text(encoding="utf-8"),
        comment="Managed by setup_credentials.py; do not edit manually in GSA.",
    )
    credential_id = response.get("id")
    print(f"created credential {name!r} ({credential_id})")
    return credential_id


def ensure_target(gmp, name, hosts, credential_id, port_list_id, comment):
    existing = find_by_name(gmp, gmp.get_targets, "target", name)
    if existing:
        print(f"target {name!r} already exists ({existing}), skipping")
        return existing
    response = gmp.create_target(
        name=name,
        hosts=hosts,
        ssh_credential_id=credential_id,
        alive_test=ALIVE_TESTS,
        port_list_id=port_list_id,
        comment=comment,
    )
    target_id = response.get("id")
    print(f"created target {name!r} ({target_id})")
    return target_id


def ensure_task(gmp, name, config_id, target_id, scanner_id, schedule_id):
    existing = find_by_name(gmp, gmp.get_tasks, "task", name)
    if existing:
        gmp.modify_task(existing, schedule_id=schedule_id)
        print(f"task {name!r} already exists ({existing}), ensured schedule {schedule_id!r}")
        return existing
    response = gmp.create_task(
        name=name,
        config_id=config_id,
        target_id=target_id,
        scanner_id=scanner_id,
        schedule_id=schedule_id,
        comment="Managed credentialed task; daily per-zone schedule.",
    )
    task_id = response.get("id")
    print(f"created task {name!r} ({task_id}) scheduled via {schedule_id!r}")
    return task_id


def ensure_schedule(gmp, zone):
    """One recurring daily GVM Schedule per network zone. Re-applies
    icalendar/timezone on every run so a corrected ZONE_SCHEDULE_TIMES
    value lands on already-created schedules too. Hand-builds the
    iCalendar text rather than depending on the `icalendar` package."""
    hhmm = ZONE_SCHEDULE_TIMES.get(zone)
    if hhmm is None:
        raise RuntimeError(
            f"no schedule start time configured for zone {zone!r} -- add it to "
            f"ZONE_SCHEDULE_TIMES in this file before this zone can be scheduled"
        )
    name = f"Daily fleet scan: {zone}"
    hour, minute = hhmm.split(":")
    now = datetime.datetime.now(datetime.timezone.utc)
    icalendar = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//proxmox-homelab//gvm-fleet-schedule//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:gvm-fleet-schedule-{zone}@proxmox-homelab\r\n"
        f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTSTART:{now.strftime('%Y%m%d')}T{hour}{minute}00\r\n"
        "RRULE:FREQ=DAILY\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    comment = f"Credentialed scans for zone {zone!r}, daily at {hhmm} {SCHEDULE_TIMEZONE}."
    existing = find_by_name(gmp, gmp.get_schedules, "schedule", name)
    if existing:
        gmp.modify_schedule(existing, icalendar=icalendar, timezone=SCHEDULE_TIMEZONE, comment=comment)
        print(f"schedule {name!r} ({existing}) updated to daily at {hhmm} {SCHEDULE_TIMEZONE}")
        return existing
    response = gmp.create_schedule(name=name, icalendar=icalendar, timezone=SCHEDULE_TIMEZONE, comment=comment)
    schedule_id = response.get("id")
    print(f"created schedule {name!r} ({schedule_id}) daily at {hhmm} {SCHEDULE_TIMEZONE}")
    return schedule_id


def ensure_zone_tag(gmp, zone, task_ids):
    if not task_ids:
        return None
    name = f"zone:{zone}"
    existing = find_by_name(gmp, gmp.get_tags, "tag", name)
    if existing:
        gmp.modify_tag(existing, resource_action="add", resource_type="task", resource_ids=task_ids)
        print(f"tag {name!r} ({existing}) -- ensured {len(task_ids)} task(s) attached")
        return existing
    response = gmp.create_tag(
        name=name,
        resource_type="task",
        resource_ids=task_ids,
        comment=f"Credentialed scan hosts in network zone {zone!r}.",
    )
    tag_id = response.get("id")
    print(f"created tag {name!r} ({tag_id}) attached to {len(task_ids)} task(s)")
    return tag_id


def load_fleet_targets(fleet_dir):
    """Returns a list of {"name", "host", "zone", "key_path"} dicts, or []
    if GVM_FLEET_DIR has no targets.json -- degrades gracefully rather
    than crashing the whole run over an incomplete rollout."""
    manifest_path = Path(fleet_dir) / "targets.json"
    if not manifest_path.exists():
        print(f"no fleet targets manifest at {manifest_path}, skipping fleet targets")
        return []
    fleet = []
    for entry in json.loads(manifest_path.read_text(encoding="utf-8")):
        key_path = Path(fleet_dir) / f"{entry['name']}.key"
        if not key_path.exists():
            print(f"WARN: fleet target {entry['name']!r} missing key file, skipping")
            continue
        if not entry.get("zone"):
            print(f"WARN: fleet target {entry['name']!r} has no zone, skipping")
            continue
        fleet.append({**entry, "key_path": str(key_path)})
    return fleet


def reconcile_fleet_host(gmp, fleet_target, config_id, scanner_id, port_list_id, schedule_id):
    """Returns the host's task id, or None if it was skipped this run."""
    name = fleet_target["name"]
    object_name = f"Credentialed scan: fleet/{name}"
    login_credential_name = f"fleet-{name}-login"
    legacy_sudo_credential_name = f"fleet-{name}-sudo"
    private_key = Path(fleet_target["key_path"]).read_text(encoding="utf-8")
    fp = fingerprint(fleet_target["host"], private_key, PORT_LIST_NAME, ALIVE_TESTS, RECONCILE_VERSION)
    marker = f"{FP_MARKER}{fp}"

    target_id = find_by_name(gmp, gmp.get_targets, "target", object_name)
    current_comment = ""
    if target_id:
        current_comment = gmp.get_target(target_id).findtext("target/comment", default="")
    if target_id and marker in current_comment:
        print(f"fleet host {name!r} up to date ({marker})")
    else:
        reason = "new" if not target_id else "changed key/IP/settings"
        print(f"fleet host {name!r}: rebuilding GVM objects ({reason})")
        if not delete_if_present(gmp, "task", object_name):
            return None
        delete_if_present(gmp, "target", object_name)
        delete_if_present(gmp, "credential", login_credential_name)
        delete_if_present(gmp, "credential", legacy_sudo_credential_name)
        credential_id = ensure_credential(gmp, login_credential_name, GVM_FLEET_LOGIN, fleet_target["key_path"])
        target_id = ensure_target(
            gmp, object_name, [fleet_target["host"]], credential_id, port_list_id,
            comment=f"Managed by setup_credentials.py; single explicit host. {marker}",
        )
    return ensure_task(gmp, object_name, config_id, target_id, scanner_id, schedule_id)


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        config_id = resolve_id(gmp, gmp.get_scan_configs, FULL_CONFIG_NAME, "config")
        scanner_id = resolve_id(gmp, gmp.get_scanners, SCANNER_NAME, "scanner")
        port_list_id = resolve_id(gmp, gmp.get_port_lists, PORT_LIST_NAME, "port_list")

        cleanup_legacy(gmp)

        schedule_ids_by_zone = {}
        task_ids_by_zone = {}

        def schedule_for(zone):
            if zone not in schedule_ids_by_zone:
                schedule_ids_by_zone[zone] = ensure_schedule(gmp, zone)
            return schedule_ids_by_zone[zone]

        mikrotik_credential_id = ensure_credential(
            gmp, MIKROTIK_CREDENTIAL["name"], MIKROTIK_CREDENTIAL["login"], MIKROTIK_CREDENTIAL["key_path"],
        )
        mikrotik_target_id = ensure_target(
            gmp, MIKROTIK_TARGET["name"], MIKROTIK_TARGET["hosts"], mikrotik_credential_id, port_list_id,
            comment="Managed by setup_credentials.py; MikroTik RouterOS gvm-scan user.",
        )
        mikrotik_task_id = ensure_task(
            gmp, MIKROTIK_TARGET["name"], config_id, mikrotik_target_id, scanner_id,
            schedule_for(MIKROTIK_TARGET["zone"]),
        )
        task_ids_by_zone.setdefault(MIKROTIK_TARGET["zone"], []).append(mikrotik_task_id)

        for fleet_target in load_fleet_targets(GVM_FLEET_DIR):
            zone = fleet_target["zone"]
            task_id = reconcile_fleet_host(
                gmp, fleet_target, config_id, scanner_id, port_list_id, schedule_for(zone),
            )
            if task_id:
                task_ids_by_zone.setdefault(zone, []).append(task_id)

        for zone, task_ids in task_ids_by_zone.items():
            ensure_zone_tag(gmp, zone, task_ids)

        if START_TASK_NAME:
            task_id = find_by_name(gmp, gmp.get_tasks, "task", START_TASK_NAME)
            if not task_id:
                raise RuntimeError(f"requested credentialed task {START_TASK_NAME!r} not found")
            gmp.start_task(task_id)
            print(f"started task {START_TASK_NAME!r} ({task_id})")

        if STATUS_TASK_NAME:
            task_id = find_by_name(gmp, gmp.get_tasks, "task", STATUS_TASK_NAME)
            if not task_id:
                raise RuntimeError(f"requested credentialed task {STATUS_TASK_NAME!r} not found")
            task = gmp.get_task(task_id)
            status = task.findtext("task/status", default="unknown")
            progress = task.findtext("task/progress", default="unknown")
            print(f"status {STATUS_TASK_NAME!r}: {status}, progress={progress}")

    print("done")


if __name__ == "__main__":
    sys.exit(main())
GVMCOV_EOF
```

### gvmcov-09-greenbone-playbook

```yaml
id: gvmcov-09-greenbone-playbook
title: Stop staging the operator root key and workstation key on greenbone-stack
depends_on: [gvmcov-08-setup-credentials]

change: >
  Run the Python edit block below against
  terraform/lxc/ansible/playbooks/deploy-greenbone-stack.yml. It removes the
  steve/openvas-workstation key vars, their file writes, -v mounts, -e flags and
  environment entries, keeps the MikroTik key, and makes changed_when also
  report "deleted". Each anchor must match exactly once or the block aborts.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-greenbone-stack.yml
  forbidden_actions:
    - "Any edit outside the credential-program section and the two var lines"

gates:
  - id: keys-gone
    cmd: "grep -c 'steve.key\\|GREENBONE_STEVE\\|openvas-workstation\\|OPENVAS_WORKSTATION' terraform/lxc/ansible/playbooks/deploy-greenbone-stack.yml"
    expect: "prints 0"
    critical: true
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-greenbone-stack.yml </dev/null"
    expect: "exit 0"
    critical: true
```

```bash
python3 - <<'EOF'
from pathlib import Path

path = Path("terraform/lxc/ansible/playbooks/deploy-greenbone-stack.yml")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "    greenbone_steve_ssh_private_key: \"{{ lookup('env', 'GREENBONE_STEVE_SSH_PRIVATE_KEY') | mandatory('GREENBONE_STEVE_SSH_PRIVATE_KEY env var is required') }}\"\n"
        "    greenbone_openvas_workstation_ssh_private_key: \"{{ lookup('env', 'GREENBONE_OPENVAS_WORKSTATION_SSH_PRIVATE_KEY') | mandatory('GREENBONE_OPENVAS_WORKSTATION_SSH_PRIVATE_KEY env var is required') }}\"\n",
        "",
    ),
    (
        "    # First-pass credentialed scanning deliberately reuses SSH access that\n"
        "    # already exists on managed targets.  This tag only touches\n"
        "    # greenbone-stack: it does not deploy accounts, SSH keys, or sudo policy\n",
        "    # Credentialed scanning (docs/gvm-coverage-cleanup/plan.md): per-host\n"
        "    # gvm-scan keys from OpenBao plus the MikroTik key.  This tag only touches\n"
        "    # greenbone-stack: it does not deploy accounts, SSH keys, or sudo policy\n",
    ),
    (
        "        - name: Write Steve SSH private key for credential-program\n"
        "          ansible.builtin.copy:\n"
        "            content: \"{{ greenbone_steve_ssh_private_key }}\"\n"
        "            dest: \"{{ greenbone_credential_program_tempdir.path }}/steve.key\"\n"
        "            # gvm-tools runs as an unprivileged container UID. The parent\n"
        "            # tempfile directory is mode 0700 and root-owned on the host, so\n"
        "            # 0644 lets only the bind-mounted container process read it.\n"
        "            mode: \"0644\"\n"
        "          no_log: true\n"
        "\n"
        "        - name: Write workstation OpenVAS SSH private key for credential-program\n"
        "          ansible.builtin.copy:\n"
        "            content: \"{{ greenbone_openvas_workstation_ssh_private_key }}\"\n"
        "            dest: \"{{ greenbone_credential_program_tempdir.path }}/openvas-workstation.key\"\n"
        "            mode: \"0644\"\n"
        "          no_log: true\n"
        "\n"
        "        - name: Write MikroTik gvm-scan SSH private key for credential-program\n"
        "          ansible.builtin.copy:\n"
        "            content: \"{{ greenbone_mikrotik_ssh_private_key }}\"\n"
        "            dest: \"{{ greenbone_credential_program_tempdir.path }}/mikrotik-gvm-scan.key\"\n"
        "            mode: \"0644\"\n"
        "          no_log: true\n",
        "        - name: Write MikroTik gvm-scan SSH private key for credential-program\n"
        "          ansible.builtin.copy:\n"
        "            content: \"{{ greenbone_mikrotik_ssh_private_key }}\"\n"
        "            dest: \"{{ greenbone_credential_program_tempdir.path }}/mikrotik-gvm-scan.key\"\n"
        "            # gvm-tools runs as an unprivileged container UID. The parent\n"
        "            # tempfile directory is mode 0700 and root-owned on the host, so\n"
        "            # 0644 lets only the bind-mounted container process read it.\n"
        "            mode: \"0644\"\n"
        "          no_log: true\n",
    ),
    (
        "        - name: Generate the fleet-targets directory (targets.json + per-stack key/sudopass)\n",
        "        - name: Generate the fleet-targets directory (targets.json + per-host key)\n",
    ),
    (
        "              -v {{ greenbone_credential_program_tempdir.path }}/steve.key:/tmp/steve.key:ro\n"
        "              -v {{ greenbone_credential_program_tempdir.path }}/openvas-workstation.key:/tmp/openvas-workstation.key:ro\n",
        "",
    ),
    (
        "              -e GREENBONE_STEVE_KEY_PATH\n"
        "              -e GREENBONE_OPENVAS_WORKSTATION_KEY_PATH\n",
        "",
    ),
    (
        "            GREENBONE_STEVE_KEY_PATH: /tmp/steve.key\n"
        "            GREENBONE_OPENVAS_WORKSTATION_KEY_PATH: /tmp/openvas-workstation.key\n",
        "",
    ),
    (
        "            'created credential' in greenbone_credential_program_setup.stdout\n",
        "            'created credential' in greenbone_credential_program_setup.stdout\n"
        "            or 'deleted ' in greenbone_credential_program_setup.stdout\n",
    ),
]
for old, new in replacements:
    count = text.count(old)
    assert count == 1, f"expected exactly 1 match, found {count}: {old[:80]!r}"
    text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
print("deploy-greenbone-stack.yml updated")
EOF
```

### gvmcov-10-scan-program-zones

```yaml
id: gvmcov-10-scan-program-zones
title: CIDR scans for every zone; NAS and pve-test-vm out of the exclusions
depends_on: []

change: >
  Overwrite terraform/lxc/ansible/files/greenbone-scan-setup/setup_scan_program.py
  with the exact content below. Adds pentest/media/cse/connector/apps zones,
  FIXTURE_EXCLUDE for pentest_seg fixtures, lan tier_a_exclude reduced to
  MikroTik + pve, and rebuild-on-change when a target's hosts/excludes differ.

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/greenbone-scan-setup/setup_scan_program.py
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: compile
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/greenbone-scan-setup/setup_scan_program.py"
    expect: "exit 0"
    critical: true
  - id: zones
    cmd: "grep -c '\"key\": \"' terraform/lxc/ansible/files/greenbone-scan-setup/setup_scan_program.py"
    expect: "prints 12"
    critical: true
```

```bash
cat > terraform/lxc/ansible/files/greenbone-scan-setup/setup_scan_program.py <<'GVMCOV_EOF'
#!/usr/bin/env python3
"""Idempotent setup for the LAN/VLAN discovery + vulnerability scan program
-- docs/greenbone-stack/network-scan-rollout-plan.md Phase 2, extended by
docs/gvm-coverage-cleanup/plan.md (2026-10-11: added pentest_seg,
media_seg, cse_seg, connector_seg and apps_seg; dropped the NAS and the
retired pve-test-vm from the lan full-vuln exclusions).

Run inside the greenbone-stack compose's throwaway gvm-tools container:

    docker compose run --rm \
      -v <this file>:/tmp/setup_scan_program.py:ro \
      -e GVM_USERNAME=admin -e GVM_PASSWORD=... \
      gvm-tools python3 /tmp/setup_scan_program.py

Creates one Discovery and one Full-and-fast Target+Task per zone/LAN.
Discovery Tasks stay unscheduled; full-vuln Tasks get their weekly
Schedule from setup_schedules.py (run after this file by the playbook).

Reconciles, not create-only: if an existing Target's hosts/exclude_hosts
differ from this file, its Task and Target are deleted (ultimate) and
recreated -- gvmd refuses to change hosts on a Target in use by a Task.
A Task that is currently running is left alone with a WARN and picked up
on the next run. setup_schedules.py re-attaches the weekly Schedule to a
recreated full-vuln Task by name.
"""
import os
import sys

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]

DISCOVERY_CONFIG_NAME = "Discovery"
FULL_CONFIG_NAME = "Full and fast"
SCANNER_NAME = "OpenVAS Default"

# GVM's own standard pairing for "Full and fast"; create_target has no
# implicit port default (confirmed live 2026-08-16).
PORT_LIST_NAME = "All TCP and Nmap top 100 UDP"

# GVM's standard combined default. Exact enum string confirmed live
# 2026-08-16 against python-gvm's AliveTest enum.
ALIVE_TESTS = "ICMP, TCP-ACK Service & ARP Ping"

ACTIVE_TASK_STATUSES = {"Running", "Requested", "Queued", "Stop Requested", "Delete Requested"}

# Tier A hosts are excluded from the Full-and-fast target only -- still
# covered by Discovery, and every one of them has its own daily
# credentialed scan (setup_credentials.py).
ZONES = [
    {"key": "build_seg", "cidr": "192.168.10.0/24", "tier_a_exclude": []},
    {
        "key": "mgmt_seg",
        "cidr": "192.168.20.0/24",
        "tier_a_exclude": ["192.168.20.10", "192.168.20.11"],  # Authentik, step-ca
    },
    {"key": "edge_seg", "cidr": "192.168.30.0/24", "tier_a_exclude": ["192.168.30.10"]},  # Traefik
    {"key": "infra_seg", "cidr": "192.168.40.0/24", "tier_a_exclude": ["192.168.40.10"]},  # Harbor
    {"key": "ai_seg", "cidr": "192.168.50.0/24", "tier_a_exclude": []},
    {"key": "game_seg", "cidr": "192.168.60.0/24", "tier_a_exclude": []},
    {"key": "pentest_seg", "cidr": "192.168.70.0/24", "tier_a_exclude": []},
    {"key": "media_seg", "cidr": "192.168.80.0/24", "tier_a_exclude": []},
    {"key": "cse_seg", "cidr": "192.168.100.0/24", "tier_a_exclude": []},
    {"key": "connector_seg", "cidr": "192.168.110.0/24", "tier_a_exclude": []},
    {"key": "apps_seg", "cidr": "192.168.120.0/24", "tier_a_exclude": []},
    {
        "key": "lan",
        "cidr": "192.168.1.0/24",
        "tier_a_exclude": ["192.168.1.1", "192.168.1.2"],  # MikroTik, pve
    },
]

# Permanent red-team / test fixtures -- excluded from every routine target
# (both tiers) in their zone; their findings are known/meaningless noise
# and they stay reachable via the on-demand gvm-bridge/PentAGI path only.
FIXTURE_EXCLUDE = {
    "lan": ["192.168.1.113", "192.168.1.55"],  # Metasploitable2, harness-target
    # harness-target-pve, pentagi-upstream-control, cse-kali
    "pentest_seg": ["192.168.70.12", "192.168.70.13", "192.168.70.210"],
}


def resolve_id(gmp, getter, name, tag):
    response = getter(filter_string=f'name="{name}"')
    el = response.find(tag)
    if el is None:
        raise RuntimeError(f"{tag} {name!r} not found on this gvmd")
    return el.get("id")


def find_by_name(gmp, getter, tag, name):
    response = getter(filter_string=f'name="{name}"')
    el = response.find(tag)
    return el.get("id") if el is not None else None


def _host_set(text):
    return {h.strip() for h in (text or "").split(",") if h.strip()}


def target_matches(gmp, target_id, cidr, exclude_hosts):
    target = gmp.get_target(target_id)
    return (
        _host_set(target.findtext("target/hosts")) == {cidr}
        and _host_set(target.findtext("target/exclude_hosts")) == set(exclude_hosts)
    )


def ensure_target_and_task(gmp, name, cidr, exclude_hosts, config_id, scanner_id, port_list_id):
    """exclude_hosts is a list[str] of individual addresses -- a pre-joined
    comma string fails live with GvmResponseError 400 "Error in host
    specification" (confirmed 2026-08-16)."""
    target_id = find_by_name(gmp, gmp.get_targets, "target", name)
    task_id = find_by_name(gmp, gmp.get_tasks, "task", name)

    if target_id and not target_matches(gmp, target_id, cidr, exclude_hosts):
        if task_id:
            status = gmp.get_task(task_id).findtext("task/status", default="unknown")
            if status in ACTIVE_TASK_STATUSES:
                print(f"WARN: task {name!r} is {status}; its target is stale, leaving it alone this run")
                return
            gmp.delete_task(task_id, ultimate=True)
            print(f"deleted task {name!r} ({task_id}) -- target hosts/excludes changed")
            task_id = None
        gmp.delete_target(target_id, ultimate=True)
        print(f"deleted target {name!r} ({target_id}) -- hosts/excludes changed")
        target_id = None

    if target_id:
        print(f"target {name!r} already exists ({target_id}), up to date")
    else:
        kwargs = {"exclude_hosts": exclude_hosts} if exclude_hosts else {}
        response = gmp.create_target(
            name=name,
            hosts=[cidr],
            alive_test=ALIVE_TESTS,
            port_list_id=port_list_id,
            **kwargs,
        )
        target_id = response.get("id")
        print(f"created target {name!r} ({target_id})")

    if task_id:
        print(f"task {name!r} already exists ({task_id}), skipping")
    else:
        response = gmp.create_task(name=name, config_id=config_id, target_id=target_id, scanner_id=scanner_id)
        print(f"created task {name!r} ({response.get('id')})")


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        discovery_config_id = resolve_id(gmp, gmp.get_scan_configs, DISCOVERY_CONFIG_NAME, "config")
        full_config_id = resolve_id(gmp, gmp.get_scan_configs, FULL_CONFIG_NAME, "config")
        scanner_id = resolve_id(gmp, gmp.get_scanners, SCANNER_NAME, "scanner")
        port_list_id = resolve_id(gmp, gmp.get_port_lists, PORT_LIST_NAME, "port_list")

        for zone in ZONES:
            key, cidr = zone["key"], zone["cidr"]
            fixtures = FIXTURE_EXCLUDE.get(key, [])

            ensure_target_and_task(
                gmp, f"LAN scan: {key} discovery", cidr, list(fixtures),
                discovery_config_id, scanner_id, port_list_id,
            )
            ensure_target_and_task(
                gmp, f"LAN scan: {key} full-vuln", cidr, list(zone["tier_a_exclude"]) + list(fixtures),
                full_config_id, scanner_id, port_list_id,
            )

    print("done")


if __name__ == "__main__":
    sys.exit(main())
GVMCOV_EOF
```

### gvmcov-11-schedules

```yaml
id: gvmcov-11-schedules
title: Weekly full-vuln schedules for the five new zones
depends_on: [gvmcov-10-scan-program-zones]

change: >
  Overwrite terraform/lxc/ansible/files/greenbone-scan-setup/setup_schedules.py
  with the exact content below. ZONE_FIRST_RUN_LOCAL keeps the existing seven
  zones' dates and adds the five new zones on Wednesday nights from
  2026-10-14 22:00 NZT, one hour apart.

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/greenbone-scan-setup/setup_schedules.py
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: compile
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/greenbone-scan-setup/setup_schedules.py"
    expect: "exit 0"
    critical: true
```

```bash
cat > terraform/lxc/ansible/files/greenbone-scan-setup/setup_schedules.py <<'GVMCOV_EOF'
#!/usr/bin/env python3
"""Attach weekly recurring GMP Schedules to the vulnerability
("full-vuln") Tasks created by setup_scan_program.py --
docs/greenbone-stack/network-scan-rollout-plan.md Phase 4, extended by
docs/gvm-coverage-cleanup/plan.md (2026-10-11: five new zones).

Original operator instruction, 2026-08-16: schedule only the
vulnerability scans (not Discovery), staggered an hour apart, LAN segment
last, first occurrence 22:00 local time, recurring weekly. The five zones
added 2026-10-11 run on a separate night (Wednesday) with the same
one-hour stagger, so the Sunday night batch doesn't grow.

Idempotent: looks up an existing Schedule by exact name first and reuses
it (does not update its icalendar/timezone if already present -- delete
the stale Schedule first if a time ever needs to change).
modify_task(schedule_id=...) runs every time, so a full-vuln Task that
setup_scan_program.py recreated gets its Schedule re-attached.

DURATION is deliberately omitted from every VEVENT -- gvmd defaults it to
PT0S, which never force-stops an in-progress scan on a recurring
schedule (resolved 2026-08-16 by reading gvmd's scheduler source).
"""
import os
import sys
from datetime import datetime
from datetime import timezone as dt_timezone

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]

# Naive local wall-clock times; gvmd applies SCAN_TIMEZONE to them.
SCAN_TIMEZONE = "Pacific/Auckland"

# First occurrence per zone; RRULE:FREQ=WEEKLY repeats it. The first seven
# are unchanged from 2026-08-16 (their Schedules already exist live).
ZONE_FIRST_RUN_LOCAL = {
    "build_seg": datetime(2026, 8, 16, 22, 0, 0),
    "mgmt_seg": datetime(2026, 8, 16, 23, 0, 0),
    "edge_seg": datetime(2026, 8, 17, 0, 0, 0),
    "infra_seg": datetime(2026, 8, 17, 1, 0, 0),
    "ai_seg": datetime(2026, 8, 17, 2, 0, 0),
    "game_seg": datetime(2026, 8, 17, 3, 0, 0),
    "lan": datetime(2026, 8, 17, 4, 0, 0),
    "pentest_seg": datetime(2026, 10, 14, 22, 0, 0),
    "media_seg": datetime(2026, 10, 14, 23, 0, 0),
    "cse_seg": datetime(2026, 10, 15, 0, 0, 0),
    "connector_seg": datetime(2026, 10, 15, 1, 0, 0),
    "apps_seg": datetime(2026, 10, 15, 2, 0, 0),
}


def find_by_name(gmp, getter, tag, name):
    response = getter(filter_string=f'name="{name}"')
    el = response.find(tag)
    return el.get("id") if el is not None else None


def ensure_schedule(gmp, name, dtstart_local):
    existing = find_by_name(gmp, gmp.get_schedules, "schedule", name)
    if existing:
        print(f"schedule {name!r} already exists ({existing}), skipping")
        return existing

    uid = f"{name.replace(' ', '-').replace(':', '')}@gibbsgreatly.xyz"
    dtstamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart = dtstart_local.strftime("%Y%m%dT%H%M%S")
    icalendar = (
        "BEGIN:VCALENDAR\r\n"
        "PRODID:-//Greenbone.net//NONSGML Greenbone Security Manager //EN\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{dtstart}\r\n"
        "RRULE:FREQ=WEEKLY\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    response = gmp.create_schedule(name=name, icalendar=icalendar, timezone=SCAN_TIMEZONE)
    schedule_id = response.get("id")
    print(f"created schedule {name!r} ({schedule_id}), first run {dtstart} {SCAN_TIMEZONE}, weekly")
    return schedule_id


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        for key, dtstart_local in ZONE_FIRST_RUN_LOCAL.items():
            task_name = f"LAN scan: {key} full-vuln"
            schedule_name = f"LAN scan: {key} full-vuln weekly"

            task_id = find_by_name(gmp, gmp.get_tasks, "task", task_name)
            if not task_id:
                raise RuntimeError(f"task {task_name!r} not found -- run setup_scan_program.py first")

            schedule_id = ensure_schedule(gmp, schedule_name, dtstart_local)
            gmp.modify_task(task_id, schedule_id=schedule_id)
            print(f"attached schedule {schedule_name!r} to task {task_name!r}")

    print("done")


if __name__ == "__main__":
    sys.exit(main())
GVMCOV_EOF
```

### gvmcov-12-firewall-reach

```yaml
id: gvmcov-12-firewall-reach
title: Let greenbone-stack reach media_seg, cse_seg, connector_seg and apps_seg
depends_on: []

change: >
  Run the Python edit block below against
  ansible/00-initial-setup/mikrotik-firewall-greenbone-lan-scan-reach.yml: add
  four greenbone_scan_destinations entries (192.168.80/100/110/120.0/24) after
  game_seg and update the comment above the list.

scope:
  allowed_paths:
    - ansible/00-initial-setup/mikrotik-firewall-greenbone-lan-scan-reach.yml
  forbidden_actions:
    - "Running the playbook (operator runbook only -- it changes the live router)"

gates:
  - id: destinations
    cmd: "grep -c '^      - zone: ' ansible/00-initial-setup/mikrotik-firewall-greenbone-lan-scan-reach.yml"
    expect: "prints 11"
    critical: true
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/mikrotik-firewall-greenbone-lan-scan-reach.yml </dev/null"
    expect: "exit 0"
    critical: true
```

```bash
python3 - <<'EOF'
from pathlib import Path

path = Path("ansible/00-initial-setup/mikrotik-firewall-greenbone-lan-scan-reach.yml")
text = path.read_text(encoding="utf-8")

old = (
    "    # One entry per destination. game_seg and the flat LAN have no\n"
    "    # LAB_SUBNET_*_CIDR env var (matching pve.yaml's own hardcoding of\n"
    "    # 192.168.60.0/24 for game_seg), so those two are hardcoded here too.\n"
)
new = (
    "    # One entry per destination. game_seg, media_seg, cse_seg,\n"
    "    # connector_seg, apps_seg and the flat LAN have no LAB_SUBNET_*_CIDR\n"
    "    # env var (matching pve.yaml's own hardcoding of 192.168.60.0/24 for\n"
    "    # game_seg), so those are hardcoded here too. media_seg, cse_seg,\n"
    "    # connector_seg and apps_seg added 2026-10-11\n"
    "    # (docs/gvm-coverage-cleanup/plan.md) -- before that GVM could not\n"
    "    # reach media-stack-lab, torrent-stack-lab, newt-connector,\n"
    "    # nextcloud-stack, cse-controller or cse-code-eval at all.\n"
)
assert text.count(old) == 1
text = text.replace(old, new)

old = (
    "      - zone: game_seg\n"
    "        cidr: \"192.168.60.0/24\"\n"
)
new = (
    "      - zone: game_seg\n"
    "        cidr: \"192.168.60.0/24\"\n"
    "      - zone: media_seg\n"
    "        cidr: \"192.168.80.0/24\"\n"
    "      - zone: cse_seg\n"
    "        cidr: \"192.168.100.0/24\"\n"
    "      - zone: connector_seg\n"
    "        cidr: \"192.168.110.0/24\"\n"
    "      - zone: apps_seg\n"
    "        cidr: \"192.168.120.0/24\"\n"
)
assert text.count(old) == 1
text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
print("greenbone reach playbook updated")
EOF
```

### gvmcov-13-bridge-endpoint

```yaml
id: gvmcov-13-bridge-endpoint
title: gvm-bridge GET /tasks/credentialed for the coverage check
depends_on: []

change: >
  Run the Python edit block below. It inserts a tasks_credentialed() route into
  terraform/lxc/ansible/files/gvm-bridge/app.py immediately before the final
  `if __name__ == "__main__":` block (it must come before that line so the
  route is registered when the file is run directly).

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/gvm-bridge/app.py
  forbidden_actions:
    - "Any edit to existing routes"

gates:
  - id: compile
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/gvm-bridge/app.py"
    expect: "exit 0"
    critical: true
  - id: route-before-main
    cmd: "python3 -c \"t=open('terraform/lxc/ansible/files/gvm-bridge/app.py').read(); print(t.index('/tasks/credentialed') < t.index('if __name__'))\""
    expect: "prints True"
    critical: true
```

```bash
python3 - <<'PYEOF'
from pathlib import Path

path = Path("terraform/lxc/ansible/files/gvm-bridge/app.py")
text = path.read_text(encoding="utf-8")
assert "/tasks/credentialed" not in text, "endpoint already present"
anchor = "\n\nif __name__ == \"__main__\":\n"
assert text.count(anchor) == 1
endpoint = """

@app.get("/tasks/credentialed")
def tasks_credentialed():
    # Coverage-check source for gvm_findings_sync.py
    # (docs/gvm-coverage-cleanup/plan.md): every credentialed Task with its
    # status, schedule and last report's scan start. get_tasks only --
    # get_reports is never called anywhere in this file (gvmd #2273, see
    # scan_results()). Credentialed Task names all start with
    # "Credentialed scan: " (setup_credentials.py,
    # setup_oci_pangolin_credentialed.py).
    with _open_gmp() as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)
        response = gmp.get_tasks(filter_string='name~"Credentialed scan: " rows=-1')

    tasks = []
    for t in response.findall("task"):
        tasks.append(
            {
                "name": t.findtext("name"),
                "status": t.findtext("status"),
                "schedule": t.findtext("schedule/name") or None,
                "last_report_scan_start": t.findtext("last_report/report/scan_start") or None,
            }
        )
    return jsonify({"tasks": tasks})"""
text = text.replace(anchor, endpoint.rstrip("\n") + "\n" + anchor)
path.write_text(text, encoding="utf-8")
print("gvm-bridge endpoint added")
PYEOF
```

### gvmcov-14-coverage-check

```yaml
id: gvmcov-14-coverage-check
title: Fail loudly when credentialed scans stop authenticating or running
depends_on: [gvmcov-13-bridge-endpoint]

change: >
  Run the Python edit block below against
  terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py. It
  adds the five new zones to ZONES and the pentest_seg fixtures to
  REDTEAM_EXCLUDE, inserts the coverage functions before main(), and makes
  main() write es-findings-sync-state/greenbone-coverage, print COVERAGE
  lines, and exit 3 when any credentialed task is failing.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py
  forbidden_actions:
    - "Any change to build_documents/bulk_upsert/update_sync_state"

gates:
  - id: compile
    cmd: "python3 -m py_compile terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py"
    expect: "exit 0"
    critical: true
  - id: wired
    cmd: "grep -c 'evaluate_coverage\\|put_coverage_state\\|fetch_credentialed_tasks' terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py"
    expect: "prints 6"
    critical: true
```

```bash
python3 - <<'PYEOF'
from pathlib import Path

path = Path("terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py")
text = path.read_text(encoding="utf-8")
assert "evaluate_coverage" not in text, "coverage check already present"

def replace_once(old, new):
    global text
    count = text.count(old)
    assert count == 1, f"expected exactly 1 match, found {count}: {old[:80]!r}"
    text = text.replace(old, new)

replace_once(
    '    {"key": "game_seg", "cidr": "192.168.60.0/24"},\n'
    '    {"key": "lan", "cidr": "192.168.1.0/24"},\n',
    '    {"key": "game_seg", "cidr": "192.168.60.0/24"},\n'
    '    {"key": "pentest_seg", "cidr": "192.168.70.0/24"},\n'
    '    {"key": "media_seg", "cidr": "192.168.80.0/24"},\n'
    '    {"key": "cse_seg", "cidr": "192.168.100.0/24"},\n'
    '    {"key": "connector_seg", "cidr": "192.168.110.0/24"},\n'
    '    {"key": "apps_seg", "cidr": "192.168.120.0/24"},\n'
    '    {"key": "lan", "cidr": "192.168.1.0/24"},\n',
)
replace_once(
    'REDTEAM_EXCLUDE = ["192.168.1.113", "192.168.1.55"]\n',
    '# Every FIXTURE_EXCLUDE address from setup_scan_program.py, flattened.\n'
    'REDTEAM_EXCLUDE = ["192.168.1.113", "192.168.1.55", "192.168.70.12", "192.168.70.13", "192.168.70.210"]\n',
)

COVERAGE_BLOCK = '''

# --- Credentialed-scan coverage check (docs/gvm-coverage-cleanup/plan.md) ---
# Found 2026-10-11: every scheduled fleet credentialed scan since
# 2026-09-30 had silently failed authentication ("SSH Login Failed For
# Authenticated Checks", zero Local Security Check results) for 11 days
# with nothing noticing. This check runs after every ingest and makes that
# failure loud: one summary document in es-findings-sync-state
# (_id greenbone-coverage) plus a non-zero exit, which fails the
# gvm-findings-ingest systemd unit.
AUTH_OK_NAME = "SSH Login Successful For Authenticated Checks"
AUTH_FAIL_NAME = "SSH Login Failed For Authenticated Checks"
# Unscheduled by design (docs/greenbone-stack/README.md) -- never "stale".
COVERAGE_IGNORE_TASKS = {"Credentialed scan: OCI Pangolin public edge"}
# Daily schedules; 48h tolerates one skipped night before alerting.
COVERAGE_MAX_AGE_HOURS = 48
COVERAGE_ACTIVE_STATUSES = {"Running", "Requested", "Queued"}
COVERAGE_FAILING = {"never_run", "auth_failed", "no_auth_evidence", "stale", "unscheduled"}


def fetch_credentialed_tasks(bridge_url: str, *, timeout: int = 60) -> list[dict]:
    req = urllib.request.Request(f"{bridge_url.rstrip('/')}/tasks/credentialed", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
        body = json.loads(resp.read())
    return body.get("tasks", [])


def _parse_gmp_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate_coverage(tasks: list[dict], raw_results: list[dict], *, now: datetime) -> list[dict]:
    """One row per credentialed Task: {"task", "status", "coverage",
    "last_scan_start", "results_in_last_run"}. coverage is "ok",
    "running", or one of COVERAGE_FAILING."""
    results_by_task: dict[str, list[dict]] = {}
    for r in raw_results:
        results_by_task.setdefault(r.get("task_name") or "", []).append(r)

    rows = []
    for task in tasks:
        name = task.get("name") or ""
        if name in COVERAGE_IGNORE_TASKS:
            continue
        started = _parse_gmp_time(task.get("last_report_scan_start"))
        run_results = []
        if started is not None:
            for r in results_by_task.get(name, []):
                created = _parse_gmp_time(r.get("creation_time"))
                if created is not None and created >= started:
                    run_results.append(r)
        names = {r.get("name") for r in run_results}

        if task.get("status") in COVERAGE_ACTIVE_STATUSES:
            coverage = "running"
        elif not task.get("schedule"):
            coverage = "unscheduled"
        elif started is None:
            coverage = "never_run"
        elif AUTH_FAIL_NAME in names:
            coverage = "auth_failed"
        elif AUTH_OK_NAME not in names:
            coverage = "no_auth_evidence"
        elif (now - started).total_seconds() > COVERAGE_MAX_AGE_HOURS * 3600:
            coverage = "stale"
        else:
            coverage = "ok"
        rows.append(
            {
                "task": name,
                "status": task.get("status"),
                "coverage": coverage,
                "last_scan_start": task.get("last_report_scan_start"),
                "results_in_last_run": len(run_results),
            }
        )
    return rows


def put_coverage_state(base_url: str, rows: list[dict], *, auth_header: str, verify_tls: bool, checked_at: str) -> None:
    failing = [row for row in rows if row["coverage"] in COVERAGE_FAILING]
    doc = {
        "source": "greenbone-coverage",
        "checked_at": checked_at,
        "status": "ok" if not failing else "failing",
        "tasks_total": len(rows),
        "tasks_failing": len(failing),
        "failing": failing,
        "tasks": rows,
    }
    url = f"{base_url}/es-findings-sync-state/_doc/greenbone-coverage"
    req = urllib.request.Request(url, data=json.dumps(doc).encode("utf-8"), method="PUT")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15):  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
            pass
    except urllib.error.HTTPError as exc:
        print(f"WARN: failed to write coverage state: {exc}", file=sys.stderr)
'''
replace_once(
    "\n\ndef main() -> int:\n",
    COVERAGE_BLOCK.rstrip("\n") + "\n\n\ndef main() -> int:\n",
)

replace_once(
    '    print(f"Done — raw={len(raw_results)} findings_indexed={indexed} errors={errors} dry_run={args.dry_run}")\n'
    '    return 1 if errors > 0 else 0\n',
    '    coverage_failing = 0\n'
    '    try:\n'
    '        credentialed_tasks = fetch_credentialed_tasks(args.gvm_bridge_url)\n'
    '    except Exception as exc:  # noqa: BLE001\n'
    '        print(f"ERROR: failed to fetch credentialed tasks from gvm-bridge: {exc}", file=sys.stderr)\n'
    '        credentialed_tasks = None\n'
    '    if credentialed_tasks is not None:\n'
    '        rows = evaluate_coverage(credentialed_tasks, raw_results, now=datetime.now(timezone.utc))\n'
    '        for row in rows:\n'
    '            print(\n'
    '                f"COVERAGE {row[\'coverage\'].upper()}: {row[\'task\']} (status={row[\'status\']}, "\n'
    '                f"last_scan_start={row[\'last_scan_start\']}, results={row[\'results_in_last_run\']})"\n'
    '            )\n'
    '        coverage_failing = sum(1 for row in rows if row["coverage"] in COVERAGE_FAILING)\n'
    '        if not args.dry_run:\n'
    '            put_coverage_state(\n'
    '                es_base, rows, auth_header=es_auth, verify_tls=not args.no_verify_tls, checked_at=_now_iso()\n'
    '            )\n'
    '\n'
    '    print(\n'
    '        f"Done — raw={len(raw_results)} findings_indexed={indexed} errors={errors} "\n'
    '        f"coverage_failing={coverage_failing} dry_run={args.dry_run}"\n'
    '    )\n'
    '    if errors > 0 or credentialed_tasks is None:\n'
    '        return 1\n'
    '    # 3 = ingest succeeded but credentialed-scan coverage is failing; fails\n'
    '    # the gvm-findings-ingest systemd unit so it shows up in\n'
    '    # `systemctl --failed` (docs/gvm-coverage-cleanup/plan.md).\n'
    '    return 3 if coverage_failing else 0\n',
)

path.write_text(text, encoding="utf-8")
print("gvm_findings_sync.py updated")
PYEOF
```

### gvmcov-15-weekly-cadence

```yaml
id: gvmcov-15-weekly-cadence
title: Weekly credentialed scans, max 4 hosts per slot; 8-day coverage window
depends_on: [gvmcov-08-setup-credentials, gvmcov-14-coverage-check]

change: >
  Run the Python edit block below. It replaces setup_credentials.py's daily
  ZONE_SCHEDULE_TIMES/ensure_schedule with weekly ZONE_WEEKLY_SLOTS/
  ensure_weekly_schedule, with hosts dealt round-robin across a zone's slots
  and the old "Daily fleet scan: <zone>" schedules deleted once unused. It
  also sets gvm_findings_sync.py's COVERAGE_MAX_AGE_HOURS to 8 * 24.

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py
    - terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: compile
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py"
    expect: "exit 0"
    critical: true
  - id: no-daily
    cmd: "grep -c 'ZONE_SCHEDULE_TIMES\\|RRULE:FREQ=DAILY\\|COVERAGE_MAX_AGE_HOURS = 48' terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py"
    expect: "prints ':0' for both files"
    critical: true
```

Operator decision 2026-10-12, made after the plan was written: the run
history showed greenbone-stack (2 cores) completing only 2–4 of 11 daily
runs for mgmt_seg's 8 simultaneous hosts, and this plan grows the fleet to
40 tasks. Slots (Pacific/Auckland; Monday and Thursday mornings are left
for the weekly CIDR program):

| Night (local start) | Slots |
| --- | --- |
| Tue | lan #1 00:30 (4), mgmt #1 03:00 (3), cse 05:00 (2), build 06:00 (1) |
| Wed | lan #2 00:30 (4), mgmt #2 03:00 (3), pentest 05:00 (1), apps 06:00 (1) |
| Fri | lan #3 00:30 (3), mgmt #3 03:00 (3), connector 05:00 (1) |
| Sat | infra #1 00:30 (3), ai 03:00 (3), edge 05:00 (2) |
| Sun | infra #2 00:30 (2), game 03:00 (2), media 05:00 (2) |

Verified 2026-10-12 against a stubbed GMP with the real 39-host inventory
plus MikroTik: 40 tasks across 17 slots, max 4 per slot, correct DTSTART
weekdays, the legacy daily schedule deleted, and a second run changes
nothing.

```bash
python3 - <<'PYEOF'
from pathlib import Path

path = Path("terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py")
text = path.read_text(encoding="utf-8")
assert "ZONE_WEEKLY_SLOTS" not in text, "weekly slots already present"

def replace_once(old, new):
    global text
    count = text.count(old)
    assert count == 1, f"expected exactly 1 match, found {count}: {old[:80]!r}"
    text = text.replace(old, new)

replace_once(
    "Target/Task and gets its zone's daily Schedule (ZONE_SCHEDULE_TIMES) plus\n",
    "Target/Task and gets one of its zone's weekly Schedules (ZONE_WEEKLY_SLOTS) plus\n",
)

old_start = text.index("# Daily, staggered ~45min apart overnight")
old_end = text.index('SCHEDULE_TIMEZONE = "Pacific/Auckland"\n')
text = text[:old_start] + '''# Weekly, not daily (operator decision 2026-10-12): greenbone-stack (2 cores,
# memory-gated scan queue) completed only 2-4 of 11 daily runs for mgmt_seg's
# 8 simultaneous hosts, and this plan grows the fleet from 25 to 40 tasks.
# Each zone gets one or more (weekday, local start) slots; hosts in a zone
# are dealt round-robin across its slots (MikroTik first, then targets.json
# order) so no slot starts more than 4 hosts. Monday and Thursday mornings
# are kept free -- the weekly CIDR full-vuln program runs Sunday
# 22:00-Monday 04:00 and Wednesday 22:00-Thursday 02:00 (setup_schedules.py).
# Times are Pacific/Auckland wall clock, a real IANA zone so NZ DST
# transitions resolve correctly.
ZONE_WEEKLY_SLOTS = {
    "lan": [("TU", "00:30"), ("WE", "00:30"), ("FR", "00:30")],
    "mgmt_seg": [("TU", "03:00"), ("WE", "03:00"), ("FR", "03:00")],
    "infra_seg": [("SA", "00:30"), ("SU", "00:30")],
    "ai_seg": [("SA", "03:00")],
    "game_seg": [("SU", "03:00")],
    "edge_seg": [("SA", "05:00")],
    "media_seg": [("SU", "05:00")],
    "cse_seg": [("TU", "05:00")],
    "pentest_seg": [("WE", "05:00")],
    "connector_seg": [("FR", "05:00")],
    "build_seg": [("TU", "06:00")],
    "apps_seg": [("WE", "06:00")],
}
WEEKDAY_INDEX = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
# The pre-2026-10-12 daily schedules ("Daily fleet scan: <zone>"), deleted
# once no task uses them.
LEGACY_DAILY_SCHEDULE_ZONES = [
    "mgmt_seg", "infra_seg", "ai_seg", "media_seg", "game_seg", "edge_seg",
    "pentest_seg", "connector_seg", "build_seg", "apps_seg", "cse_seg", "lan",
]
''' + text[old_end:]

replace_once(
    '        comment="Managed credentialed task; daily per-zone schedule.",\n',
    '        comment="Managed credentialed task; weekly per-zone schedule.",\n',
)

fn_start = text.index("def ensure_schedule(gmp, zone):\n")
fn_end = text.index("def ensure_zone_tag(")
text = text[:fn_start] + '''def ensure_weekly_schedule(gmp, zone, slot_index):
    """One recurring weekly GVM Schedule per (zone, slot). Re-applies
    icalendar/timezone on every run so a corrected ZONE_WEEKLY_SLOTS value
    lands on already-created schedules too. Hand-builds the iCalendar text
    rather than depending on the `icalendar` package. DTSTART is the next
    calendar date falling on the slot's weekday (a date's weekday doesn't
    depend on timezone); gvmd applies SCHEDULE_TIMEZONE to the naive time."""
    slots = ZONE_WEEKLY_SLOTS.get(zone)
    if not slots:
        raise RuntimeError(
            f"no weekly slot configured for zone {zone!r} -- add it to "
            f"ZONE_WEEKLY_SLOTS in this file before this zone can be scheduled"
        )
    day, hhmm = slots[slot_index]
    name = f"Weekly credentialed scan: {zone} #{slot_index + 1}"
    hour, minute = hhmm.split(":")
    now = datetime.datetime.now(datetime.timezone.utc)
    first = now.date() + datetime.timedelta(days=(WEEKDAY_INDEX[day] - now.weekday()) % 7)
    icalendar = (
        "BEGIN:VCALENDAR\\r\\n"
        "VERSION:2.0\\r\\n"
        "PRODID:-//proxmox-homelab//gvm-fleet-schedule//EN\\r\\n"
        "BEGIN:VEVENT\\r\\n"
        f"UID:gvm-fleet-weekly-{zone}-{slot_index + 1}@proxmox-homelab\\r\\n"
        f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}\\r\\n"
        f"DTSTART:{first.strftime('%Y%m%d')}T{hour}{minute}00\\r\\n"
        "RRULE:FREQ=WEEKLY\\r\\n"
        "END:VEVENT\\r\\n"
        "END:VCALENDAR\\r\\n"
    )
    comment = f"Credentialed scans for zone {zone!r} slot {slot_index + 1}, weekly {day} {hhmm} {SCHEDULE_TIMEZONE}."
    existing = find_by_name(gmp, gmp.get_schedules, "schedule", name)
    if existing:
        gmp.modify_schedule(existing, icalendar=icalendar, timezone=SCHEDULE_TIMEZONE, comment=comment)
        print(f"schedule {name!r} ({existing}) updated to weekly {day} {hhmm} {SCHEDULE_TIMEZONE}")
        return existing
    response = gmp.create_schedule(name=name, icalendar=icalendar, timezone=SCHEDULE_TIMEZONE, comment=comment)
    schedule_id = response.get("id")
    print(f"created schedule {name!r} ({schedule_id}) weekly {day} {hhmm} {SCHEDULE_TIMEZONE}")
    return schedule_id


def delete_legacy_daily_schedules(gmp):
    for zone in LEGACY_DAILY_SCHEDULE_ZONES:
        name = f"Daily fleet scan: {zone}"
        schedule_id = find_by_name(gmp, gmp.get_schedules, "schedule", name)
        if not schedule_id:
            continue
        try:
            gmp.delete_schedule(schedule_id, ultimate=True)
            print(f"deleted schedule {name!r} ({schedule_id})")
        except Exception as exc:  # noqa: BLE001 -- still attached to a task left alone this run
            print(f"WARN: could not delete schedule {name!r} yet ({exc}); re-run later")


''' + text[fn_end:]

replace_once(
    "        schedule_ids_by_zone = {}\n"
    "        task_ids_by_zone = {}\n"
    "\n"
    "        def schedule_for(zone):\n"
    "            if zone not in schedule_ids_by_zone:\n"
    "                schedule_ids_by_zone[zone] = ensure_schedule(gmp, zone)\n"
    "            return schedule_ids_by_zone[zone]\n",
    "        schedule_ids = {}\n"
    "        hosts_seen_by_zone = {}\n"
    "        task_ids_by_zone = {}\n"
    "\n"
    "        def schedule_for(zone):\n"
    "            # Round-robin this zone's hosts across its weekly slots.\n"
    "            slots = ZONE_WEEKLY_SLOTS.get(zone) or [None]\n"
    "            slot_index = hosts_seen_by_zone.get(zone, 0) % len(slots)\n"
    "            hosts_seen_by_zone[zone] = hosts_seen_by_zone.get(zone, 0) + 1\n"
    "            if (zone, slot_index) not in schedule_ids:\n"
    "                schedule_ids[(zone, slot_index)] = ensure_weekly_schedule(gmp, zone, slot_index)\n"
    "            return schedule_ids[(zone, slot_index)]\n",
)
replace_once(
    "        for zone, task_ids in task_ids_by_zone.items():\n"
    "            ensure_zone_tag(gmp, zone, task_ids)\n",
    "        for zone, task_ids in task_ids_by_zone.items():\n"
    "            ensure_zone_tag(gmp, zone, task_ids)\n"
    "\n"
    "        delete_legacy_daily_schedules(gmp)\n",
)
path.write_text(text, encoding="utf-8")
print("setup_credentials.py: weekly slots")

path = Path("terraform/lxc/ansible/roles/gvm_findings_ingest/files/gvm_findings_sync.py")
text = path.read_text(encoding="utf-8")
replace_once(
    "# Daily schedules; 48h tolerates one skipped night before alerting.\n"
    "COVERAGE_MAX_AGE_HOURS = 48\n",
    "# Weekly schedules (setup_credentials.py ZONE_WEEKLY_SLOTS); 8 days\n"
    "# tolerates a run that starts late or spans midnight before alerting.\n"
    "COVERAGE_MAX_AGE_HOURS = 8 * 24\n",
)
path.write_text(text, encoding="utf-8")
print("gvm_findings_sync.py: 8-day coverage window")
PYEOF
```

### gvmcov-16-in-use-safe-deletion

```yaml
id: gvmcov-16-in-use-safe-deletion
title: Delete every task still using a target before the target; never abort the whole run on one item
depends_on: [gvmcov-15-weekly-cadence]

change: >
  Run the Python edit block below against setup_credentials.py. It adds
  tasks_using_target(), which lists tasks via get_target(tasks=True) plus
  trashcan tasks. delete_if_present() now deletes those tasks (and any
  same-named duplicates) before the target, unless one is active.
  cleanup_legacy() and each fleet host now catch GvmError, log WARN and
  continue, and main() returns 1 at the end if anything failed.

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: compile
    cmd: "python3 -m py_compile terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py"
    expect: "exit 0"
    critical: true
  - id: wired
    cmd: "grep -c 'def tasks_using_target\\|except GvmError\\|failures.append' terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py"
    expect: "prints 5"
    critical: true
```

Found live in the first OP-4 run (2026-10-12 13:28): the script deleted
the legacy task `Credentialed scan: managed Debian services`, then gvmd
refused to delete its target with `400 Target is in use`. Another task
(differently named, or in the trashcan) still referenced it, and the
uncaught error aborted the credential program before any fleet host was
reconciled. Tested against a stub that reproduces gvmd's in-use refusals:
a differently-named task and a trashed task on the legacy target are both
deleted, then the target. A legacy credential held by an unmanaged target
is logged as WARN, the fleet still reconciles, and the run exits 1. The
weekly-cadence test from gvmcov-15 still passes unchanged.

```bash
python3 - <<'PYEOF'
from pathlib import Path

path = Path("terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py")
text = path.read_text(encoding="utf-8")
assert "def tasks_using_target" not in text, "gvmcov-16 already applied"

def replace_once(old, new):
    global text
    count = text.count(old)
    assert count == 1, f"expected exactly 1 match, found {count}: {old[:80]!r}"
    text = text.replace(old, new)

replace_once(
    "from gvm.connections import UnixSocketConnection\n",
    "from gvm.connections import UnixSocketConnection\n"
    "from gvm.errors import GvmError\n",
)

old_start = text.index("def delete_if_present(gmp, kind, name):\n")
old_end = text.index("def ensure_credential(gmp, name, login, key_path):\n")
text = text[:old_start] + '''def tasks_using_target(gmp, target_id):
    """{task_id: name} for every task that references target_id, including
    tasks in the trashcan. Found live 2026-10-12 (docs/gvm-coverage-cleanup
    gvmcov-16): deleting a legacy target failed with "Target is in use"
    after its same-named task was gone -- another task (different name, or
    trashed rather than ultimately deleted) still referenced it."""
    users = {}
    target = gmp.get_target(target_id, tasks=True)
    for task in target.findall("target/tasks/task"):
        users[task.get("id")] = task.findtext("name") or "?"
    trash = gmp.get_tasks(trash=True, filter_string="rows=-1")
    for task in trash.findall("task"):
        target_el = task.find("target")
        if target_el is not None and target_el.get("id") == target_id:
            users[task.get("id")] = f"{task.findtext('name') or '?'} [trashcan]"
    return users


def delete_if_present(gmp, kind, name):
    """kind is "task", "target" or "credential". Deletes every object of
    that kind with that exact name (duplicates included). For a target,
    first deletes every task still using it. Returns False only when a task
    is active (running/queued) and so was left alone; GMP errors propagate
    to the caller."""
    getter = {"task": gmp.get_tasks, "target": gmp.get_targets, "credential": gmp.get_credentials}[kind]
    deleter = {"task": gmp.delete_task, "target": gmp.delete_target, "credential": gmp.delete_credential}[kind]
    for _ in range(10):
        object_id = find_by_name(gmp, getter, kind, name)
        if not object_id:
            return True
        if kind == "task":
            status = task_status(gmp, object_id)
            if status in ACTIVE_TASK_STATUSES:
                print(f"WARN: task {name!r} is {status}, leaving it alone this run")
                return False
        if kind == "target":
            for task_id, task_name in tasks_using_target(gmp, object_id).items():
                if not task_name.endswith("[trashcan]") and task_status(gmp, task_id) in ACTIVE_TASK_STATUSES:
                    print(f"WARN: task {task_name!r} using target {name!r} is active, leaving both alone this run")
                    return False
                gmp.delete_task(task_id, ultimate=True)
                print(f"deleted task {task_name!r} ({task_id}) -- it still used target {name!r}")
        deleter(object_id, ultimate=True)
        print(f"deleted {kind} {name!r} ({object_id})")
    raise RuntimeError(f"{kind} {name!r} still present after 10 deletions")


def cleanup_legacy(gmp, failures):
    """Best-effort: a legacy object that can't be removed is logged (and
    fails the run at the end) but never blocks the fleet reconcile."""
    for kind, name in (
        [("task", n) for n in LEGACY_TASKS_AND_TARGETS]
        + [("target", n) for n in LEGACY_TASKS_AND_TARGETS]
        + [("credential", n) for n in LEGACY_CREDENTIALS]
    ):
        try:
            delete_if_present(gmp, kind, name)
        except GvmError as exc:
            print(f"WARN: could not delete legacy {kind} {name!r}: {exc}")
            failures.append(f"legacy {kind} {name!r}")


''' + text[old_end:]

replace_once(
    "        cleanup_legacy(gmp)\n",
    "        failures = []\n"
    "        cleanup_legacy(gmp, failures)\n",
)
replace_once(
    "        for fleet_target in load_fleet_targets(GVM_FLEET_DIR):\n"
    "            zone = fleet_target[\"zone\"]\n"
    "            task_id = reconcile_fleet_host(\n"
    "                gmp, fleet_target, config_id, scanner_id, port_list_id, schedule_for(zone),\n"
    "            )\n"
    "            if task_id:\n",
    "        for fleet_target in load_fleet_targets(GVM_FLEET_DIR):\n"
    "            zone = fleet_target[\"zone\"]\n"
    "            try:\n"
    "                task_id = reconcile_fleet_host(\n"
    "                    gmp, fleet_target, config_id, scanner_id, port_list_id, schedule_for(zone),\n"
    "                )\n"
    "            except GvmError as exc:\n"
    "                print(f\"WARN: fleet host {fleet_target['name']!r} failed: {exc}\")\n"
    "                failures.append(f\"fleet host {fleet_target['name']!r}\")\n"
    "                continue\n"
    "            if task_id:\n",
)
replace_once(
    '    print("done")\n',
    '        if failures:\n'
    '            print(f"FAILED: {len(failures)} item(s): {\', \'.join(failures)}")\n'
    '            return 1\n'
    '\n'
    '    print("done")\n',
)
path.write_text(text, encoding="utf-8")
print("setup_credentials.py: in-use-safe deletion, per-item failures")
PYEOF
```

## Operator runbook (production -- not step blocks)

Run these in order, from the repo root on this branch, after
gvmcov-01…16 are committed. Each production command follows CLAUDE.md's
Preflight → approval → `TASK_APPROVAL` → after-action flow.

### OP-1: create OpenBao credentials for the 14 new hosts (OIDC write)

```bash
bao login -method=oidc -no-store
export BAO_TOKEN=<token printed by bao login>
scripts/gvm_scan_credentials_bootstrap.py \
  cse-code-eval cse-controller cse-panel-stack technitium-tiny-stack \
  host-framework host-pi-22 host-pi-23 host-pve host-pve-tiny host-workstation \
  management-stack media-stack omada-controller proxmox-backup-server
unset BAO_TOKEN
```

Expect `done: 14 succeeded, 0 failed`. Don't pass `--all`, because that
would rotate the 25 existing hosts too.

### OP-2: MikroTik reach for the four blocked zones (additive firewall rules)

```bash
TASK_APPROVAL=gvmcov-firewall ./with-secrets-prod ansible-playbook \
  ansible/00-initial-setup/mikrotik-firewall-greenbone-lan-scan-reach.yml
```

Then re-read `/ip/firewall/filter` in order and confirm each new
`greenbone-stack: LAN/VLAN discovery+vuln scan reach -> <zone>` rule
sits above the `vlan70-pentest` default-deny. Also confirm that an
established/related accept is above cse_seg's, media_seg's,
connector_seg's and apps_seg's own default-deny rules (return traffic).
That is the playbook header's own rule-ordering warning.

### OP-3: roll the gvm-scan account out to every scan host

```bash
./with-secrets-prod python3 scripts/gvm_fleet_targets_generate.py \
  --emit-inventory /tmp/gvm-scan-inventory.json   # expect 39 hosts
export ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg
# root-SSH hosts (stacks, Proxmox nodes, flat-LAN LXCs):
TASK_APPROVAL=gvmcov-accounts ./with-secrets-prod ansible-playbook \
  -i /tmp/gvm-scan-inventory.json terraform/lxc/ansible/playbooks/deploy-gvm-scan-accounts.yml \
  --limit '!host-workstation:!host-framework:!host-pi-22:!host-pi-23'
# sudo hosts, one at a time (each has its own become password):
for h in host-framework host-pi-22 host-pi-23 host-workstation; do
  TASK_APPROVAL=gvmcov-accounts ./with-secrets-prod ansible-playbook \
    -i /tmp/gvm-scan-inventory.json terraform/lxc/ansible/playbooks/deploy-gvm-scan-accounts.yml \
    --limit "$h" -K
done
```

This also removes `/etc/sudoers.d/gvm-scan` and the password from the
existing 25 hosts. Expected per-host trouble spots, which don't block the
other hosts:

- management-stack, media-stack, proxmox-backup-server and
  omada-controller have never been Ansible-managed, so root SSH with the
  lab key is unconfirmed.
- The Pis use the `ansible` user.
- The workstation is Garuda (Arch). Greenbone's distro-package LSC
  coverage for Arch is expected to be thin, so check the first report.

### OP-4: redeploy greenbone-stack (full play)

```bash
TASK_APPROVAL=gvmcov-greenbone ./with-secrets-prod scripts/provision.sh --stack greenbone-stack
```

This needs the full play, not just tags, because gvm-bridge is rebuilt in
the main compose play. Expected output:

- the scan program deletes and recreates `LAN scan: lan full-vuln`
  (excludes changed) and creates the five new zones' targets and tasks
- schedules attach to every full-vuln task
- the credential program deletes the 4 legacy tasks/targets and 3 legacy
  credentials, and rebuilds every fleet host ("rebuilding GVM objects")

Any task that is mid-scan prints WARN and is picked up on the next run.

### OP-5: verify

1. **Idempotency.** Re-run only the two GMP programs:

   ```bash
   ANSIBLE_TAGS=scan-program,credential-program TASK_APPROVAL=gvmcov-greenbone \
     ./with-secrets-prod scripts/provision.sh --stack greenbone-stack
   ```

   Every fleet host should print `up to date`, every LAN target
   `up to date`, and nothing should print `deleted`. If anything rebuilds
   twice in a row, stop: the fingerprint or host comparison is unstable and
   would destroy report history every deploy.
2. **One real credentialed scan.** Start one task with
   `GREENBONE_START_TASK_NAME="Credentialed scan: fleet/apt-cacher-stack"`
   on the same tagged command. Once it finishes,
   `curl -s http://192.168.70.11:8010/tasks/credentialed` should show its
   `last_report_scan_start`. Its results (gvm-bridge `/findings/all`,
   filtered to that task) must include
   `SSH Login Successful For Authenticated Checks` and
   `(Linux/Unix SSH Login)` detections, and must not include
   `SSH Login Failed For Authenticated Checks`. In Wazuh, that host's
   gvm-scan session must show no `su` line. If `last_report_scan_start` is
   null for a task that has run, gvm-bridge's `last_report/report/scan_start`
   path is wrong for this gvmd version, so fix gvmcov-13 before trusting the
   coverage check.
3. **Coverage check, after the first full week.** After the 19:00 UTC
   `gvm-findings-ingest` run, read
   `es-findings-sync-state/_doc/greenbone-coverage`. Expect
   `"status": "ok"`. Until each host's weekly slot has come round, the check
   shows `never_run` for it, so the first week fails by design. On greenbone-stack,
   `systemctl status gvm-findings-ingest` should not be failed (exit 3
   means coverage is failing).
4. **New zones.** After Wednesday night's CIDR runs, the pentest/media/cse/
   connector/apps full-vuln tasks have reports, and media-stack-lab,
   torrent-stack-lab, newt-connector, nextcloud-stack, cse-controller and
   cse-code-eval appear in results.
5. Record results in README.md's Hand-backs and Status. Then replace every
   "planned, not yet executed" status pointer that names this workspace:
   - docs/greenbone-stack/README.md ("Scan program status")
   - docs/greenbone-stack/network-scan-rollout-plan.md (Status block)
   - docs/lxc-scan-and-monitoring-rollout/README.md and plan.md (corrections)
   - docs/opensearch-stack/README.md (GVM caveat)
   - terraform/lxc/stacks/greenbone-stack/STACK_CONTRACT.md (gvm-bridge row)

   `grep -rn "gvm-coverage-cleanup" docs terraform/lxc/stacks` lists them.

## Phase 2 runbook (VLAN-grouped credentials, 2026-10-12)

Operator decision 2026-10-12: one shared `gvm-scan` key per VLAN/zone
instead of per host. Code in 1a5b263c (implemented directly by Claude and
stub-tested from the live per-host state, not as step blocks; see
README.md). Run R1–R3 back to back in one sitting. After R2 each host
trusts only its zone key, so the per-host GVM tasks would fail
authentication until R3 replaces them. Avoid the overnight windows: the
first Phase 2 slot is Tuesday 00:30 (lan).

### R1: create the 12 zone keys in OpenBao (operator, OIDC write)

```bash
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
LAB_IP_OPENBAO=192.168.20.16 scripts/gvm_scan_credentials_bootstrap.py --all
unset BAO_TOKEN
./with-secrets-prod python3 scripts/gvm_fleet_targets_generate.py \
  --emit-inventory /tmp/gvm-scan-inventory.json --out-dir /tmp/gvm-zone-check \
  && ls /tmp/gvm-zone-check/*.key | wc -l; rm -rf /tmp/gvm-zone-check
```
Expect `done: 12 succeeded`, then `wrote 12 zones covering 39/39 hosts`
and `12`. `--all` is correct here: it means the 12 zones, none of which
exist yet.

### R2: put each host on its zone key

```bash
export ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg
TASK_APPROVAL=gvmcov-vlan-accounts ./with-secrets-prod ansible-playbook \
  -i /tmp/gvm-scan-inventory.json terraform/lxc/ansible/playbooks/deploy-gvm-scan-accounts.yml \
  --limit '!host-workstation:!host-framework:!host-pi-22:!host-pi-23'
for h in host-framework host-pi-22 host-pi-23 host-workstation; do
  TASK_APPROVAL=gvmcov-vlan-accounts ./with-secrets-prod ansible-playbook \
    -i /tmp/gvm-scan-inventory.json terraform/lxc/ansible/playbooks/deploy-gvm-scan-accounts.yml \
    --limit "$h" -K
done
```
Expect `failed=0 unreachable=0` everywhere and `changed=1` per host (the
`authorized_keys` swap). `-K` asks for that host's sudo password.

### R3: redeploy greenbone-stack (full play; gvm-bridge changed)

```bash
TASK_APPROVAL=gvmcov-vlan-greenbone ./with-secrets-prod scripts/provision.sh --stack greenbone-stack 2>&1 \
  | tee /tmp/gvmcov-r3.log
grep -E "failed=" /tmp/gvmcov-r3.log
python3 -c "import json,urllib.request as u; [print(t['status'].ljust(7), (t['schedule'] or '-').ljust(32), len(t['target_hosts']), t['name']) for t in json.load(u.urlopen('http://192.168.70.11:8010/tasks/credentialed'))['tasks']]"
```
Expect `failed=0` and 14 tasks: 12 `Credentialed scan: <zone>` (each on
`Weekly VLAN scan: <zone>`, with its host count), MikroTik, and OCI
(unscheduled). If R3 fails at the credential program with `FAILED: … (active)`,
a per-host task was mid-scan. Re-run with
`ANSIBLE_TAGS=credential-program` once it finishes.

### R4: verify

1. Nothing changes on a second run. Both lines must show `ok:`:
   ```bash
   ANSIBLE_TAGS=scan-program,credential-program TASK_APPROVAL=gvmcov-vlan-greenbone \
     ./with-secrets-prod scripts/provision.sh --stack greenbone-stack 2>&1 | tee /tmp/gvmcov-r4.log
   grep -A1 -E "TASK \[(Create/verify the LAN/VLAN scan program|Create credentialed targets)" /tmp/gvmcov-r4.log
   ```
2. One live zone scan. edge_seg has 2 hosts, so it's quick:
   ```bash
   GREENBONE_START_TASK_NAME="Credentialed scan: edge_seg" ANSIBLE_TAGS=credential-program \
     TASK_APPROVAL=gvmcov-vlan-greenbone ./with-secrets-prod scripts/provision.sh --stack greenbone-stack
   ```
   When it is Done, both hosts (192.168.30.10, 192.168.30.11) must show
   `SSH Login Successful` and LSC detections, with no `SSH Login Failed`.
3. Record results in README.md, and update the status pointers listed in
   OP-5 step 5.
