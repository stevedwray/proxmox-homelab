# Proxmox Homelab

This repository contains the current infrastructure automation and operating
docs for the Proxmox homelab.

The active working model is:

- `pve-test-vm` is the validation environment
- `pve` is production
- Terraform/Terragrunt entry point is `terraform/lxc/`
- Ansible handles host bootstrap and stack provisioning
- Proxmox SDN VLAN zones provide network segmentation
- MikroTik is the L3 gateway and DNS forwarding control point

## Start here

If you are new to the repository, read these in order:

1. [`docs/getting-started.md`](./docs/getting-started.md)
2. [`docs/workflow/branch-model.md`](./docs/workflow/branch-model.md)
3. [`docs/workflow/environments.md`](./docs/workflow/environments.md)
4. [`docs/workflow/documentation-workspaces.md`](./docs/workflow/documentation-workspaces.md)
5. [`docs/reference/secrets-management.md`](./docs/reference/secrets-management.md)
6. [`docs/plan/README.md`](./docs/plan/README.md)
7. [`docs/design/architecture.md`](./docs/design/architecture.md)
8. [`docs/design/network.md`](./docs/design/network.md)
9. [`terraform/README.md`](./terraform/README.md)
10. [`terraform/lxc/README.md`](./terraform/lxc/README.md)

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

1. Work from a short-lived branch cut from the current working HEAD
2. Select the target environment through the appropriate wrapper and env files
3. Define stack intent in `terraform/lxc/stacks/<stack>/stack.yaml`
4. Define network intent in `terraform/lxc/network/<environment>.yaml`
5. Run Terraform/Terragrunt from `terraform/lxc/`
6. Let Terraform create LXCs and invoke Ansible-based provisioning
7. Validate at the tier that matches the change risk before promotion

## Edge Reconciler

For stack-owned browser ingress manifests under `terraform/lxc/stacks/*/edge.yaml`,
use the dry-run-first unified reconciler:

```bash
# Dry-run (default)
python3 terraform/lxc/reconcile-edge.py --json

# Apply mode (requires target preflight + service health checks)
./with-secrets python3 terraform/lxc/reconcile-edge.py --apply --json
```

Detailed command options and expected behavior are documented in
`terraform/lxc/README.md`.

For shared migration validation, rollback, and stop conditions used by the
stack-owned edge route tasks, see
`docs/provisioning-refactor/runbook.md`.

## Canonical docs

- Workflow:
  - [`docs/workflow/branch-model.md`](./docs/workflow/branch-model.md)
  - [`docs/workflow/environments.md`](./docs/workflow/environments.md)
  - [`docs/workflow/documentation-workspaces.md`](./docs/workflow/documentation-workspaces.md)
- Architecture:
  - [`docs/design/architecture.md`](./docs/design/architecture.md)
  - [`docs/design/network.md`](./docs/design/network.md)
  - [`docs/design/bootstrap.md`](./docs/design/bootstrap.md)
- Reference:
  - [`docs/reference/secrets-management.md`](./docs/reference/secrets-management.md)
  - [`docs/reference/proxmox-server-baseline.md`](./docs/reference/proxmox-server-baseline.md)
  - [`docs/reference/proxmox-terraform-user.md`](./docs/reference/proxmox-terraform-user.md)
  - [`docs/reference/sdn-segment-routing.md`](./docs/reference/sdn-segment-routing.md)
- Implementation:
  - [`terraform/README.md`](./terraform/README.md)
  - [`terraform/lxc/README.md`](./terraform/lxc/README.md)

## Secrets management

Use `./with-secrets` for `pve-test-vm` work and `./with-secrets-prod` for `pve`.
Secrets are managed through SOPS-backed files and wrapper scripts, not plaintext
tracked files.

See [`docs/reference/secrets-management.md`](./docs/reference/secrets-management.md)
for the current workflow.

## Current notes

- `pve-test-vm` is the current validation target; older `pve-test` references
  should be treated as historical unless a doc explicitly says otherwise.
- The design uses Proxmox SDN VLAN zones. VLAN-backed zones are the current SDN model.
- Some SDN VLAN setup is still manual because current automation does not yet
  fully apply VLAN zones automatically.
- Planning and implementation are still being aligned in places, so prefer the
  workflow and reference docs above when there is a conflict with older
  historical material.
