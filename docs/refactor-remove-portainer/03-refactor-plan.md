# Refactor Plan — Terraform/Ansible Separation + Platform Portainer Removal

> Legacy draft note
>
> This file is retained as historical planning context only.
>
> Do not execute from this document. The active task package is now the rest of
> `docs/refactor-remove-portainer/`, especially `README.md`, `decisions.md`,
> `task-sequence.md`, `runbook.md`, `tasks/`, and `prompts/`.

**Status:** Draft — not yet merged into proxmox-homelab
**Prerequisites:** Documents 01 and 02 reviewed and agreed
**Branch strategy:** Cut `refactor/provision-separation` from `dev/pve-test`; merge back when complete

---

## Scope

This plan refactors the codebase to implement:

1. Removal of Ansible `local-exec` provisioners from Terraform
2. A new `scripts/provision.sh` orchestration script for the Ansible phase
3. A new `direct_stack` Ansible role for Tier 1 (platform) stack deployment
4. Removal of `portainer_agent` from Tier 1 LXC stacks
5. A second LXC OS template without Portainer agent (`debian-13-docker-platform`)
6. Classification of all stacks into `deployment_tier: platform` or `deployment_tier: apps`
7. Updated `stack.yaml` files for all existing stacks
8. Updated `PLATFORM_CONTRACT.md` and architecture documentation

---

## Task sequence

Tasks must be completed in the order below. Each task has an explicit entry and exit
condition. Tasks within the same group can be done in parallel.

---

### Group A — New Ansible role: `direct_stack`

**Entry condition:** None
**Exit condition:** Role exists at `terraform/lxc/ansible/roles/direct_stack/`, passes
`ansible-lint`, and has a working test against a scratch LXC

#### A-1: Create `direct_stack` role

Create `terraform/lxc/ansible/roles/direct_stack/` with the following structure:

```
direct_stack/
  defaults/main.yml
  tasks/main.yml
```

**`defaults/main.yml`:**

```yaml
direct_stack_compose_dir: "/srv/docker/{{ direct_stack_name }}"
direct_stack_compose_path: "{{ direct_stack_compose_dir }}/docker-compose.yml"
direct_stack_name: "{{ inventory_hostname }}"
direct_stack_compose_content: ""   # caller must set this
direct_stack_env: []               # list of {name: X, value: Y} dicts — matches app_stack interface
direct_stack_prune_on_update: true
```

**`tasks/main.yml`:**

```yaml
- name: Ensure compose directory exists
  ansible.builtin.file:
    path: "{{ direct_stack_compose_dir }}"
    state: directory
    mode: '0755'

- name: Write .env file for compose
  ansible.builtin.copy:
    dest: "{{ direct_stack_compose_dir }}/.env"
    content: "{{ direct_stack_env | map(attribute='name') | zip(direct_stack_env | map(attribute='value')) | map('join', '=') | join('\n') }}\n"
    mode: '0600'
  no_log: true

- name: Read current compose file (if exists)
  ansible.builtin.slurp:
    src: "{{ direct_stack_compose_path }}"
  register: direct_stack_current_compose
  failed_when: false

- name: Compute content hashes
  ansible.builtin.set_fact:
    direct_stack_current_sha: "{{ (direct_stack_current_compose.content | default('') | b64decode) | hash('sha256') }}"
    direct_stack_desired_sha: "{{ direct_stack_compose_content | hash('sha256') }}"

- name: Write compose file (if changed)
  ansible.builtin.copy:
    dest: "{{ direct_stack_compose_path }}"
    content: "{{ direct_stack_compose_content }}"
    mode: '0644'
  when: direct_stack_current_sha != direct_stack_desired_sha

- name: Validate compose file
  ansible.builtin.command:
    cmd: docker compose -f "{{ direct_stack_compose_path }}" config -q
    chdir: "{{ direct_stack_compose_dir }}"
  changed_when: false

- name: Deploy stack (up -d)
  ansible.builtin.command:
    cmd: >
      docker compose -f "{{ direct_stack_compose_path }}"
      {{ '--remove-orphans' if direct_stack_prune_on_update else '' }}
      up -d
    chdir: "{{ direct_stack_compose_dir }}"
  register: direct_stack_up_result
  changed_when: "'Started' in direct_stack_up_result.stderr or 'Created' in direct_stack_up_result.stderr"
  when: direct_stack_current_sha != direct_stack_desired_sha

- name: No-change result
  ansible.builtin.debug:
    msg: "Stack '{{ direct_stack_name }}' is up-to-date (no changes needed)"
  when: direct_stack_current_sha == direct_stack_desired_sha
```

