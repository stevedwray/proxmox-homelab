# pve-tiny network onboarding plan

Written following `docs/agent-design/step-packet-schema.md`. See `README.md`
for status, the key assumption this plan makes (pve-tiny joins pve's existing
VLAN 20/40, not new zone numbers), and the live facts it's grounded in.

Three things below are genuinely not step blocks, written as plain operator
instructions instead: the physical/MikroTik switch trunk (out-of-band
hardware work), and the two Ansible playbook runs against pve-tiny
(`proxmox-vlan-aware-bridge.yml`, `proxmox-sdn-setup.yml`) — both are a first
mutation of production infrastructure, and in this session both were
confirmed to be blocked from direct execution by Claude Code's own
"Production Deploy" auto-mode classifier when attempted directly, the same
way the original host-bootstrap and template-build commands were. The
operator runs these directly; nothing about that is a step the local model
should attempt.

---

## Step: pve-tiny-net-01-network-manifest

**Status: done (2026-09-17)** — authored directly rather than through the
step/gate loop, since a frontier session was already doing the file editing
live. Gate below was run for real and passed; recorded here for the record,
same as an `implement-step` hand-back would be.

```yaml
id: pve-tiny-net-01-network-manifest
title: Create pve-tiny's network intent file (infra_seg + mgmt_seg only)
depends_on: []

change: >
  Create terraform/lxc/network/pve-tiny.yaml. It must declare
  `proxmox.target_node: pve-tiny`, an `attachments.lan` bridge block
  identical in shape to pve.yaml's, and exactly two SDN zone attachments —
  `infra_seg` (zone tvinfra, vlan_tag 40, subnet "${lab_subnet_infra_cidr}",
  gateway "${lab_gw_infra}") and `mgmt_seg` (zone tvmgmt, vlan_tag 20,
  subnet "${lab_subnet_mgmt_cidr}", gateway "${lab_gw_mgmt}") — each with
  `nodes: [pve-tiny]` (not `pve`), `snat: false`, `firewall: false`, matching
  the exact attachment shape already used in terraform/lxc/network/pve.yaml's
  own infra_seg/mgmt_seg blocks. Do not add edge_seg, build_seg, game_seg, or
  any other zone. The zones: section's containers lists must both be empty
  (`containers: []`) — nothing is deployed into these zones on pve-tiny yet.
  Set policies: [] (no cross-zone rules needed until something is actually
  deployed there).

scope:
  allowed_paths:
    - terraform/lxc/network/pve-tiny.yaml
  forbidden_actions:
    - "Editing terraform/lxc/network/pve.yaml or any other node's network file"
    - "Adding any zone besides infra_seg and mgmt_seg"
    - "Listing any container in the zones: containers list — none exist yet"
    - "Running any pvesh/ansible-playbook/terragrunt command — file authoring only"

gates:
  - id: yaml-parses
    cmd: "python3 -c \"import yaml; d = yaml.safe_load(open('terraform/lxc/network/pve-tiny.yaml')); assert d['proxmox']['target_node'] == 'pve-tiny'; assert set(d['attachments']) == {'lan', 'infra_seg', 'mgmt_seg'}; assert d['attachments']['infra_seg']['sdn']['nodes'] == ['pve-tiny']; assert d['attachments']['mgmt_seg']['sdn']['nodes'] == ['pve-tiny']; print('OK')\""
    expect: "OK"
    critical: true
```

**Actual gate result (2026-09-17):** `OK` — verified live, not assumed.

---

## Step: pve-tiny-net-02-storage-manifest

**Status: done (2026-09-17)** — same note as above.

```yaml
id: pve-tiny-net-02-storage-manifest
title: Create pve-tiny's storage profile file (local-lvm only, no ZFS)
depends_on: []

change: >
  Create terraform/lxc/storage/pve-tiny.yaml, mirroring
  terraform/lxc/storage/pve-test.yaml's non-ZFS platform-default profile
  shape exactly, but trimmed to only the backends pve-tiny actually has:
  storage_backends must contain exactly `local-lvm` (backend_type: lvm-thin,
  content_types [images, rootdir]) and `local` (backend_type: dir,
  content_types [backup, iso, vztmpl]) — no infrastructure-containers,
  storage-containers, gaming-containers, or any other ZFS-backed entry.
  defaults.storage_profile must be platform-default, and that profile's
  rootfs_storage/docker_storage must both be local-lvm. template default
  must be debian-13.1-2-docker-template.tar.gz (the template already built
  and preserved on pve-tiny as CT 910 / packaged in local:vztmpl/).

scope:
  allowed_paths:
    - terraform/lxc/storage/pve-tiny.yaml
  forbidden_actions:
    - "Referencing any ZFS-backed storage pool — pve-tiny has none"
    - "Editing any other node's storage/*.yaml file"

gates:
  - id: yaml-parses
    cmd: "python3 -c \"import yaml; d = yaml.safe_load(open('terraform/lxc/storage/pve-tiny.yaml')); assert d['profiles']['platform-default']['rootfs_storage'] == 'local-lvm'; assert 'local-lvm' in d['storage_backends'] and d['storage_backends']['local-lvm']['backend_type'] == 'lvm-thin'; assert not any(v.get('backend_type') == 'zfs' for v in d['storage_backends'].values()); print('OK')\""
    expect: "OK"
    critical: true
```

