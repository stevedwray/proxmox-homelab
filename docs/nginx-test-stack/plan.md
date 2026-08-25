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

## Research this plan is based on

- `docs/agent-design/step-packet-schema.md`'s "Reuse `scaffold-stack.sh`
  for new stacks specifically" section: a brand-new stack should get one
  `frontier`-shaped research step (folded into this plan already, see
  below) that authors `stack-request.yaml`, then one step that runs
  `terraform/lxc/scaffold-stack.sh <stack-name>` -- not hand-written
  `stack.yaml`/`docker-compose.yml`/`STACK_CONTRACT.md`/`terragrunt.hcl`
  edits.
- `terraform/lxc/stacks/stack-request.example.yaml` and the
  `minecraft-stack` exemplar it documents
  (`docs/stack-lifecycle-refactor/stage-10-minecraft-exemplar.md`) -- the
  concrete, already-validated shape for `stack_yaml`,
  `compose_requirements`/`compose_forbidden`, `contract_facts`, and
  `playbook_content` fields reused directly below.
- Every `terraform/lxc/stacks/*/stack.yaml` was checked for VMID and
  `192.168.1.0/24` IP collisions: VMID `161` and `192.168.1.54/24` are
  both free. `docker-socket-proxy-test` (VMID `160`, `.53`) is the
  closest existing disposable test-tier stack and is the template for
  `deployment_tier`, tags, sizing, and network placement.
- Bare `docker.io` is never used directly for image pulls in this repo --
  every compose file that pulls a public image goes through Harbor's
  proxy-cache path
  (`harbor.lab.gibbsgreatly.xyz/dockerhub/<namespace>/<image>:<tag>`),
  confirmed against `terraform/lxc/stacks/harness-target/docker-compose.yml`
  (`harbor.lab.gibbsgreatly.xyz/dockerhub/vulhub/struts2:2.3.30`,
  `.../dockerhub/library/redis:7.4`).
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
- `terraform/lxc/validate-stack-metadata.py`'s `ACTIVE_STACKS` tuple is a
  small fixed list of platform stacks (harbor, apt-cacher, netbox,
  portainer, authentik, step-ca, ci-runner-01, mcp-utility) -- it does not
  scan every stack directory, so it is not a meaningful gate for a new
  disposable test-tier stack and is intentionally not used below.

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

---

## Step: nginx-test-stack-01-stack-request

```yaml
id: nginx-test-stack-01-stack-request
title: Author stack-request.yaml for nginx-test-stack
model_hint: local
depends_on: []

change: >
  Create terraform/lxc/stacks/nginx-test-stack/stack-request.yaml
  (creating the terraform/lxc/stacks/nginx-test-stack/ directory first if
  it does not exist) containing exactly the literal YAML content in the
  "Literal file content" block immediately below this step -- transcribe
  it verbatim, do not paraphrase or reorder fields, do not model it on
  any other stack's stack-request.yaml.

scope:
  allowed_paths:
    - terraform/lxc/stacks/nginx-test-stack/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any scaffold-stack.sh, terragrunt, or provision.sh run -- this step only writes the request file"

gates:
  - id: file-exists
    cmd: "test -f terraform/lxc/stacks/nginx-test-stack/stack-request.yaml"
    expect: "exit 0"
    critical: true
  - id: yaml-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/nginx-test-stack/stack-request.yaml'))\""
    expect: "exit 0"
    critical: true
```

### Literal file content for `nginx-test-stack-01-stack-request`

