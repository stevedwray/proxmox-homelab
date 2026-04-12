# Phase 03c — Artifact Proxy (apt-cacher-ng + Terraform provider mirror)

## Goal

Reduce bandwidth usage and build latency by caching Debian apt packages and Terraform providers locally. No heavy artifact repository is required for this lab:

1. **apt-cacher-ng** — lightweight transparent apt proxy for all LXC containers and the CI runner; single binary, ~50 MB, ~128 MB RAM at rest
2. **Terraform provider filesystem mirror** — local on-disk mirror of required providers; no running service needed; committed to the repo and used by CI

This phase replaces the need for Nexus or any similar heavy artifact manager. Python/pip caching is handled by GitHub Actions `actions/cache@v4` (cache key on `requirements.txt`), which is sufficient for this lab.

## Prerequisites

- Phase 00 (housekeeping) complete — repo is clean
- At least one LXC provisioned by the base Terraform/Ansible pattern (see `terraform/lxc/stacks/harbor-stack/` as reference)
- SSH access to Proxmox host

## IP / VMID allocation

| Service | IP | VMID | Zone |
|---|---|---|---|
| apt-cacher-ng | `192.168.1.35` | 142 | `mgmt_seg` |

Check NetBox for confirmed availability before assigning. Adjust if `.35` is already taken.

---

## Part A — apt-cacher-ng apt proxy

### Why apt-cacher-ng

- 50 MB Debian binary, ~128 MB RAM at rest, zero configuration beyond the default
- Caches Debian apt packages on first pull; subsequent requests are served locally
- All LXCs and the CI runner route `apt-get install` through it automatically
- Scales fine for a lab of up to ~20 nodes

### A1 — Stack file

Create `terraform/lxc/stacks/apt-cacher-stack/stack.yaml`:

```yaml
# apt-cacher-ng transparent apt proxy — management zone
hostname: apt-cacher-stack
ip_address: "192.168.1.35/24"
gateway: "192.168.1.1"
vmid: 142
cores: 1
memory: 256
swap: 128
rootfs_size: 8
rootfs_storage: infrastructure-containers
docker_storage_size: "20G"    # cache storage; resize if usage demands
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - apt-cache
  - infrastructure
  - build

ansible_playbook: "deploy-apt-cacher-stack"
portainer_agent: false        # no Docker, so no Portainer agent needed
```

> The `docker_storage_size` pool is reused here as the apt package cache volume. If the stack module only supports Docker storage, add a dedicated data volume instead. The key requirement is that the cache persists between LXC reboots.

### A2 — Ansible playbook

Create `terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml`:

```yaml
---
- name: Deploy apt-cacher-ng
  hosts: apt_cacher_stack
  become: true

  tasks:
    - name: Install apt-cacher-ng
      ansible.builtin.apt:
        name: apt-cacher-ng
        state: present
        update_cache: true

    - name: Ensure apt-cacher-ng is enabled and running
      ansible.builtin.systemd:
        name: apt-cacher-ng
        enabled: true
        state: started

    - name: Configure PassThroughPattern to allow HTTPS passthrough
      ansible.builtin.lineinfile:
        path: /etc/apt-cacher-ng/acng.conf
        regexp: "^#?PassThroughPattern:"
        line: "PassThroughPattern: .*"
      notify: Restart apt-cacher-ng

    - name: Open port 3142 in UFW (if UFW is enabled)
      community.general.ufw:
        rule: allow
        port: "3142"
        proto: tcp
      when: ansible_facts.packages['ufw'] is defined

  handlers:
    - name: Restart apt-cacher-ng
      ansible.builtin.systemd:
        name: apt-cacher-ng
        state: restarted
```

### A3 — Configure all LXCs to use the proxy

Add the following task to the **base LXC Ansible role** (or the common tasks file applied to all LXCs). File: `terraform/lxc/ansible/roles/base-lxc/tasks/main.yml` (or equivalent):

