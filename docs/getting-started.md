# Getting Started

This guide is the current onboarding path for working on the `pve-test` build of the
Proxmox homelab repository.

It assumes the active project model:

- `pve-test` is a bare-metal Proxmox host
- Terraform entry point is `terraform/lxc/`
- Proxmox API access uses the `automation@pve!terraform` token
- host bootstrap is handled through the planned bootstrap Ansible playbooks

## What you need first

- Git with SSH access to the repository
- a Linux shell environment suitable for Terraform, Ansible, and SSH
- SSH access to `root@pve-test.gibbsgreatly.xyz`
- local copies of required environment files and secrets

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

## Verify host access

Before using any automation, confirm the target host is reachable:

```bash
ping -c 1 pve-test.gibbsgreatly.xyz
ssh root@pve-test.gibbsgreatly.xyz "pveversion"
curl -k https://pve-test.gibbsgreatly.xyz:8006
```

Expected:

- DNS resolves correctly
- root SSH works
- the Proxmox web/API endpoint responds on port `8006`

## Bootstrap the Proxmox host

If `pve-test` is freshly installed or has lost its automation baseline, run the current
bootstrap flow:

```bash
cd ansible
ansible-playbook -i inventory/dev.yml 00-initial-setup/proxmox-initial-setup.yml
ansible-playbook -i inventory/dev.yml 01-base-system/terraform-token-management.yml
```

This establishes the current baseline, including:

- Proxmox repository normalization
- `automation@pve`
- `automation@pve!terraform`
- token output for Terraform use

After rotating or creating the token, update your local `.env` and/or `.env.pve-test`
with the printed token values.

## Configure local environment files

At minimum, copy and populate the local environment file:

```bash
cp .env.template .env
```

Fill in the values required by the current repo workflow. For Terraform auth, the active
pattern is token-based, for example:

```bash
TF_VAR_pm_api_token_id=automation@pve!terraform
TF_VAR_pm_api_token_secret=<TOKEN_SECRET>
```

Depending on the task, you may also need `.env.pve-test`.

## Verify Proxmox API access

Before running Terraform, confirm the token works:

```bash
curl -ks -H "Authorization: PVEAPIToken=automation@pve!terraform=<TOKEN_SECRET>" \
  "https://pve-test.gibbsgreatly.xyz:8006/api2/json/version"
```

Expected: JSON containing Proxmox version data.

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
- `terraform/lxc/network/pve-test.yaml`
- `terraform/lxc/stacks/<stack>/stack.yaml`

## Success criteria

You are ready to work when:

- local Terraform and Ansible tooling is installed
- `pve-test.gibbsgreatly.xyz` is reachable by SSH and HTTPS
- the Proxmox bootstrap baseline has been applied if needed
- `automation@pve!terraform` is available and working
- `terragrunt plan` or `tofu validate` succeeds from `terraform/lxc/`

## Common issues

### SSH access problems

Check:

- your SSH key is present locally
- root SSH works to `pve-test.gibbsgreatly.xyz`
- `ansible/inventory/dev.yml` still matches the current host IP and key path

### Proxmox API authentication problems

Check:

- the token exists: `pveum user token list automation@pve`
- the token secret in `.env` or `.env.pve-test` is current
- you are using token auth, not the old password-based `access/ticket` flow

### Host bootstrap drift

If the host has been rebuilt or partially reset, follow:

- `docs/troubleshooting/vm-reset-recovery.md`
- `docs/reference/proxmox-server-baseline.md`
- `docs/reference/proxmox-terraform-user.md`

## Next places to read

- `docs/plan/README.md`
- `docs/plan/phase-00a-proxmox-host-bootstrap.md`
- `docs/reference/proxmox-server-baseline.md`
- `docs/reference/proxmox-terraform-user.md`
- `docs/reference/secrets-management.md`
- `docs/reference/sdn-segment-routing.md`
- `docs/troubleshooting/vm-reset-recovery.md`
- `terraform/README.md`
- `terraform/lxc/README.md`
