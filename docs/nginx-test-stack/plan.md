# nginx-test-stack plan -- pass 1 (deploy + provision only)

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Intended to be executed with
`.github/prompts/implement-step.prompt.md`, one step at a time.

**Scope of this pass, explicitly:** stand up `nginx-test-stack` as an
isolated, un-integrated LXC on `pve-test-vm` and confirm it serves
traffic. No Traefik, no technitium DNS record, no monitoring wiring --
those are deliberately deferred to a second, later plan-change run
against a freshly-recreated container, per the operator's own framing of
this exercise. Do not add integration steps to this file; write a new
`docs/<workspace>/plan.md` for that pass instead.

**Revision 2026-08-26: dropped `scaffold-stack.sh`/OpenCode from this
plan.** The first version of this plan reused
`terraform/lxc/scaffold-stack.sh`, this repo's standard tool for
authoring a new stack's five files, per `step-packet-schema.md`'s
"Reuse scaffold-stack.sh for new stacks specifically" section. That tool
shells out to OpenCode (a second local-agent runtime, separate from
Laguna/Copilot) to get per-agent tool-permission denial, because a
single general-purpose agent asked to author all five files in one
open-ended task was previously found to invent things. The operator does
not want a second agent runtime introduced for this exercise, and step
`nginx-test-stack-01` already demonstrated Laguna can transcribe literal
content into a new file with zero drift when given an unambiguous,
narrowly-scoped instruction -- the same technique the five OpenCode
sub-agents use internally, just executed directly by Laguna instead.
Steps `02`-`06` below replace the single `scaffold-stack.sh` step with
five such literal-content steps; no OpenCode or `scaffold-stack.sh`
involvement remains anywhere in this plan. This is a scope decision for
*this* exercise, not a change to the repo's general recommendation to
reuse `scaffold-stack.sh` for other new stacks.

## Research this plan is based on

- `terraform/lxc/stacks/stack-request.example.yaml` and the
  `minecraft-stack` exemplar it documents
  (`docs/stack-lifecycle-refactor/stage-10-minecraft-exemplar.md`) -- the
  concrete, already-validated shape for `stack_yaml`,
  `compose_requirements`/`compose_forbidden`, `contract_facts`, and
  `playbook_content` content reused directly below (now transcribed
  straight into each real file instead of via a `stack-request.yaml`
  intermediate -- see the revision note above).
- Every `terraform/lxc/stacks/*/stack.yaml` was checked for VMID and
  `192.168.1.0/24` IP collisions: VMID `161` and `192.168.1.54/24` are
  both free. `docker-socket-proxy-test` (VMID `160`, `.53`) is the
  closest existing disposable test-tier stack and is the template for
  `deployment_tier`, tags, sizing, and network placement -- its own
  compose file even uses nginx as its harmless workload image, at
  `${REGISTRY_HOST}/dockerhub/library/nginx:stable-alpine`, confirming
  the same Harbor-proxy-cache path used below.
- Bare `docker.io` is never used directly for image pulls in this repo --
  every compose file that pulls a public image goes through Harbor's
  proxy-cache path
  (`harbor.lab.gibbsgreatly.xyz/dockerhub/<namespace>/<image>:<tag>`),
  confirmed against `terraform/lxc/stacks/harness-target/docker-compose.yml`
  (`harbor.lab.gibbsgreatly.xyz/dockerhub/vulhub/struts2:2.3.30`,
  `.../dockerhub/library/redis:7.4`) and `docker-socket-proxy-test`.
- `terraform/lxc/validate-compose.py` accepts an explicit `--stack` flag
  (unlike `validate-stack-metadata.py`, whose `ACTIVE_STACKS` tuple is a
  small fixed list of platform stacks with no override) -- so
  `validate-compose.sh --stack nginx-test-stack` genuinely checks this
  new stack's real compose file, not a no-op. Confirmed by reading both
  scripts and running the compose validator against the actual file
  before writing this plan (see step `04` below).
- `terraform/lxc/validate-stack-metadata.py` has no per-stack override,
  so it's not a meaningful gate for a new disposable test-tier stack and
  is intentionally not used below.
- Every gate command below was actually run against real file content
  before being written into this plan (not just judged plausible): the
  literal `stack.yaml`, `docker-compose.yml`, `STACK_CONTRACT.md`,
  `terragrunt.hcl`, and playbook content were written to their real
  target paths, every gate command in steps `02`-`06` was run and
  confirmed to pass (`docker compose config` initially warned about an
  obsolete top-level `version:` key -- removed from the literal content
  below, after which the warning was gone and the gate stayed a clean
  exit 0), then the files were deleted again so Laguna performs the
  actual authoring per the plan.