```yaml
- name: Configure apt to use apt-cacher-ng proxy
  ansible.builtin.copy:
    dest: /etc/apt/apt.conf.d/01proxy
    content: |
      Acquire::http::Proxy "http://192.168.1.35:3142";
    owner: root
    group: root
    mode: "0644"
```

Apply this change to:
- All new LXC stacks deployed from Phase 04 onwards
- The CI runner (VMID 141, deployed in Phase 01) — re-run its playbook to add the proxy config

### A4 — Configure the CI runner

After deploying apt-cacher-ng, re-run the CI runner deploy playbook to add the proxy:

```bash
# From the repo root:
ansible-playbook \
  -i terraform/lxc/ansible/inventory \
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml \
  --tags apt-proxy
```

Or add the `01proxy` file task to the CI runner playbook directly (see A3).

### A5 — Verify caching is working

After deploying the first LXC that uses the proxy:

```bash
# From any LXC that has the proxy configured:
apt-get update && apt-get install -y curl

# On the apt-cacher-ng host, check the cache statistics:
curl http://localhost:3142/acng-report.html
```

You should see cache hit counts increase on subsequent `apt-get` runs.

---

## Part B — Terraform provider filesystem mirror

### Why a filesystem mirror

Terraform/OpenTofu can use a local directory as a provider mirror instead of fetching from `registry.terraform.io` on every `terraform init`. For a lab, this is the simplest approach:

- No running service required
- Mirror directory is committed to the repo (or stored in CI cache)
- Every CI `terraform init` uses the local mirror: zero external network dependency
- Keeps provider versions pinned to what is tested locally

### B1 — Create the mirror

Run this **once** on your workstation from the repo root:

```bash
# Ensure you have the providers used across all terraform configurations:
cd terraform

# Mirror providers for the LXC module (most common):
terraform providers mirror ./terraform-providers

# This creates a filesystem mirror structure under terraform/terraform-providers/:
# terraform/terraform-providers/
#   registry.terraform.io/
#     bpg/proxmox/
#       <version>/
#         terraform-provider-proxmox_<version>_linux_amd64.zip
#         ...
```

Run the mirror command from each environment directory that has unique provider requirements:

```bash
terraform -chdir=lxc providers mirror ../terraform-providers
# (add other environment directories if they have different providers)
```

### B2 — Configure Terraform to use the mirror

Create (or update) `~/.terraformrc` on the workstation and on **ci-runner-01**:

```hcl
# ~/.terraformrc
provider_installation {
  filesystem_mirror {
    path    = "/home/steve/git/proxmox-homelab/terraform/terraform-providers"
    include = ["registry.terraform.io/*/*"]
  }
  direct {
    exclude = ["registry.terraform.io/*/*"]
  }
}
```

On the CI runner, set the path to the cloned repo location:

```hcl
# /root/.terraformrc  (or /home/ci-runner/.terraformrc)
provider_installation {
  filesystem_mirror {
    path    = "/home/ci-runner/workspace/proxmox-homelab/terraform/terraform-providers"
    include = ["registry.terraform.io/*/*"]
  }
  direct {
    exclude = ["registry.terraform.io/*/*"]
  }
}
```

Add this to `deploy-ci-runner.yml` as a templated task:

```yaml
- name: Configure Terraform provider filesystem mirror
  ansible.builtin.template:
    src: terraformrc.j2
    dest: "/root/.terraformrc"
    owner: root
    group: root
    mode: "0644"
```

With template `terraform/lxc/ansible/templates/terraformrc.j2`:

```hcl
provider_installation {
  filesystem_mirror {
    path    = "{{ terraform_mirror_path }}"
    include = ["registry.terraform.io/*/*"]
  }
  direct {
    exclude = ["registry.terraform.io/*/*"]
  }
}
```

Set `terraform_mirror_path` in the CI runner group vars or as a playbook variable.