```yaml
# Scaffolding input for terraform/lxc/scaffold-stack.sh nginx-test-stack.
# Not part of the stack's final tracked file set -- delete or keep as a
# record of intent once the stack is scaffolded and validated.
#
# Pass 1 only: deploy + provision, no integration. See
# docs/nginx-test-stack/README.md for the two-pass framing.

stack_yaml:
  hostname: nginx-test-stack
  ip_address: "192.168.1.54/24"
  gateway: "192.168.1.1"
  dns_server: "192.168.1.1"
  vmid: 161
  cores: 1
  memory: 512
  swap: 512
  rootfs_size: 8
  storage_profile: platform-default
  docker_storage_size: "4G"
  template_name: "debian-13.1-2-docker-template.tar.gz"
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

compose_requirements: |
  Single service named nginx. Image pinned to exactly
  harbor.lab.gibbsgreatly.xyz/dockerhub/library/nginx:1.27-alpine --
  pulled through Harbor's Docker Hub proxy-cache, never bare
  docker.io/nginx or an unpinned "latest" tag. container_name:
  nginx-test-stack-nginx. Port mapping "80:80/tcp" only. restart:
  unless-stopped. No volumes or bind mounts -- serve the image's own
  built-in default content unmodified for this pass.

compose_forbidden: |
  a custom top-level networks: block, any volumes:/bind-mounts
  overriding /usr/share/nginx/html or /etc/nginx/*, a second service, any
  TLS/certificate configuration, and any environment variables (the stock
  nginx image needs none). This is a deliberately minimal first pass --
  no Traefik/monitoring/DNS wiring belongs in this compose file.

contract_facts: |
  - Purpose: first, deliberately minimal pass validating the
    plan-change -> scaffold-stack.sh -> provision.sh pipeline end-to-end
    (docs/agent-design/README.md), using nginx as a throwaway example
    workload -- not a production web service.
  - Zone: plain LAN bridge (vmbr0), no SDN zone for this pass -- matches
    docker-socket-proxy-test and test-storage.
  - IP: 192.168.1.54/24
  - Gateway: 192.168.1.1
  - VMID: 161
  - Inputs: none beyond platform defaults
  - Provides: nginx-http, port 80, protocol tcp
  - Dependencies: none
  - Persistent state: none -- stock image content only, no volumes for
    this pass
  - Nothing depends on this stack
  - What must not be edited casually: nothing yet -- this is
    intentionally the simplest possible pass
  - Playbook: deploy-nginx-test-stack, using lxc_base + docker_base roles
    plus a compose file
  - Implementation files:
    terraform/lxc/stacks/nginx-test-stack/stack.yaml (new),
    terraform/lxc/stacks/nginx-test-stack/terragrunt.hcl (new),
    terraform/lxc/stacks/nginx-test-stack/inventory.yml (generated by
    terragrunt apply, do not hand-edit),
    terraform/lxc/ansible/playbooks/deploy-nginx-test-stack.yml (new)
  - Planned next, NOT part of this plan: once validated, this container
    is destroyed and a second, separate plan-change pass adds Traefik,
    technitium DNS (test zone), and monitoring integration on a rebuilt
    nginx-test-stack.

playbook_content: |
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

## Step: nginx-test-stack-02-scaffold

```yaml
id: nginx-test-stack-02-scaffold
title: Run scaffold-stack.sh to generate the five stack files
model_hint: local
depends_on: [nginx-test-stack-01-stack-request]

change: >
  From the repo root, run
  `terraform/lxc/scaffold-stack.sh nginx-test-stack`. It reads the
  stack-request.yaml written in the previous step and authors
  stack.yaml, docker-compose.yml, STACK_CONTRACT.md, terragrunt.hcl, and
  terraform/lxc/ansible/playbooks/deploy-nginx-test-stack.yml, stopping
  on the first validator failure. Do not hand-edit any of these five
  files yourself in this step -- if the scaffolder fails, report which
  validator stopped it rather than working around it.

scope:
  allowed_paths:
    - terraform/lxc/stacks/nginx-test-stack/
    - terraform/lxc/ansible/playbooks/deploy-nginx-test-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any terragrunt or provision.sh run -- scaffolding only in this step"
    - "Hand-editing any of the five generated files"

gates:
  - id: scaffold-exit-0
    cmd: "terraform/lxc/scaffold-stack.sh nginx-test-stack"
    expect: "exit 0"
    critical: true
  - id: five-files-exist
    cmd: "test -f terraform/lxc/stacks/nginx-test-stack/stack.yaml && test -f terraform/lxc/stacks/nginx-test-stack/docker-compose.yml && test -f terraform/lxc/stacks/nginx-test-stack/STACK_CONTRACT.md && test -f terraform/lxc/stacks/nginx-test-stack/terragrunt.hcl && test -f terraform/lxc/ansible/playbooks/deploy-nginx-test-stack.yml"
    expect: "exit 0"
    critical: true
  - id: compose-config-valid
    cmd: "cd terraform/lxc/stacks/nginx-test-stack && docker compose config"
    expect: "exit 0"
    critical: true
```

---

## Step: nginx-test-stack-03-provision

```yaml
id: nginx-test-stack-03-provision
title: Apply Terraform and run the deploy playbook against pve-test-vm
model_hint: local
depends_on: [nginx-test-stack-02-scaffold]

change: >
  Confirm the target is pve-test-vm, then run `terragrunt apply
  -auto-approve` scoped to only the nginx-test-stack directory (never
  `run --all`) to create the LXC and generate its inventory handoff, then
  run `scripts/provision.sh --stack nginx-test-stack` to execute the
  generated deploy-nginx-test-stack Ansible playbook against it. Stop and
  report if the target-node check does not print pve-test-vm -- do not
  proceed against any other node.

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

## Step: nginx-test-stack-04-verify

```yaml
id: nginx-test-stack-04-verify
title: Confirm nginx-test-stack is actually serving traffic
model_hint: local
depends_on: [nginx-test-stack-03-provision]

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