**Note:** The env var interface (`direct_stack_env` as a list of `{name, value}` dicts)
intentionally mirrors `app_stack_env` so playbooks can switch between the two roles with
minimal changes.

#### A-2: Update existing Tier 1 playbooks to use `direct_stack`

For each platform playbook that currently calls `app_stack`, replace the role call:

```yaml
# Before
- role: app_stack
  vars:
    app_stack_name: "harbor"
    app_stack_compose_content: "{{ lookup('file', 'files/harbor-compose.yml') }}"
    app_stack_env: "{{ harbor_env_vars }}"

# After
- role: direct_stack
  vars:
    direct_stack_name: "harbor"
    direct_stack_compose_content: "{{ lookup('file', 'files/harbor-compose.yml') }}"
    direct_stack_env: "{{ harbor_env_vars }}"
```

Playbooks to update:

- `deploy-harbor-stack.yml`
- `deploy-authentik-stack.yml`
- `deploy-monitoring-stack.yml`
- `deploy-proxy-stack.yml` (Traefik)
- `deploy-netbox-stack.yml`
- `deploy-portainer-stack.yml` (Portainer itself — special case, see A-3)
- Any other platform playbooks using `app_stack`

#### A-3: Portainer playbook — special case

Portainer is deployed by Ansible but cannot register itself via its own API. The
`deploy-portainer-stack.yml` playbook should:

1. Use `direct_stack` to deploy the Portainer compose stack
2. Skip the `portainer_api` registration step entirely (Portainer does not register itself)

---

### Group B — Remove `portainer_agent` from Tier 1 stacks

**Entry condition:** Group A complete
**Exit condition:** No Tier 1 `stack.yaml` has `portainer_agent: true`; no Tier 1 playbook
calls the `portainer_agent` role

#### B-1: Update `stack.yaml` for all Tier 1 stacks

Add `deployment_tier: platform` and remove or set `portainer_agent: false` for:

```
stacks/portainer-stack/stack.yaml
stacks/harbor-stack/stack.yaml
stacks/authentik-stack/stack.yaml
stacks/step-ca-stack/stack.yaml
stacks/monitoring-stack/stack.yaml     (or equivalent name)
stacks/proxy-stack/stack.yaml          (Traefik)
stacks/dns-stack/stack.yaml            (CoreDNS)
stacks/netbox-stack/stack.yaml
stacks/apt-cacher-stack/stack.yaml
stacks/ci-runner-01/stack.yaml
```

#### B-2: Update `stack.yaml` for all Tier 2 stacks

Add `deployment_tier: apps` and confirm `portainer_agent: true` for all Phase 06 stacks
(pihole-stack, arr-stack, jellyfin-stack, game-stack) when they are created.

#### B-3: Remove `portainer_agent` role calls from Tier 1 playbooks

Verify no Tier 1 playbook includes the `portainer_agent` role. The `portainer_api`
registration role should also be removed from Tier 1 playbooks — it is only needed by Tier 2
stacks to register their agents with Portainer.

---

### Group C — Build second LXC OS template

**Entry condition:** None (can run in parallel with Groups A and B)
**Exit condition:** Two templates available on `pve-test` storage; each `stack.yaml` references the correct template

#### C-1: Add `platform` template build to `build-debian-13-template.yml`

The existing build playbook already has `install_portainer_agent` as a variable. Add a
second invocation block or a parameterised build profile:

```yaml
# In ansible/00-initial-setup/build-debian-13-template.yml
# Add a second template build target:
- name: Build platform template (no Portainer agent)
  vars:
    install_portainer_agent: false
    template_name: "debian-13-docker-platform"
  # ... rest of build tasks
```

The resulting template is stored as:
`storage-template:vztmpl/debian-13-docker-platform.tar.gz`

The existing template (with agent) is renamed for clarity:
`storage-template:vztmpl/debian-13-docker-apps.tar.gz`

