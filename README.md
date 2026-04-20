# Proxmox Homelab

This repository contains the current build, planning, and automation work for the
`pve-test` Proxmox homelab environment.

The active project direction is:

- single-node `pve-test`
- bare-metal Proxmox host
- Terraform/Terragrunt-driven LXC provisioning under `terraform/lxc/`
- Ansible-based host bootstrap and stack provisioning
- Proxmox SDN VLAN zones on a VLAN-aware `vmbr0`
- MikroTik as the L3 gateway

## Start here

If you are new to the repository, read these in order:

1. [`docs/getting-started.md`](./docs/getting-started.md)
2. [`docs/plan/README.md`](./docs/plan/README.md)
3. [`terraform/README.md`](./terraform/README.md)
4. [`terraform/lxc/README.md`](./terraform/lxc/README.md)

## Repository layout

```text
proxmox-homelab/
├── ansible/
│   ├── 00-initial-setup/        # Proxmox host bootstrap
│   ├── 01-base-system/          # Terraform user/token and related host setup
│   └── _legacy/                 # Older automation kept outside the active path
├── docs/
│   ├── design/                  # Architecture and revision docs
│   ├── plan/                    # Active development/deployment phases and tasks
│   ├── reference/               # Current operator/developer reference docs
│   └── troubleshooting/         # Current troubleshooting guides
├── scripts/                     # Local helper and validation scripts
├── terraform/
│   ├── lxc/                     # Active Terraform + Ansible LXC pipeline
│   ├── secrets.enc.yaml         # SOPS-encrypted infrastructure secrets
│   └── terraform-providers/     # Local provider mirror/cache
├── .env.template                # Local environment template
├── AGENTS.md                    # Codex workflow instructions
└── CLAUDE.md                    # Claude workflow notes
```

## Active workflow

At a high level, the current workflow is:

1. Bootstrap or recover the Proxmox host with the active Ansible playbooks
2. Define stack intent in `terraform/lxc/stacks/<stack>/stack.yaml`
3. Define network intent in `terraform/lxc/network/pve-test.yaml`
4. Run Terraform/Terragrunt from `terraform/lxc/`
5. Let Terraform create LXCs and invoke Ansible-based provisioning

## Edge Reconciler

For stack-owned browser ingress manifests under `terraform/lxc/stacks/*/edge.yaml`,
use the dry-run-first unified reconciler:

```bash
# Dry-run (default)
python3 terraform/lxc/reconcile-edge.py --json

# Apply mode (requires pve-test preflight + service health checks)
./with-secrets python3 terraform/lxc/reconcile-edge.py --apply --json
```

Detailed command options and expected behavior are documented in
`terraform/lxc/README.md`.

For shared migration validation, rollback, and stop conditions used by the
stack-owned edge route tasks, see
`docs/provisioning-refactor/runbook.md`.

## Key documents

### Architecture and planning

- [`docs/design/GreenField.md`](./docs/design/GreenField.md)
- [`docs/design/NetworkPlanning.md`](./docs/design/NetworkPlanning.md)
- [`docs/plan/README.md`](./docs/plan/README.md)
- [`docs/plan/phase-00a-proxmox-host-bootstrap.md`](./docs/plan/phase-00a-proxmox-host-bootstrap.md)

### Host bootstrap and Terraform access

- [`docs/reference/proxmox-server-baseline.md`](./docs/reference/proxmox-server-baseline.md)
- [`docs/reference/proxmox-terraform-user.md`](./docs/reference/proxmox-terraform-user.md)
- [`docs/troubleshooting/vm-reset-recovery.md`](./docs/troubleshooting/vm-reset-recovery.md)

### Network model

- [`docs/reference/sdn-segment-routing.md`](./docs/reference/sdn-segment-routing.md)
- [`terraform/lxc/network/pve-test.yaml`](./terraform/lxc/network/pve-test.yaml)

### Terraform and stacks

- [`terraform/README.md`](./terraform/README.md)
- [`terraform/lxc/README.md`](./terraform/lxc/README.md)

## Secrets management

Secrets are not committed in plaintext.

The current repository references:

- local environment files such as `.env`
- SOPS-encrypted infrastructure data in `terraform/secrets.enc.yaml`
- GitHub Actions secrets for CI-only values

See [`docs/reference/secrets-management.md`](./docs/reference/secrets-management.md) for the current secrets workflow.

## Current notes

- The design uses Proxmox SDN VLAN zones. VLANs did not replace SDN; VLAN-backed zones are the current SDN model.
- Some SDN VLAN setup is still manual because the current Terraform/Ansible automation does not yet fully apply VLAN zones automatically.
- The active implementation is still mid-alignment with the revised design and plan, so the planning docs should be treated as the target state and `terraform/lxc` as the implementation in progress.