### B3 — Commit the mirror to the repo

```bash
# Ensure the mirror directory is tracked:
git add terraform/terraform-providers/
git status  # verify provider zips are included

# If you want to exclude by default (and generate on first use instead), add to .gitignore:
# !terraform/terraform-providers/
```

Committing the mirror keeps providers pinned and CI hermetic. The directory will be a few hundred MB per provider. If repo size is a concern, use GitHub Actions `actions/cache@v4` instead:

```yaml
# In validate.yml, before terraform init:
- name: Cache Terraform providers
  uses: actions/cache@v4
  with:
    path: terraform/terraform-providers
    key: terraform-providers-${{ hashFiles('terraform/**/*.tf') }}
    restore-keys: terraform-providers-
```

**Recommendation for this lab:** Commit the mirror. The repo is private, the providers are small, and hermeticity is more important than repo size. If the repo grows, switch to `actions/cache@v4`.

### B4 — Update CI validate workflow

After setting up the mirror, verify CI uses it. In `.github/workflows/validate.yml`, the `terraform init` step should work without changes (the runner uses `~/.terraformrc`). Confirm with:

```bash
# On the runner, manually:
terraform init -backend=false   # should NOT fetch from internet
```

---

## Part C — Python / pip caching

No additional service is needed. GitHub Actions `actions/cache@v4` is sufficient for pip:

```yaml
# Already in (or add to) validate.yml if there are Python steps:
- name: Cache pip packages
  uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: pip-${{ hashFiles('requirements.txt') }}
    restore-keys: pip-
```

The self-hosted runner retains its `~/.cache/pip` directory between runs anyway, so this effectively gives permanent caching without any additional service.

---

## Commit and push

```bash
git checkout -b feat/apt-cacher-terraform-mirror dev/pve-test

# After creating all files:
git add \
  terraform/lxc/stacks/apt-cacher-stack/ \
  terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml \
  terraform/lxc/ansible/templates/terraformrc.j2 \
  terraform/terraform-providers/ \
  docs/plan/phase-03c-artifact-proxy.md

git commit -m "feat(infra): add apt-cacher-ng proxy and Terraform provider filesystem mirror"
git push origin feat/apt-cacher-terraform-mirror
# Merge to dev/pve-test via PR
```

---

## Acceptance criteria

### apt-cacher-ng
- [ ] apt-cacher-ng LXC running at `192.168.1.35` (VMID 142)
- [ ] `curl http://192.168.1.35:3142/acng-report.html` returns stats page
- [ ] `/etc/apt/apt.conf.d/01proxy` present on all new LXCs and on ci-runner-01
- [ ] Second `apt-get update` on any proxied LXC hits the cache (verify via stats page)
- [ ] apt-cacher-ng registered in NetBox

### Terraform provider mirror
- [ ] `terraform/terraform-providers/` directory exists and is committed
- [ ] `~/.terraformrc` configured on workstation and on ci-runner-01 with `filesystem_mirror`
- [ ] `terraform init` on ci-runner-01 completes without fetching from `registry.terraform.io`
- [ ] All provider versions match what is specified in `terraform/lxc/versions.tf` (or equivalent)

### Python / pip
- [ ] `actions/cache@v4` configured for pip in `validate.yml`
- [ ] Confirmed: no Pip Index Service / Nexus proxy needed

## Observations

- Apt proxy verification on ci-runner-01 is most reliable with a repeatable package download, not `apt-get update` alone.
- `apt-config dump` confirms the runner sees `Acquire::http::Proxy`, even when the cache report requires the counted view to show hits.
- The runner playbook should be launched from `terraform/lxc/ansible/` with the generated stack inventory so the shared LXC role and SSH options resolve correctly.
- `sonar-scanner` is available in the local install under `/home/steve/.local/bin/sonar-scanner`, even though it is not on the default PATH in this shell.