- `terraform/lxc/terragrunt.hcl` (root) stores each stack's Terraform
  state locally inside that stack's own directory
  (`${get_original_terragrunt_dir()}/terraform.tfstate`) -- so running
  `terragrunt apply` scoped to just `terraform/lxc/stacks/nginx-test-stack/`
  is isolated from every other stack's state, not a shared blast radius.
  This is the additive-only Terraform tier in the root `CLAUDE.md`. The
  exact single-stack invocation shape -- `terragrunt plan --working-dir`
  and `terragrunt apply --working-dir ... -auto-approve -no-color`, each
  pointed at one stack's own directory -- matches the precedent already
  used across
  `docs/productionize-refactor/runbooks/*-canary-*-checklist.md`.

## Decisions (resolved with the operator before writing this plan)

- Stack name: `nginx-test-stack` (operator's explicit choice over plain
  `nginx-stack`, precisely because this is a throwaway validation pass,
  matching the `-test` suffix precedent of `docker-socket-proxy-test`).
- Network placement: plain LAN bridge (vmbr0), `deployment_tier: test`,
  no SDN zone -- matches every other disposable test-tier stack. Zone
  choice for eventual integration (pass 2) is out of scope here; that
  container gets destroyed before pass 2 starts, so there is no reason to
  pre-commit a zone now.
- No persistent state, no Portainer fleet membership (`portainer_agent:
  false`) -- consistent with this being the simplest possible first pass.
- No OpenCode/`scaffold-stack.sh` in this plan (see revision note above)
  -- Laguna authors all five stack files directly from literal content.

---

## Step: nginx-test-stack-01-stack-request

**Status: done (2026-08-26).** Kept as-is; its output,
`terraform/lxc/stacks/nginx-test-stack/stack-request.yaml`, is no longer
consumed by anything now that `scaffold-stack.sh` is out of this plan --
it stays only as a historical record of original intent, exactly as
`stack-request.example.yaml`'s own comment allows ("delete or keep as a
record of intent -- either is fine"). Steps `02`-`06` below re-derive the
same facts directly into the real files, so nothing needs to be re-run
because of the revision.

```yaml
id: nginx-test-stack-01-stack-request
title: Author stack-request.yaml for nginx-test-stack
model_hint: local
depends_on: []
status: done
```

---

## Step: nginx-test-stack-02-stack-yaml

```yaml
id: nginx-test-stack-02-stack-yaml
title: Author stack.yaml for nginx-test-stack
model_hint: local
depends_on: [nginx-test-stack-01-stack-request]

change: >
  Create terraform/lxc/stacks/nginx-test-stack/stack.yaml containing
  exactly the literal YAML content in the block immediately below --
  transcribe it verbatim, same keys, same values, same order. Do not add
  a network: block or any other block not present below, even if it
  would look more complete -- this repo's stack.yaml schema is entirely
  project-specific.

scope:
  allowed_paths:
    - terraform/lxc/stacks/nginx-test-stack/stack.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Modeling this file on any other stack's stack.yaml instead of using the literal content below"

gates:
  - id: yaml-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/nginx-test-stack/stack.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: hostname-matches
    cmd: "grep -q '^hostname: nginx-test-stack$' terraform/lxc/stacks/nginx-test-stack/stack.yaml"
    expect: "exit 0"
    critical: true
```

### Literal file content for `nginx-test-stack-02-stack-yaml`

```yaml
hostname: nginx-test-stack
ip_address: 192.168.1.54/24
gateway: 192.168.1.1
dns_server: 192.168.1.1
vmid: 161
cores: 1
memory: 512
swap: 512
rootfs_size: 8
storage_profile: platform-default
docker_storage_size: 4G
template_name: debian-13.1-2-docker-template.tar.gz
tags:
- docker
- disposable
- test
depends_on: []
provides:
- service: nginx-http
  port: 80
  protocol: tcp
ansible_playbook: deploy-nginx-test-stack
deployment_tier: test
portainer_agent: false
```

---

## Step: nginx-test-stack-03-compose

```yaml
id: nginx-test-stack-03-compose
title: Author docker-compose.yml for nginx-test-stack
model_hint: local
depends_on: [nginx-test-stack-01-stack-request]

change: >
  Create terraform/lxc/stacks/nginx-test-stack/docker-compose.yml
  containing exactly the literal YAML content in the block immediately
  below -- transcribe it verbatim. Do not add a version: key (obsolete in
  current Compose and produces a warning), a top-level networks: block,
  any volumes or bind mounts, a second service, or any environment
  variables -- the stock nginx image needs none of that for this pass.

scope:
  allowed_paths:
    - terraform/lxc/stacks/nginx-test-stack/docker-compose.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Adding anything not in the literal content below, even if a typical nginx Compose tutorial would include it"

gates:
  - id: compose-lint
    cmd: "terraform/lxc/validate-compose.sh --stack nginx-test-stack"
    expect: "exit 0, \"Compose validation passed\""
    critical: true
  - id: compose-config-valid
    cmd: "cd terraform/lxc/stacks/nginx-test-stack && docker compose config"
    expect: "exit 0, no warnings"
    critical: true
```

