# 03c-artifact-proxy-02 — Create Terraform provider filesystem mirror

## Status

PENDING

## Phase

Phase 03c — Artifact Proxy (apt-cacher-ng + Terraform provider mirror)

## Prerequisites

- Task 03c-01 complete (or can be done in parallel — this task has no apt-cacher dependency)
- Terraform/OpenTofu installed on workstation
- Internet access from workstation (one-time mirror creation)

## Objective

A `terraform/terraform-providers/` filesystem mirror exists in the repo, `~/.terraformrc` on the workstation is configured to use it, and `terraform init` on ci-runner-01 completes without fetching from `registry.terraform.io`.

## Scope

- Run `terraform providers mirror` from the `terraform/lxc/` directory to create the mirror
- Create or update `~/.terraformrc` on the workstation with `filesystem_mirror` config
- Create a Jinja2 template `terraform/lxc/ansible/templates/terraformrc.j2` for deploying `.terraformrc` on ci-runner-01
- Add the mirror configuration task to `deploy-ci-runner.yml`
- Commit the mirror directory and template

## Out of Scope

- Deploying apt-cacher-ng (task 03c-01)
- Pip caching (covered by `actions/cache@v4` in CI, not a service)
- Setting up GitHub Actions cache for providers (alternative approach, not the primary)

## Inputs

- `terraform/lxc/` — run providers mirror command here
- `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml` — add `.terraformrc` task
- `docs/plan/phase-03c-artifact-proxy.md` — Parts B1–B4

## Expected Outputs

- `terraform/terraform-providers/` directory (committed to repo)
- `terraform/lxc/ansible/templates/terraformrc.j2` (new)
- `deploy-ci-runner.yml` — new task to write `.terraformrc`
- `~/.terraformrc` on workstation — configured

## Constraints and Conventions

- Mirror directory structure: `terraform/terraform-providers/registry.terraform.io/bpg/proxmox/<version>/...`
- The mirror directory is **committed** to the repo (private repo + small providers = hermeticity wins)
- `~/.terraformrc` on workstation uses the absolute path to the repo
- On ci-runner-01, the path is `/root/git/proxmox-homelab/terraform/terraform-providers` (adjust to actual workspace clone path)
- `direct { exclude }` must exclude all mirrored providers to force local resolution
- The `terraform_mirror_path` variable in the Jinja template must be set in the playbook or group vars

## Acceptance Criteria

- [ ] `terraform/terraform-providers/registry.terraform.io/bpg/proxmox/` directory exists and is committed
- [ ] `~/.terraformrc` on workstation contains `filesystem_mirror` block pointing to repo path
- [ ] `terraform init -backend=false` in `terraform/lxc/` succeeds without network access (test with network blocked or inspect logs)
- [ ] `terraformrc.j2` template exists in `terraform/lxc/ansible/templates/`
- [ ] `deploy-ci-runner.yml` has task to write `.terraformrc` on the runner

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Create a Terraform provider filesystem mirror for offline/hermetic CI, configure the
workstation to use it, and add .terraformrc deployment to the ci-runner playbook.

BEFORE EDITING, READ:
  terraform/lxc/                                           (this is the main terraform module)
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml    (add task here)
  docs/plan/phase-03c-artifact-proxy.md                   (Parts B1–B4)

STEP 1 — Create the mirror (run once from workstation):
  cd /home/steve/git/proxmox-homelab/terraform
  terraform -chdir=lxc providers mirror ../terraform-providers
  # Creates terraform/terraform-providers/registry.terraform.io/...

STEP 2 — Configure workstation .terraformrc:
  Create or update ~/.terraformrc:
    provider_installation {
      filesystem_mirror {
        path    = "/home/steve/git/proxmox-homelab/terraform/terraform-providers"
        include = ["registry.terraform.io/*/*"]
      }
      direct {
        exclude = ["registry.terraform.io/*/*"]
      }
    }

STEP 3 — Create Jinja2 template for ci-runner:
  Create terraform/lxc/ansible/templates/terraformrc.j2:
    provider_installation {
      filesystem_mirror {
        path    = "{{ terraform_mirror_path }}"
        include = ["registry.terraform.io/*/*"]
      }
      direct {
        exclude = ["registry.terraform.io/*/*"]
      }
    }

STEP 4 — Add task to deploy-ci-runner.yml:
  Read the playbook first, then add a task in the appropriate play:
    - name: Configure Terraform provider filesystem mirror
      ansible.builtin.template:
        src: terraformrc.j2
        dest: "/root/.terraformrc"
        owner: root
        group: root
        mode: "0644"
      vars:
        terraform_mirror_path: "/root/workspace/proxmox-homelab/terraform/terraform-providers"
        # Adjust path to match where the GitHub Actions runner checks out the repo

STEP 5 — Verify locally:
  terraform init -backend=false terraform/lxc/
  # Should succeed; no download from registry.terraform.io

STEP 6 — Commit:
  git add terraform/terraform-providers/ \
          terraform/lxc/ansible/playbooks/deploy-ci-runner.yml \
          terraform/lxc/ansible/templates/terraformrc.j2
  git commit -m "feat(infra): add Terraform provider filesystem mirror for hermetic CI"
  git push origin feat/apt-cacher-terraform-mirror

SECURITY SCAN (run after pushing feature branch — stop and present options if new issues are found):
  cd /home/steve/git/proxmox-homelab && source .env && sonar-scanner

DONE WHEN: terraform init works offline, mirror committed, scan clean, and task added to
ci-runner playbook. The branch is merged to dev/pve-test in task 03c-03.
```
