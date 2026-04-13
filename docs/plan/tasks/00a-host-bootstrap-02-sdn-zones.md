# 00a-host-bootstrap-02 — Configure Proxmox SDN VLAN zones

## Status

PENDING

## Phase

Phase 00a — Proxmox Host Bootstrap Alignment

## GitHub Issue

Not assigned yet.

## Greenfield assumption

This task assumes the Proxmox host initial setup (task 00a-01) has been completed. The
host has the Terraform API token provisioned. No SDN zones, VNets, or VLAN bridges exist
yet on pve-test.

## Prerequisites

- Task 00a-01 complete — pve-test has the Proxmox package baseline applied
- MikroTik router has static routes configured for all four `10.57.x.0/24` subnets pointing
  at `192.168.1.40` (pve-test)
- `vmbr0` is set to VLAN-aware on pve-test
- SSH access to pve-test as root

## Network placement

This task creates the following SDN zones, VNets, and VLAN mappings on pve-test:

| Zone | VNet bridge | VLAN | Subnet | Gateway |
|---|---|---|---|---|
| `build_seg` | `tvnetc` | 10 | `10.57.0.0/24` | `10.57.0.1` |
| `mgmt_seg` | `tvmgmt` | 20 | `10.57.1.0/24` | `10.57.1.1` |
| `edge_seg` | `tvedge` | 30 | `10.57.2.0/24` | `10.57.2.1` |
| `infra_seg` | `tvinfra` | 40 | `10.57.3.0/24` | `10.57.3.1` |

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

- MikroTik route configuration (assumed complete as a prerequisite)
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

- [ ] `ansible/00-initial-setup/proxmox-sdn-setup.yml` exists and is committed
- [ ] Playbook run exits 0 with no failed tasks
- [ ] `ssh root@pve-test pvesh get /cluster/sdn/zones` lists all four zones
- [ ] `ssh root@pve-test pvesh get /nodes/pve-test/network` lists `tvnetc`, `tvmgmt`, `tvedge`, `tvinfra`
- [ ] `ping -c 3 10.57.0.1` from a test LXC on `build_seg` succeeds (MikroTik gateway reachable)

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Write and run an Ansible playbook that configures the four SDN VLAN zones on pve-test.

The source of truth for zone definitions is:
  terraform/lxc/network/pve-test.yaml

The four zones are:
  build_seg  → tvnetc  VLAN 10  10.57.0.0/24  gw 10.57.0.1
  mgmt_seg   → tvmgmt  VLAN 20  10.57.1.0/24  gw 10.57.1.1
  edge_seg   → tvedge  VLAN 30  10.57.2.0/24  gw 10.57.2.1
  infra_seg  → tvinfra VLAN 40  10.57.3.0/24  gw 10.57.3.1

STEP 1 — Read the network definition file:
  cat terraform/lxc/network/pve-test.yaml

STEP 2 — Write the playbook:
  Create ansible/00-initial-setup/proxmox-sdn-setup.yml
  Use pvesh to create each zone and VNet if not already present.
  The playbook must be idempotent (check-before-create pattern).
  Target host group: proxmox (pve-test)

STEP 3 — Run the playbook:
  ansible-playbook \
    -i ansible/inventory/dev.yml \
    ansible/00-initial-setup/proxmox-sdn-setup.yml

STEP 4 — Apply and reload SDN:
  ssh root@pve-test.gibbsgreatly.xyz "pvesh set /cluster/sdn"

STEP 5 — Verify zones and VNets:
  ssh root@pve-test.gibbsgreatly.xyz "pvesh get /cluster/sdn/zones"
  ssh root@pve-test.gibbsgreatly.xyz "pvesh get /nodes/pve-test/network"
  # Expect: tvnetc, tvmgmt, tvedge, tvinfra bridges present

STEP 6 — Commit the new playbook:
  git add ansible/00-initial-setup/proxmox-sdn-setup.yml
  git commit -m "feat(ansible): add proxmox-sdn-setup playbook for VLAN zones"

DONE WHEN: All four SDN VLAN zones are active on pve-test and the VNet bridges appear in
the host network interface list.
```
