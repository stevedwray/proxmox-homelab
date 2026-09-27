# Terraform in This Repository

This directory is the Terraform entry point for the current `pve-test` build path.

The active implementation is centered on [`terraform/lxc/`](./lxc/), which provisions
Proxmox LXC stacks, generates inventory, and triggers Ansible-based provisioning and
stack deployment.

## Current layout

```text
terraform/
├── README.md
├── lxc/                         # Active Terraform + Ansible pipeline
├── PRODUCTION_NODES             # Declared list of production-trust Proxmox nodes
└── terraform-providers/         # Local provider mirror/cache
```

## What is active

The current Terraform workflow is:

1. Define or update stack intent in `terraform/lxc/stacks/<stack>/stack.yaml`
2. Define network intent in `terraform/lxc/network/pve-test.yaml`
3. Run Terraform/Terragrunt from `terraform/lxc/`
4. Let Terraform create the LXC, generate inventory, and invoke Ansible as needed

The active environment model is:

- single-node `pve-test`
- bare-metal Proxmox host
- Proxmox SDN VLAN zones on a VLAN-aware `vmbr0`
- MikroTik as the L3 gateway

## Main entry points

- [`terraform/lxc/README.md`](./lxc/README.md): detailed implementation guide for the active LXC pipeline
- [`terraform/lxc/network/pve-test.yaml`](./lxc/network/pve-test.yaml): declarative network and zone intent
- [`terraform/lxc/stacks/`](./lxc/stacks/): stack definitions
- [`terraform/lxc/ansible/`](./lxc/ansible/): provisioning playbooks and roles

## Active stacks

Examples of current stack directories under `terraform/lxc/stacks/` include:

- `portainer-stack`
- `harbor-stack`
- `apt-cacher-stack`
- `netbox-stack`
- `authentik-stack`
- `step-ca-stack`
- `ci-runner-01`
- validation/network stacks such as `net-client-01`, `net-service-01`, and `net-isolated-01`

Each stack directory is the unit of deployment for the current implementation.

## What this README is not

This is not a module-development guide for the older `terraform/modules/*` layout, and it
is not documentation for the earlier top-level stack directories like
`management-stack/`, `media-stack/`, or `security-stack/`. Those patterns are not the
current repository model.

It is also not the authoritative source for stack internals. For that, use
[`terraform/lxc/README.md`](./lxc/README.md).

## Prerequisites

Before using `terraform/lxc/`, make sure the host/bootstrap prerequisites are in place:

- Proxmox host baseline applied
- `automation@pve!terraform` token available
- local environment files populated with required credentials
- `pve-test` host reachable over SSH and API

Related docs:

- [`docs/plan/phase-00a-proxmox-host-bootstrap.md`](../docs/plan/phase-00a-proxmox-host-bootstrap.md)
- [`docs/reference/proxmox-server-baseline.md`](../docs/reference/proxmox-server-baseline.md)
- [`docs/reference/proxmox-terraform-user.md`](../docs/reference/proxmox-terraform-user.md)

## Secret Management

Secret values live in OpenBao (`openbao-stack`), not in this directory. The
wrappers read them with a read-only AppRole per environment; which entries and
fields each environment gets is declared in `../secrets/manifest.json`.
Per-node values (a node's own Proxmox API tokens and LXC root password) are the
`hosts/<node>` entries; everything else is shared. See
`docs/reference/secrets-management.md` for day-to-day use, and
`docs/secrets-refactor/secrets-design.md` for the design. The old
`secrets.*.enc.yaml` SOPS files were retired in 2026-09 (still in Git history,
not authoritative).

For details on credential controls, approval flows, and environment targeting, see:
- [`docs/reference/production-credentials.md`](../docs/reference/production-credentials.md)
- [`docs/productionize-refactor/tasks/01-credential-controls.md`](../docs/productionize-refactor/tasks/01-credential-controls.md)

## Notes

- The network model has moved to Proxmox SDN VLAN zones; VLANs did not replace SDN, they
  are the current SDN zone type in use.
- There is still a known implementation gap: Terraform/Ansible automation does not yet
  fully apply VLAN zones automatically, so some SDN setup remains manual. See the active
  plan docs and `pve-test.yaml` for details.