#### C-2: Update `ostemplate` in all `stack.yaml` files

| Tier | `ostemplate` value |
|---|---|
| `platform` | `storage-template:vztmpl/debian-13-docker-platform.tar.gz` |
| `apps` | `storage-template:vztmpl/debian-13-docker-apps.tar.gz` |

---

### Group D — Remove `local-exec` Ansible provisioners from Terraform

**Entry condition:** Groups A, B, C complete and validated on a scratch LXC
**Exit condition:** `main.tf` contains no `local-exec` calls to `ansible-playbook`; `terraform apply` only provisions infrastructure

#### D-1: Remove Ansible provisioner blocks from `main.tf`

Remove or comment out the following `null_resource` blocks:

- `null_resource.ansible_provision` (the main playbook runner, ~line 425)
- `null_resource.portainer_register` (agent registration trigger)
- `null_resource.keyctl` (if it calls Ansible — replace with direct SSH task in `provision.sh`)
- `null_resource.wait_for_ssh` (move SSH readiness check to Ansible via `wait_for_connection`)

The `local_file.ansible_inventory` resource is **retained** — Terraform still generates inventories.

#### D-2: Remove `ansible_playbook` field handling from `main.tf`

The `ansible_playbook` field in `stack.yaml` is no longer consumed by Terraform. It remains
in `stack.yaml` as the reference that `provision.sh` uses to determine which playbook to run.
Remove the Terraform locals and conditionals that reference it for the purpose of triggering
`local-exec`.

#### D-3: Remove `portainer_server_ip` from generated inventory (Tier 1 only)

For Tier 1 stacks, `portainer_server_ip` in the generated inventory is unused. It can be
omitted by adding a conditional to `templates/inventory.tpl` or by removing it globally
since Tier 2 stacks can still reference it from `variables.tf` defaults.

#### D-4: Validate `terraform plan` is clean

After D-1 and D-2, run:

```bash
./with-secrets terragrunt run-all plan
```

Expected: no diff except for the removed null_resource blocks. No infrastructure changes.

---

### Group E — Create `scripts/provision.sh`

**Entry condition:** Group D complete
**Exit condition:** `provision.sh` runs all platform stacks cleanly against a fresh `pve-test` deployment

#### E-1: Write `scripts/provision.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev parse --show-toplevel)"
ANSIBLE_DIR="${REPO_ROOT}/terraform/lxc/ansible"
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"

TIER="all"
TARGET_STACK=""
CHECK_MODE=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --tier) TIER="$2"; shift 2 ;;
    --stack) TARGET_STACK="$2"; shift 2 ;;
    --check) CHECK_MODE="--check"; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

run_playbook() {
  local stack_dir="$1"
  local stack_name
  stack_name=$(basename "$stack_dir")
  local inventory="${stack_dir}/inventory.yml"
  local playbook

  if [[ ! -f "${inventory}" ]]; then
    echo "SKIP ${stack_name}: no inventory.yml (Terraform not yet applied?)"
    return
  fi

  playbook=$(yq '.all.hosts.*.ansible_playbook // ""' "${inventory}" 2>/dev/null || true)

  if [[ -z "${playbook}" ]]; then
    echo "SKIP ${stack_name}: no ansible_playbook set"
    return
  fi

  echo "--- Provisioning ${stack_name} (playbook: ${playbook}) ---"
  ANSIBLE_HOST_KEY_CHECKING=False \
  ANSIBLE_CONFIG="${ANSIBLE_DIR}/ansible.cfg" \
  ANSIBLE_ROLES_PATH="${ANSIBLE_DIR}/roles" \
    ansible-playbook ${CHECK_MODE} \
      -i "${inventory}" \
      "${ANSIBLE_DIR}/playbooks/${playbook}.yml"
}

# Platform stacks — always first
PLATFORM_STACKS=(
  portainer-stack
  harbor-stack
  apt-cacher-stack
  ci-runner-01
  dns-stack
  step-ca-stack
  authentik-stack
  proxy-stack
  monitoring-stack
  netbox-stack
)

# App stacks — after platform
APP_STACKS=(
  pihole-stack
  arr-stack
  jellyfin-stack
  game-stack
)