### Literal file content for `nginx-test-stack-03-compose`

```yaml
services:
  nginx:
    image: harbor.lab.gibbsgreatly.xyz/dockerhub/library/nginx:1.27-alpine
    container_name: nginx-test-stack-nginx
    ports:
      - "80:80/tcp"
    restart: unless-stopped
```

---

## Step: nginx-test-stack-04-contract

```yaml
id: nginx-test-stack-04-contract
title: Author STACK_CONTRACT.md for nginx-test-stack
model_hint: local
depends_on: [nginx-test-stack-01-stack-request]

change: >
  Create terraform/lxc/stacks/nginx-test-stack/STACK_CONTRACT.md
  containing exactly the literal Markdown content in the block
  immediately below -- transcribe it verbatim, same section headings and
  order as every other stack's STACK_CONTRACT.md (see
  terraform/lxc/stacks/apt-cacher-stack/STACK_CONTRACT.md for the shape
  this follows).

scope:
  allowed_paths:
    - terraform/lxc/stacks/nginx-test-stack/STACK_CONTRACT.md
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: has-provides-section
    cmd: "grep -q '^## Provides' terraform/lxc/stacks/nginx-test-stack/STACK_CONTRACT.md"
    expect: "exit 0"
    critical: true
  - id: has-dependencies-section
    cmd: "grep -q '^## Dependencies' terraform/lxc/stacks/nginx-test-stack/STACK_CONTRACT.md"
    expect: "exit 0"
    critical: true
```

### Literal file content for `nginx-test-stack-04-contract`

```markdown
# nginx-test-stack — Stack Contract

## Purpose

First, deliberately minimal pass validating the plan-change ->
implement-step process end-to-end (docs/agent-design/README.md), using
nginx as a throwaway example workload -- not a production web service.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | plain LAN bridge (vmbr0), no SDN zone |
| IP           | `192.168.1.54/24`        |
| Gateway      | `192.168.1.1`            |
| VMID         | 161                      |

## Inputs

None beyond platform defaults.

## Provides

| Service       | Port | Protocol | Notes |
|---------------|------|----------|-------|
| nginx-http    | 80   | HTTP     | Stock nginx default welcome page |

`stack.yaml` service identifier: `nginx-http`.

## Dependencies

None.

## Persistent State

None -- stock image content only, no volumes for this pass.

## What May Depend on This Stack

Nothing yet.

## What Must Not Be Edited Casually

Nothing yet -- this is intentionally the simplest possible pass.

## Playbook

`deploy-nginx-test-stack`
```

---

## Step: nginx-test-stack-05-terragrunt

```yaml
id: nginx-test-stack-05-terragrunt
title: Author terragrunt.hcl for nginx-test-stack
model_hint: local
depends_on: [nginx-test-stack-01-stack-request]

change: >
  Create terraform/lxc/stacks/nginx-test-stack/terragrunt.hcl containing
  exactly the literal HCL content in the block immediately below. This
  content is fixed boilerplate, identical across every stack in this
  repo -- nothing stack-specific to design or add.

scope:
  allowed_paths:
    - terraform/lxc/stacks/nginx-test-stack/terragrunt.hcl
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any deviation from the literal boilerplate below"

gates:
  - id: file-exists
    cmd: "test -f terraform/lxc/stacks/nginx-test-stack/terragrunt.hcl"
    expect: "exit 0"
    critical: true
  - id: matches-boilerplate
    cmd: "grep -q 'stack_yaml_path' terraform/lxc/stacks/nginx-test-stack/terragrunt.hcl && grep -q 'find_in_parent_folders' terraform/lxc/stacks/nginx-test-stack/terragrunt.hcl"
    expect: "exit 0"
    critical: true
```

### Literal file content for `nginx-test-stack-05-terragrunt`

```hcl
include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "${get_repo_root()}/terraform/lxc//"
}

inputs = {
  stack_name      = basename(get_terragrunt_dir())
  stack_yaml_path = "${get_terragrunt_dir()}/stack.yaml"
}
```

---

## Step: nginx-test-stack-06-playbook

```yaml
id: nginx-test-stack-06-playbook
title: Author the deploy-nginx-test-stack Ansible playbook
model_hint: local
depends_on: [nginx-test-stack-01-stack-request]

change: >
  Create terraform/lxc/ansible/playbooks/deploy-nginx-test-stack.yml
  containing exactly the literal YAML content in the block immediately
  below -- same tasks, same roles, same hosts: value, same check-mode
  guards, same quoting. hosts: must stay `all` (this repo's stacks target
  the LXC by inventory hostname, never `localhost`) -- do not change it
  even if `localhost`/`connection: local` seems simpler.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-nginx-test-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: syntax-check
    cmd: "HOME=$(mktemp -d) ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check -i localhost, -c local terraform/lxc/ansible/playbooks/deploy-nginx-test-stack.yml"
    expect: "exit 0"
    critical: true
```