**Actual gate result (2026-09-17):** `OK` — verified live, not assumed.

---

## Prerequisite (operator action, not a step): physical switch trunk

Before anything below can work, pve-tiny's switch port needs VLANs 20 and 40
tagged on it, same as `pve`'s and `pve-test`'s trunk ports already do. Two
things confirmed from this repo's own history that are worth checking rather
than assuming clean the first time (`pve-framework`'s VLAN 50 onboarding hit
both, in this exact order, 2026-07-17 — see
`docs/workflow/session-handoff-2026-07-18.md`):

1. **Physical switch**: the separate physical switch between pve-tiny and the
   MikroTik needs VLANs 20/40 added to pve-tiny's port (not just the
   MikroTik side).
2. **MikroTik bridge VLAN table**: VLAN 20/40 need to already be tagged on
   whichever MikroTik port pve-tiny's traffic actually arrives on. Every
   existing zone is tagged on both `ether1` and `ether5` in the MikroTik's
   bridge VLAN table because different physical hosts arrive via different
   ports (confirmed for `fe-pve`/`pve-framework` via its bridge host table)
   — check which port pve-tiny's traffic uses before assuming it's already
   covered; if it arrives on a port that isn't in the existing tagged set for
   VLAN 20/40, `ether1` has `ingress-filtering: true` and will hard-drop the
   frames silently (that's exactly what happened for VLAN 50, and it looked
   like "no connectivity" with no obvious cause until traced to this).

