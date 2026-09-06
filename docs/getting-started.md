# Getting Started

This guide is the current onboarding path for working in this repository.

It assumes the current environment model:

- `pve-test-vm` is the validation environment
- `pve` is production
- Terraform entry point is `terraform/lxc/`
- secrets and environment selection are handled through wrapper scripts
- host bootstrap is handled through the active Ansible playbooks

## What you need first

- Git with SSH access to the repository
- a Linux shell environment suitable for Terraform, Ansible, and SSH
- SSH access to the target environment you are validating
- local env files and SOPS access for the target environment

If you are setting up your local toolchain from scratch, use:

```bash
chmod +x scripts/setup-dev-env.sh
./scripts/setup-dev-env.sh
```

Then verify the basics:

```bash
terraform version
ansible --version
git --version
python3 -c "import proxmoxer; print('Proxmoxer available')"
```

## Read these first

- `docs/workflow/branch-model.md`
- `docs/workflow/environments.md`
- `docs/reference/secrets-management.md`
- `terraform/lxc/README.md`

## Pick the target environment

For normal validation work, use `pve-test-vm`.

Environment wrappers:

- `./with-secrets` for `pve-test-vm`
- `./with-secrets-prod` for `pve`

Before any deploy or validation run, confirm the target node:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
```

Expected:

- for routine validation work, this should print `pve-test-vm`

If it prints anything else, stop and resolve the targeting problem first.

## Verify host access

Before using automation, confirm the target host is reachable. For the default
validation environment:

```bash
ping -c 1 pve-test-vm.gibbsgreatly.xyz
ssh root@pve-test-vm.gibbsgreatly.xyz "pveversion"
curl -k https://pve-test-vm.gibbsgreatly.xyz:8006
```

## Bootstrap the Proxmox host

If the target Proxmox host is freshly installed or has lost its automation
baseline, use the active host bootstrap playbooks described in:

- `docs/reference/proxmox-server-baseline.md`
- `docs/reference/proxmox-terraform-user.md`
- `docs/troubleshooting/vm-reset-recovery.md`

## Configure local environment files

At minimum, copy the base non-secret config:

```bash
cp .env.template .env
```

Then make sure the environment-specific files you need exist:

- `.env.pve-test-vm` for validation work
- `.env.pve` for production work

For the current secrets workflow, use:

- `docs/reference/secrets-management.md`

Do not rely on plaintext tracked secrets files. Use the wrapper scripts to load
non-secret config plus SOPS-backed secrets.

## Verify Proxmox API access

Before running Terraform, confirm the wrapper resolves the right target and the
token-backed environment loads:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
```

For `pve-test-vm`, expected output is:

- `pve-test-vm`

## Work from the active Terraform entry point

The current Terraform/Terragrunt workflow lives under `terraform/lxc/`.

Typical validation flow:

```bash
cd terraform/lxc
tofu init
tofu validate
terragrunt plan
```

Use the stack and network docs there as your primary implementation reference:

- `terraform/lxc/README.md`
- `terraform/lxc/network/pve-test-vm.yaml` when working on the validation environment
- `terraform/lxc/network/pve.yaml` when working on production-related docs or code
- `terraform/lxc/stacks/<stack>/stack.yaml`

## Success criteria

You are ready to work when:

- local Terraform and Ansible tooling is installed
- the target Proxmox host is reachable by SSH and HTTPS
- the bootstrap baseline has been applied if needed
- the environment wrapper resolves the expected node
- `terragrunt plan` or `tofu validate` succeeds from `terraform/lxc/`

## Common issues

### SSH access problems

Check:

- your SSH key is present locally
- root SSH works to the selected environment host
- the relevant inventory and environment files still match the current target

### Proxmox API authentication problems

Check:

- the wrapper resolves the expected `TF_VAR_proxmox_node`
- the relevant env files exist and are current
- the SOPS-backed secrets load successfully
- you are using the wrapper-based token workflow, not an old manual auth path

### Host bootstrap drift

If the host has been rebuilt or partially reset, follow:

- `docs/troubleshooting/vm-reset-recovery.md`
- `docs/reference/proxmox-server-baseline.md`
- `docs/reference/proxmox-terraform-user.md`

## Next places to read

- `docs/plan/README.md`
- `docs/workflow/branch-model.md`
- `docs/workflow/environments.md`
- `docs/reference/proxmox-server-baseline.md`
- `docs/reference/proxmox-terraform-user.md`
- `docs/reference/secrets-management.md`
- `docs/reference/sdn-segment-routing.md`
- `docs/troubleshooting/vm-reset-recovery.md`
- `terraform/README.md`
- `terraform/lxc/README.md`
