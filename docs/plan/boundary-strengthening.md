# Monorepo Boundary Strengthening — Code Change Plan

This plan implements the three practical next steps from the monorepo architecture
review. Documentation is already done (STACK_CONTRACT.md per stack,
PLATFORM_CONTRACT.md, NETWORK_CONTRACT.md). This file covers the remaining code
changes.

---

## Change 1 — Add `depends_on` and `provides` to each `stack.yaml`

Adds explicit dependency and service declarations. No functional effect — pure
metadata for AI context and human readability.

### harbor-stack/stack.yaml
```yaml
depends_on:
  - portainer-stack

provides:
  - service: registry-http
    port: 80
    protocol: tcp
  - service: registry-https
    port: 443
    protocol: tcp
```

### apt-cacher-stack/stack.yaml
```yaml
depends_on: []

provides:
  - service: apt-proxy
    port: 3142
    protocol: tcp
```

### netbox-stack-test/stack.yaml
```yaml
depends_on:
  - harbor-stack
  - portainer-stack

provides:
  - service: netbox-http
    port: 8080
    protocol: tcp
```

### portainer-stack/stack.yaml
```yaml
depends_on: []

provides:
  - service: portainer-http
    port: 9000
    protocol: tcp
  - service: portainer-https
    port: 9443
    protocol: tcp
  - service: portainer-edge
    port: 8000
    protocol: tcp
```

### authentik-stack/stack.yaml
```yaml
depends_on:
  - harbor-stack
  - portainer-stack

provides:
  - service: authentik-http
    port: 9000
    protocol: tcp
  - service: authentik-https
    port: 9443
    protocol: tcp
```

### step-ca-stack/stack.yaml
```yaml
depends_on:
  - apt-cacher-stack

provides:
  - service: step-ca-acme
    port: 443
    protocol: tcp
```

### ci-runner-01/stack.yaml
```yaml
depends_on:
  - harbor-stack
  - apt-cacher-stack
  - portainer-stack

provides: []
```

---

## Change 2 — Fix hardcoded registry IP in authentik (pve vs pve-test mismatch)

**Root cause:** `deploy-authentik-stack.yml` and `docker-compose.yml` both hardcode
`192.168.1.10` (the pve Harbor address). On pve-test, Harbor is at `10.57.3.10`.
A pve-test authentik deployment silently uses the wrong registry.

### 2a. `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml` — line 23

```yaml
# Before:
authentik_registry_host: "192.168.1.10"

# After:
authentik_registry_host: "{{ registry_host | default('10.57.3.10') }}"
```

`registry_host` is a host var from the generated inventory (see Change 3 below).
The `default('10.57.3.10')` is a safe fallback that already points to pve-test.

Also add `REGISTRY_HOST` to the `.env` write task so Docker Compose can expand
`${REGISTRY_HOST}` in the compose file:

```yaml
# In the "Write Authentik environment file" task, in content: |
REGISTRY_HOST={{ authentik_registry_host }}
# (add alongside AUTHENTIK_SECRET_KEY and AUTHENTIK_POSTGRES_PASSWORD)
```

### 2b. `terraform/lxc/stacks/authentik-stack/docker-compose.yml`

Replace all 4 occurrences of `192.168.1.10` with `${REGISTRY_HOST}`. Example:

```yaml
# Before:
image: 192.168.1.10/dockerhub/library/postgres:16-alpine

# After:
image: ${REGISTRY_HOST}/dockerhub/library/postgres:16-alpine
```

Update the comment at the top:
```yaml
# Before:
# All images are routed through Harbor proxy cache at 192.168.1.10.

# After:
# All images are routed through Harbor proxy cache at ${REGISTRY_HOST}.
# REGISTRY_HOST is written to .env by deploy-authentik-stack.yml.
# pve-test: 10.57.3.10  pve: 192.168.1.10
```

---

## Change 3 — Wire `registry_host` and `apt_cacher_host` through the platform layer

This replaces all remaining per-playbook hardcoding with a single variable flow:
`.env.pve-test` → `TF_VAR_*` → `variables.tf` → `inventory.tpl` → host vars →
Ansible tasks.

### 3a. `terraform/lxc/variables.tf` — add after `portainer_server_ip`:

```hcl
variable "registry_host" {
  description = "Hostname or IP of the Harbor registry used for Docker image pulls (pve: 192.168.1.10, pve-test: 10.57.3.10)"
  type        = string
  default     = "192.168.1.10"
}

variable "apt_cacher_host" {
  description = "IP of the apt-cacher-ng proxy (pve: 192.168.1.35, pve-test: 10.57.3.11). Empty string skips proxy configuration."
  type        = string
  default     = "192.168.1.35"
}
```

### 3b. `terraform/lxc/templates/inventory.tpl` — add after `portainer_server_ip: ...`:

```
          registry_host: ${registry_host}
          apt_cacher_host: ${apt_cacher_host}
```

### 3c. `terraform/lxc/main.tf` — in the `templatefile()` call (around line 302):

```hcl
# Add alongside portainer_server_ip:
registry_host   = try(local.stack.registry_host, var.registry_host)
apt_cacher_host = try(local.stack.apt_cacher_host, var.apt_cacher_host)
```

### 3d. `.env.pve-test` — add if not already present:

```sh
export TF_VAR_registry_host=10.57.3.10
export TF_VAR_apt_cacher_host=10.57.3.11
```

### 3e. `terraform/lxc/ansible/roles/lxc_base/tasks/main.yml` — parameterize apt proxy:

```yaml
# Before:
- name: Configure apt to use apt-cacher-ng proxy
  ansible.builtin.copy:
    dest: /etc/apt/apt.conf.d/01proxy
    content: |
      Acquire::http::Proxy "http://192.168.1.35:3142";
    owner: root
    group: root
    mode: "0644"

# After:
- name: Configure apt to use apt-cacher-ng proxy
  ansible.builtin.copy:
    dest: /etc/apt/apt.conf.d/01proxy
    content: |
      Acquire::http::Proxy "http://{{ apt_cacher_host }}:3142";
    owner: root
    group: root
    mode: "0644"
  when: apt_cacher_host | default('') | length > 0
```

---

## Deployment order (implied by declared dependencies)

```
Wave 1 (parallel):
  apt-cacher-stack   — no deps
  portainer-stack    — no deps

Wave 2 (parallel, after Wave 1):
  harbor-stack       — needs portainer-stack
  step-ca-stack      — needs apt-cacher-stack

Wave 3 (parallel, after Wave 2):
  netbox-stack-test  — needs harbor-stack + portainer-stack
  authentik-stack    — needs harbor-stack + portainer-stack
  ci-runner-01       — needs harbor-stack + apt-cacher-stack + portainer-stack
```

---

## Files changed summary

| File | Change |
|------|--------|
| `stacks/*/stack.yaml` (7 files) | Add `depends_on` + `provides` |
| `stacks/authentik-stack/docker-compose.yml` | `192.168.1.10` → `${REGISTRY_HOST}` |
| `ansible/playbooks/deploy-authentik-stack.yml` | Read `registry_host` from inventory var |
| `variables.tf` | Add `registry_host` + `apt_cacher_host` |
| `templates/inventory.tpl` | Add two host vars |
| `main.tf` | Pass new vars through templatefile |
| `.env.pve-test` | Add two `TF_VAR_*` exports |
| `ansible/roles/lxc_base/tasks/main.yml` | Parameterize apt proxy URL |
