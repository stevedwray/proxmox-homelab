# 03c-artifact-proxy-02 — Configure Terraform provider filesystem mirror

## Status

PENDING

## Phase

Phase 03c — Artifact Proxy (apt-cacher-ng + Terraform mirror)

## Prerequisites

- [03c-artifact-proxy-01 — Deploy apt-cacher-ng stack on infra_seg](03c-artifact-proxy-01-deploy-apt-cacher.md) complete or intentionally parallelized
- Terraform/OpenTofu installed on the workstation
- Internet access available for one-time provider mirroring

## Objective

A committed provider mirror exists under `terraform/terraform-providers/`, the workstation
and `ci-runner-01` can be configured to use it, and later `terraform init` runs avoid
direct provider fetches.

## Scope

- Create the provider mirror under `terraform/terraform-providers/`
- Create `terraform/lxc/ansible/templates/terraformrc.j2`
- Update `deploy-ci-runner.yml` to deploy `.terraformrc`
- Verify mirror configuration locally

## Out of Scope

- Re-running the ci-runner playbook
- GitHub Actions cache alternatives

## Acceptance Criteria

- [ ] `terraform/terraform-providers/` exists
- [ ] `terraform/lxc/ansible/templates/terraformrc.j2` exists
- [ ] `deploy-ci-runner.yml` contains a `.terraformrc` deployment task
- [ ] Local `terraform init -backend=false` works with the mirror configured

## Session Prompt

```text
TASK: Create the Terraform provider filesystem mirror and wire it into ci-runner deployment.

STEP 1 — Create mirror:
  cd /home/steve/git/proxmox-homelab/terraform
  terraform -chdir=lxc providers mirror ../terraform-providers

STEP 2 — Configure workstation ~/.terraformrc:
  provider_installation {
    filesystem_mirror {
      path    = "/home/steve/git/proxmox-homelab/terraform/terraform-providers"
      include = ["registry.terraform.io/*/*"]
    }
    direct {
      exclude = ["registry.terraform.io/*/*"]
    }
  }

STEP 3 — Create terraform/lxc/ansible/templates/terraformrc.j2

STEP 4 — Update terraform/lxc/ansible/playbooks/deploy-ci-runner.yml
  to write /root/.terraformrc from the template.

STEP 5 — Verify:
  cd /home/steve/git/proxmox-homelab/terraform/lxc
  terraform init -backend=false

DONE WHEN: The provider mirror exists and can be deployed to ci-runner-01.
```