### Literal file content for `nginx-test-stack-06-playbook`

```yaml
---
- name: Deploy nginx-test-stack stack
  hosts: all
  become: true
  gather_facts: true

  vars:
    stack_name: nginx-test-stack
    nginx_test_stack_compose_content: "{{ lookup('file', '../../stacks/' + stack_name + '/docker-compose.yml') }}"
    nginx_test_stack_dir: "/opt/stacks/{{ stack_name }}"

  roles:
    - lxc_base
    - docker_base

  tasks:
    - name: Create stack directory
      ansible.builtin.file:
        path: "{{ nginx_test_stack_dir }}"
        state: directory
        mode: "0755"

    - name: Write docker-compose.yml to stack directory
      ansible.builtin.copy:
        content: "{{ nginx_test_stack_compose_content }}"
        dest: "{{ nginx_test_stack_dir }}/docker-compose.yml"
        mode: "0644"

    - name: Validate docker compose configuration
      ansible.builtin.command:
        cmd: docker compose config
        chdir: "{{ nginx_test_stack_dir }}"
      register: compose_config_check
      changed_when: false
      when: not ansible_check_mode

    - name: Start nginx-test-stack services via docker compose
      ansible.builtin.command:
        cmd: docker compose up -d
        chdir: "{{ nginx_test_stack_dir }}"
      register: compose_up
      changed_when: "'Started' in compose_up.stdout or 'Created' in compose_up.stdout"
      when: not ansible_check_mode

    - name: Wait for nginx to accept TCP connections
      ansible.builtin.wait_for:
        host: "{{ ansible_host }}"
        port: 80
        timeout: 120
      when: not ansible_check_mode
      ignore_errors: "{{ ansible_check_mode }}"
```

---

## Step: nginx-test-stack-07-provision

```yaml
id: nginx-test-stack-07-provision
title: Apply Terraform and run the deploy playbook against pve-test-vm
model_hint: local
depends_on:
  - nginx-test-stack-02-stack-yaml
  - nginx-test-stack-03-compose
  - nginx-test-stack-04-contract
  - nginx-test-stack-05-terragrunt
  - nginx-test-stack-06-playbook

change: >
  Confirm the target is pve-test-vm, then run `terragrunt apply
  -auto-approve` scoped to only the nginx-test-stack directory (never
  `run --all`) to create the LXC and generate its inventory handoff, then
  run `scripts/provision.sh --stack nginx-test-stack` to execute the
  deploy-nginx-test-stack Ansible playbook against it. Stop and report if
  the target-node check does not print pve-test-vm -- do not proceed
  against any other node.

scope:
  allowed_paths:
    - terraform/lxc/stacks/nginx-test-stack/
  forbidden_actions:
    - "terragrunt run --all against terraform/lxc/stacks (this step is scoped to one stack directory only)"
    - "Targeting any node other than pve-test-vm"
    - "Any change to another stack's files or state"

gates:
  - id: target-is-pve-test-vm
    cmd: "./with-secrets bash -c 'echo $TF_VAR_proxmox_node'"
    expect: "pve-test-vm"
    critical: true
  - id: plan-additive-only
    cmd: "./with-secrets terragrunt plan --working-dir terraform/lxc/stacks/nginx-test-stack -no-color"
    expect: "exit 0, shows only new resources being added (no changes/deletions to any existing resource)"
    critical: true
  - id: apply-exit-0
    cmd: "./with-secrets terragrunt apply --working-dir terraform/lxc/stacks/nginx-test-stack -auto-approve -no-color"
    expect: "exit 0"
    critical: true
  - id: provision-exit-0
    cmd: "./with-secrets scripts/provision.sh --stack nginx-test-stack"
    expect: "exit 0"
    critical: true
```

---

## Step: nginx-test-stack-08-verify

```yaml
id: nginx-test-stack-08-verify
title: Confirm nginx-test-stack is actually serving traffic
model_hint: local
depends_on: [nginx-test-stack-07-provision]

change: >
  Curl the container's IP on port 80 and confirm the response is
  nginx's default welcome page. This is the pass/fail check for the
  whole plan -- report pass/fail plainly, do not infer success from the
  provision step's exit code alone.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Any file edit -- this step only verifies, it does not change anything"

gates:
  - id: http-welcome-page
    cmd: "curl -sf http://192.168.1.54:80/ | grep -qi 'Welcome to nginx'"
    expect: "exit 0"
    critical: true
```