Verify after wiring, from a workstation already on the LAN:
```
ping 192.168.20.1   # mgmt_seg gateway — should already respond, this just confirms the port change didn't break anything
ping 192.168.40.1   # infra_seg gateway — same
```
(These pings won't yet prove pve-tiny's own VLAN interfaces work — that's
checked after the steps below run — this just confirms the physical/MikroTik
change itself didn't regress existing VLAN 20/40 traffic for `pve`.)

---

## Prerequisite (operator action, not a step): VLAN-aware bridge on pve-tiny

`vmbr0` on pve-tiny is not VLAN-aware yet (confirmed live, 2026-09-17 — no
`bridge-vlan-aware yes` in `/etc/network/interfaces`). This is what makes
`build-debian-13-template.yml` and this SDN setup both use a plain LAN
attachment vs. a VLAN one; SDN VLAN zones require it. Run, from
`/home/steve/git/proxmox-homelab`:

```bash
export TASK_APPROVAL="pve-tiny-network-onboarding"
SCRATCH=/tmp/claude-1000/-home-steve-git-proxmox-homelab/87f83cc3-14ec-4129-bf0d-c95943ff6e92/scratchpad
ansible-playbook -i "${SCRATCH}/pve-tiny-inventory.yml" -e target_hosts=proxmox -u root \
  ansible/00-initial-setup/proxmox-vlan-aware-bridge.yml \
  > "${SCRATCH}/pve-tiny-vlan-bridge.log" 2>&1
echo "exit: $?"
```

This playbook defaults to `vmbr0` / VID range `2-4094` and runs `ifreload -a`
to apply immediately — matches the defaults used for `pve-framework`, no
override needed here. Verify afterward with a **fresh** SSH connection (not
the same session) that the host is still reachable and `bridge vlan show`
reflects the change — the `pve-framework` precedent specifically checked this
because a VLAN-aware bridge reload can (rarely) interrupt connectivity if
something is misconfigured.

---

## Prerequisite (operator action, not a step): create the SDN zones

Once the bridge is VLAN-aware and the physical trunk carries VLANs 20/40 to
pve-tiny, run the command below.

No `target_hosts` override needed — this playbook's `hosts:` defaults to
`proxmox`, matching our inventory group. Its first task
(`Load network intent for target environment`) does
`include_vars: file: "../../terraform/lxc/network/{{ lookup('env', 'PVE_ENV') | default('pve-test', true) }}.yaml"`
— a Jinja `lookup('env', ...)`, which reads the actual OS process
environment, not `-e` extra-vars, so it's satisfied by exporting `PVE_ENV`
in the same shell before invoking `ansible-playbook` (confirmed by reading
`ansible/00-initial-setup/proxmox-sdn-setup.yml` directly, not assumed).
Separately confirmed: its per-vnet subnet/gateway vars
(`sdn_subnet_tvinfra`/`sdn_gw_tvinfra`, `sdn_subnet_tvmgmt`/`sdn_gw_tvmgmt`)
already exist in the playbook's own `vars:` block, resolved from the same
shared `lab_subnet_infra_cidr`/`lab_gw_infra`/etc. env vars every other
node uses — this only works unmodified because `pve-tiny.yaml` reuses the
vnet names `tvinfra`/`tvmgmt` rather than inventing new ones; a
differently-named vnet would need a matching `sdn_subnet_<name>`/`sdn_gw_<name>`
pair added to this playbook first.

```bash
export TASK_APPROVAL="pve-tiny-network-onboarding"
SCRATCH=/tmp/claude-1000/-home-steve-git-proxmox-homelab/87f83cc3-14ec-4129-bf0d-c95943ff6e92/scratchpad
PVE_ENV=pve-tiny TF_VAR_proxmox_node=pve-tiny \
  ansible-playbook -i "${SCRATCH}/pve-tiny-inventory.yml" \
  ansible/00-initial-setup/proxmox-sdn-setup.yml \
  > "${SCRATCH}/pve-tiny-sdn-setup.log" 2>&1
echo "exit: $?"
```

This creates the `tvinfra`/`tvmgmt` SDN zones and VNets on pve-tiny via
`pvesh`, and verifies the resulting `tvinfra`/`tvmgmt` bridges exist on-host.

---

## Verification (can be run read-only afterward, either by the operator or in a follow-up session)

```bash
export TASK_APPROVAL="pve-tiny-network-verify"
./with-secrets-prod-tiny bash -c '
curl -sk -H "Authorization: PVEAPIToken=${TF_VAR_pm_api_token_id}=${TF_VAR_pm_api_token_secret}" \
  "${TF_VAR_proxmox_api_url}/cluster/sdn/zones"
curl -sk -H "Authorization: PVEAPIToken=${TF_VAR_pm_api_token_id}=${TF_VAR_pm_api_token_secret}" \
  "${TF_VAR_proxmox_api_url}/cluster/sdn/vnets"
'
```
Expect `tvinfra`/`tvmgmt` zones and vnets present, plus `tvinfra`/`tvmgmt`
bridges visible in `ip -br link` on pve-tiny itself.

---

## Phase 2 — not planned yet: relocating harbor-stack / graylog-stack

Deliberately left out of this plan — the judgment calls below need
resolving first, the same way this plan resolved the VLAN-sharing question
before writing any step content:

- **Data migration mechanics.** Harbor's registry blobs and Graylog's
  index/config data currently live on pve's ZFS-backed
  `infrastructure-containers` pool. pve-tiny has no ZFS pool. Moving either
  stack means copying data across (rsync/tar over the network, or an
  application-level export/import) rather than a `zfs send`/`receive` or a
  `pct migrate` (not available — pve and pve-tiny aren't clustered). Which
  approach depends on each stack's own data layout and hasn't been
  researched yet.
- **Cutover sequencing.** Harbor is the pull-through registry essentially
  every other stack depends on for image pulls (`registry_host`, ai
  `LAB_IP_HARBOR`); Graylog is the shared log destination several stacks'
  Docker log drivers point at. Both need a real cutover plan (stop old,
  migrate data, start new, verify consumers) — not a step a local model
  should attempt unsupervised even once the mechanics are known.
- **Whether to reuse the exact same IP or not.** This plan's zone files
  assume yes (same subnet, same identity) — confirmed as the intent from
  the operator's framing, but the actual stack.yaml `ip_address` values for
  `harbor-stack`/`graylog-stack` haven't been changed or even inspected for
  this yet.

Write a separate `docs/pve-tiny-stack-relocation/plan.md` once these are
resolved, rather than folding it into this one — this workspace's scope was
network onboarding only (see README.md).
