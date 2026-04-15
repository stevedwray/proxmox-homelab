# Proxmox Initial Setup

This directory contains the active Ansible workflow for bringing the bare-metal `pve-test`
Proxmox host to the state expected by the current `terraform/lxc` deployment path.

## Active workflow

The active Phase 00a sequence is:

1. Run `proxmox-initial-setup.yml` to align repositories, host tuning, and Terraform API access.
2. Run `proxmox-sdn-setup.yml` to create the four Proxmox SDN VLAN zones and VNets defined in `terraform/lxc/network/pve-test.yaml`.
3. Run `build-debian-13-template.yml` to build and package the Debian LXC template expected by the active Terraform stacks.

These playbooks are the canonical bootstrap path for `pve-test`.

## Inventory and target host

Use the development inventory:

```bash
ansible-playbook -i ansible/inventory/dev.yml ...
```

The active Proxmox host is:

- `pve-test.gibbsgreatly.xyz`
- `192.168.1.40`
- inventory group: `proxmox`

The control node should have a working ED25519 SSH keypair available at:

- `~/.ssh/id_ed25519`
- `~/.ssh/id_ed25519.pub`

## Playbooks

### `proxmox-initial-setup.yml`

Purpose:

- switch the host to the no-subscription Proxmox repository baseline
- remove enterprise repository references
- apply host tuning for the current Debian 13 / Proxmox VE 9 baseline
- create and rotate the Terraform automation token for `automation@pve!terraform`
- optionally enable the nftables-backed Proxmox firewall backend

Run:

```bash
ansible-playbook \
  -i ansible/inventory/dev.yml \
  ansible/00-initial-setup/proxmox-initial-setup.yml
```

Key variables:

- `pmx_enable_ceph_repo`
- `pmx_disable_subscription_nag`
- `pmx_ipv6_tune`
- `pmx_setup_terraform_user`
- `pmx_terraform_user`
- `pmx_terraform_token_id`

### `proxmox-initial-tests.yml`

Purpose:

- read-only validation of Proxmox repository state, token presence, and general host readiness

Run:

```bash
ansible-playbook \
  -i ansible/inventory/dev.yml \
  ansible/00-initial-setup/proxmox-initial-tests.yml
```

### `proxmox-sdn-setup.yml`

Purpose:

- read `terraform/lxc/network/pve-test.yaml` as the source of truth
- create or validate the four VLAN SDN zones and VNets on `pve-test`
- apply SDN changes with `pvesh set /cluster/sdn`
- verify the expected VNet bridges exist on the host

Run:

```bash
ansible-playbook \
  -i ansible/inventory/dev.yml \
  ansible/00-initial-setup/proxmox-sdn-setup.yml
```

Expected VLAN SDN objects:

- zone `tvsegc`, VNet `tvnetc`, VLAN `10`
- zone `tvmgmt`, VNet `tvmgmt`, VLAN `20`
- zone `tvedge`, VNet `tvedge`, VLAN `30`
- zone `tvinfra`, VNet `tvinfra`, VLAN `40`

### `build-debian-13-template.yml`

Purpose:

- create a temporary Debian 13 builder container on `vmbr0`
- install Docker, `docker-compose`, common automation tools, and the Portainer agent service files
- convert the builder to Proxmox template ID `910`
- package the template archive as `debian-13.1-2-docker-template.tar.gz`
- preserve the template on-host for later `pct clone` use

Run:

```bash
ansible-playbook \
  -i ansible/inventory/dev.yml \
  ansible/00-initial-setup/build-debian-13-template.yml
```

Current active defaults come from `ansible/group_vars/proxmox_production.yml`:

- builder CT ID `910`
- packaging clone ID `810`
- builder IP `192.168.1.54`
- storage pool `infrastructure-containers`
- output path `/storage/template/template/cache/debian-13.1-2-docker-template.tar.gz`

Verification examples:

```bash
ssh root@pve-test.gibbsgreatly.xyz \
  "pvesm list storage-template | grep debian-13.1-2-docker-template.tar.gz"

ssh root@pve-test.gibbsgreatly.xyz \
  "pct clone 910 911 --hostname template-smoke-911 && pct destroy 911 --purge 1"
```

## Historical and alternate-path files

The following files remain in this directory but are not the canonical path for the current `pve-test` rebuild:

- `proxmox-storage-setup.yml`
- `storage-prevalidation.yml`
- `storage-setup.yml`
- `storage-setup-02.yml`
- `storage-verify.yml`
- `StoragePlaybook.md`

Treat them as historical or alternate-environment support unless a later phase explicitly brings them back into scope.

## Troubleshooting

### SSH and inventory

- Prefer the `proxmox` inventory group when targeting the host.
- Do not rely on old hardcoded RSA key paths; the active control-node path is ED25519.

### SDN verification

- Verify Proxmox SDN objects with `pvesh get /cluster/sdn/zones --output-format json` and `pvesh get /cluster/sdn/vnets --output-format json`.
- Verify live bridge interfaces with `ip -br link`; Proxmox VLAN SDN VNet bridges do not appear in `/nodes/<node>/network`.

### Template usage

- Use `pct clone 910 <new_id> --hostname <name>` for the preserved on-host template.
- Use `pct restore <new_id> /storage/template/template/cache/debian-13.1-2-docker-template.tar.gz --storage <pool>` for the packaged archive path.

### Debugging

Run playbooks with extra verbosity when needed:

```bash
ansible-playbook -vvv -i ansible/inventory/dev.yml <playbook>
```