if [[ -n "${TARGET_STACK}" ]]; then
  run_playbook "${STACKS_DIR}/${TARGET_STACK}"
  exit 0
fi

if [[ "${TIER}" == "platform" || "${TIER}" == "all" ]]; then
  for stack in "${PLATFORM_STACKS[@]}"; do
    [[ -d "${STACKS_DIR}/${stack}" ]] && run_playbook "${STACKS_DIR}/${stack}"
  done
fi

if [[ "${TIER}" == "apps" || "${TIER}" == "all" ]]; then
  for stack in "${APP_STACKS[@]}"; do
    [[ -d "${STACKS_DIR}/${stack}" ]] && run_playbook "${STACKS_DIR}/${stack}"
  done
fi
```

#### E-2: Make executable and add to repo

```bash
chmod +x scripts/provision.sh
git add scripts/provision.sh
```

---

### Group F — Update documentation

**Entry condition:** Groups A–E complete
**Exit condition:** `PLATFORM_CONTRACT.md`, `README.md`, and affected phase docs are consistent with the new model

#### F-1: Update `PLATFORM_CONTRACT.md`

- Remove `portainer_api` and `app_stack` from the "Shared Ansible roles" list for Tier 1
- Add `direct_stack` to the shared roles list
- Add `deployment_tier` to the stack.yaml field reference table
- Update the `portainer_server_ip` platform variable entry — note it is Tier 2 only
- Remove the `portainer_agent` default value note (it is no longer a global default)

#### F-2: Update `docs/design/architecture.md`

- Replace ADR-04 with the revised text from document 01 of this draft
- Add a note under FR-01 that provisioning and configuration are separate phases
- Update SEC-02 scope to Tier 2 application stacks only

#### F-3: Update phase documents

- `phase-00b-pve-test-management.md` — note Portainer is now Tier 2 management UI only
- `phase-04-core-shared-services.md` — note all Phase 04 services are Tier 1 / `direct_stack`
- `phase-06-app-stacks.md` — add note that app stacks use Tier 2 path / `app_stack` role

#### F-4: Update `terraform/lxc/README.md`

Add section describing the two-phase deployment model and `provision.sh`.

---

## Validation sequence (full rebuild)

After all groups are complete, validate with a full pve-test wipe-and-rebuild:

```bash
# 1. Wipe pve-test
./with-secrets terragrunt run-all destroy

# 2. Provision all LXCs
./with-secrets terragrunt run-all apply

# 3. Configure platform tier
./with-secrets ./scripts/provision.sh --tier platform

# 4. Smoke test platform
curl -k https://10.57.3.10/api/v2.0/ping      # Harbor
curl -k https://10.57.1.11/health             # step-ca
curl -k https://10.57.2.10/ping               # Traefik

# 5. Confirm Portainer has zero agents registered (platform LXCs absent)
# Portainer UI: Environments page should be empty until app stacks are deployed

# 6. (Phase 06 only) Configure application tier
./with-secrets ./scripts/provision.sh --tier apps
```

---

## Acceptance criteria

- [ ] `terragrunt run-all apply` completes without invoking Ansible
- [ ] `provision.sh --tier platform` configures all platform stacks to a healthy state
- [ ] Portainer UI shows no registered environments after platform provisioning
- [ ] `provision.sh --tier apps` deploys Tier 2 stacks and they appear in Portainer
- [ ] `provision.sh` is idempotent — second run produces no changes
- [ ] `ansible-lint` passes on the `direct_stack` role
- [ ] All platform stack smoke tests pass (see validation sequence)
- [ ] `snyk iac test terraform/` is clean
- [ ] `sonar-scanner` reports no new issues

---

## Risk and rollback

**Risk:** The `direct_stack` role does not yet exist — if it has defects, platform stacks
fail to deploy. Mitigation: test `direct_stack` against a single scratch LXC (Group A) before
migrating all platform stacks in Group B.

**Risk:** Removing `local-exec` provisioners means a single `terragrunt apply` no longer
produces a fully configured system. Mitigation: the README and phase documentation are updated
in Group F to make the two-step process explicit before the change is merged.

**Rollback:** The refactor branch can be abandoned at any point before merge. The
`local-exec` model in `main.tf` is the fallback. No Terraform state changes are required to
roll back — only the `main.tf` and role changes are in flight.
