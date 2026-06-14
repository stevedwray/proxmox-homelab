# 00a-host-bootstrap-02 — Configure Proxmox SDN VLAN zones

## Status

COMPLETE

## Phase

Phase 00a — Proxmox Host Bootstrap Alignment

## GitHub Issue

[#128](https://github.com/stevedwray/proxmox-homelab/issues/128)

## Greenfield assumption

This task assumes the Proxmox host initial setup (task 00a-01) has been completed. The
host has the Terraform API token provisioned. No SDN zones, VNets, or VLAN bridges exist
yet on pve-test.

## Prerequisites

- Task 00a-01 complete — pve-test has the Proxmox package baseline applied
- MikroTik router trunk to pve-test has VLAN interfaces for all four `10.57.x.0/24` subnets
  configured as described in `terraform/lxc/network/pve-test.yaml`
- `vmbr0` is set to VLAN-aware on pve-test
- SSH access to pve-test as root

## Network placement

This task creates the following SDN zones, VNets, and VLAN mappings on pve-test:

| Segment | Proxmox zone | VNet bridge | VLAN | Subnet | Gateway |
| --- | --- | --- | --- | --- | --- |
| `build_seg` | `tvsegc` | `tvnetc` | 10 | `10.57.0.0/24` | `10.57.0.1` |
| `mgmt_seg` | `tvmgmt` | `tvmgmt` | 20 | `10.57.1.0/24` | `10.57.1.1` |
| `edge_seg` | `tvedge` | `tvedge` | 30 | `10.57.2.0/24` | `10.57.2.1` |
| `infra_seg` | `tvinfra` | `tvinfra` | 40 | `10.57.3.0/24` | `10.57.3.1` |

## Objective

All four SDN VLAN zones are applied and active on pve-test. LXCs placed in any of these
zones receive an IP in the correct subnet and can reach their MikroTik gateway. This is a
prerequisite for every LXC deployed outside the bootstrap flat-LAN (`vmbr0`).

## Scope

- Write and run an Ansible playbook (`ansible/00-initial-setup/proxmox-sdn-setup.yml`)
  that applies the SDN zone configuration to pve-test using `pvesh` commands
- Apply the SDN configuration and reload it
- Verify each VNet bridge exists and the zones are active

## Out of Scope

- MikroTik VLAN interface configuration (assumed complete as a prerequisite)
- Proxmox firewall cross-zone rules (known bug — firewall remains disabled on dev passes)
- Any LXC deployment

## Inputs

- `ansible/00-initial-setup/proxmox-sdn-setup.yml` (to be created as part of this task)
- `terraform/lxc/network/pve-test.yaml` (source of truth for zone/VLAN definitions)
- `ansible/inventory/dev.yml`

## Expected Outputs

- `ansible/00-initial-setup/proxmox-sdn-setup.yml` committed to the repository
- Four SDN VLAN zones active on pve-test
- Four VNet bridges (`tvnetc`, `tvmgmt`, `tvedge`, `tvinfra`) present on the host

## Constraints and Conventions

- The Proxmox Terraform provider does not yet support VLAN zone creation; Ansible + `pvesh`
  is the required path until provider support is added
- Zone definitions must match `terraform/lxc/network/pve-test.yaml` exactly (IPs, VLANs,
  VNet names)
- The playbook should be idempotent — safe to re-run if a zone already exists

## Acceptance Criteria

- [x] `ansible/00-initial-setup/proxmox-sdn-setup.yml` exists and is committed
- [x] Playbook run exits 0 with no failed tasks
- [x] `ssh root@pve-test pvesh get /cluster/sdn/zones` lists `tvinfra`, `tvmgmt`, `tvedge`, `tvsegc`
- [x] `ssh root@pve-test "ip -br link"` lists `tvnetc`, `tvmgmt`, `tvedge`, `tvinfra`

## Completion Notes

- Completed on 2026-04-16 against `pve-test.gibbsgreatly.xyz`
- `ansible/00-initial-setup/proxmox-sdn-setup.yml` now loads `terraform/lxc/network/pve-test.yaml` directly and applies the four VLAN SDN zones idempotently
- Verified live Proxmox SDN state via `pvesh get /cluster/sdn/zones --output-format json` and `pvesh get /cluster/sdn/vnets --output-format json`
- Verified live host interfaces via `ip -br link`, which exposes the VNet bridge links for VLAN SDN; `/nodes/pve-test/network` does not list them
- Updated `ansible/inventory/dev.yml` to stop hardcoding the missing `~/.ssh/id_rsa` path so Ansible uses the working local SSH key selection

## Session Prompt

```text
You are working in /home/steve/git/proxmox-homelab on branch baseline/teardown-validated.

Issue: #128 — feat(sdn): configure Proxmox SDN VLAN zones on pve-test (Phase 00a, task 2)

Context:
- Task 00a-01 should already be complete or verified enough that pve-test has the expected host baseline and Terraform API access.
- Boundary-strengthening Sessions 3, 4, and 5 are merged into baseline/teardown-validated.
- `terraform/lxc/network/pve-test.yaml` is the source of truth for pve-test SDN zone names, VLAN IDs, VNet names, subnets, and gateways.
- Do not invent alternate SDN naming or topology semantics outside that file.

TASK: Write and run an Ansible playbook that configures the four SDN VLAN zones on pve-test.

Primary objective:
- Bring pve-test to the point where the four SDN VLAN zones exist and later LXC deployment work can attach to them predictably.

The source of truth for zone definitions is:
  terraform/lxc/network/pve-test.yaml

The four zones are:
  build_seg  → zone tvsegc  → vnet tvnetc  VLAN 10  10.57.0.0/24  gw 10.57.0.1
  mgmt_seg   → zone tvmgmt  → vnet tvmgmt  VLAN 20  10.57.1.0/24  gw 10.57.1.1
  edge_seg   → zone tvedge  → vnet tvedge  VLAN 30  10.57.2.0/24  gw 10.57.2.1
  infra_seg  → zone tvinfra → vnet tvinfra VLAN 40  10.57.3.0/24  gw 10.57.3.1

STEP 1 — Read the network definition file:
  cat terraform/lxc/network/pve-test.yaml

STEP 2 — Write the playbook:
  Create ansible/00-initial-setup/proxmox-sdn-setup.yml
  Use pvesh to create each zone and VNet if not already present.
  The playbook must be idempotent (check-before-create pattern).
  Target host group: proxmox (pve-test)
  Keep names and VLAN assignments exactly aligned with terraform/lxc/network/pve-test.yaml.

STEP 3 — Run the playbook:
  ansible-playbook \
    -i ansible/inventory/dev.yml \
    ansible/00-initial-setup/proxmox-sdn-setup.yml

STEP 4 — Apply and reload SDN:
  ssh root@pve-test.gibbsgreatly.xyz "pvesh set /cluster/sdn"

STEP 5 — Verify zones and VNets:
  ssh root@pve-test.gibbsgreatly.xyz "pvesh get /cluster/sdn/zones"
  ssh root@pve-test.gibbsgreatly.xyz "ip -br link | egrep 'tvnetc|tvmgmt|tvedge|tvinfra'"
  # Expect: tvnetc, tvmgmt, tvedge, tvinfra bridges present

STEP 6 — Validate any repo changes:
  Run the relevant validation for any files you touched.
  If Terraform files or Python/shell/YAML code changes were made, run the required scans before merging.

STEP 7 — Commit and close the issue when verified:
  git add ansible/00-initial-setup/proxmox-sdn-setup.yml
  git commit -m "feat(ansible): add pve-test SDN VLAN setup playbook (Closes #128)"
  gh issue close 128 --comment "Fixed in commit <sha>"

DONE WHEN: All four SDN VLAN zones are active on pve-test and the VNet bridges appear in
the host network interface list, and any repo updates have been validated and committed
against issue #128.
```
