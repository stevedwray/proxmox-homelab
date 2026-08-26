# LXC Provision Test Plan (throwaway)

Written with `.github/prompts/plan-change.prompt.md` per
`docs/agent-design/step-packet-schema.md`. The real target task class for
this methodology: deploy a new LXC container, configure a service on it
via Ansible. `smoketest-stack` is a single disposable nginx container
with no persistent data -- safe to destroy at any point.

## Preflight facts (checked 2026-08-26, before writing this plan)

- pve-test-vm headroom: 19Gi total RAM, 6.4Gi available, 40G mostly-free
  storage volume. Plenty for one more single-container LXC (512MB
  allocated).
- VMID `99010` and IP `192.168.1.99` were checked free at plan-write
  time (`lxcprov-00` re-checks this for real, at execution time, since
  "free when the plan was written" isn't the same as "free when the
  step actually runs").

```yaml
id: lxcprov-00-preflight-check
title: Confirm VMID 99010 and IP 192.168.1.99 are not already in use
depends_on: []

change: >
  Run exactly these two commands and report their exact output. This
  step makes no file changes -- it only checks current state before any
  real infrastructure step runs later in this plan:

    grep -rl "vmid: 99010" terraform/lxc/stacks/*/stack.yaml
    ping -c 2 -W 1 192.168.1.99

scope:
  allowed_paths: []
  forbidden_actions:
    - "Any file edit in this step"
    - "Any terragrunt or provision.sh command"

gates:
  - id: vmid-free
    cmd: "! grep -rl \"vmid: 99010\" terraform/lxc/stacks/*/stack.yaml"
    expect: "exit 0 (no existing stack claims this vmid)"
    critical: true
  - id: ip-free
    cmd: "! ping -c 2 -W 1 192.168.1.99 >/dev/null 2>&1"
    expect: "exit 0 (no reply -- address appears free)"
    critical: true
```

```yaml
id: lxcprov-01-stack-request
title: Author stack-request.yaml for the disposable smoketest-stack
depends_on: [lxcprov-00-preflight-check]

change: >
  Create terraform/lxc/stacks/smoketest-stack/stack-request.yaml with
  exactly this content:

    stack_yaml:
      hostname: smoketest-stack
      ip_address: "192.168.1.99/24"
      gateway: "192.168.1.1"
      dns_server: "192.168.1.1"
      vmid: 99010
      cores: 1
      memory: 512
      swap: 256
      rootfs_size: 4
      storage_profile: platform-default
      docker_storage_size: "2G"
      template_name: "debian-13.1-2-docker-template.tar.gz"
      tags:
        - docker
        - smoketest
      depends_on: []
      provides:
        - service: http
          port: 80
          protocol: tcp
      ansible_playbook: deploy-smoketest-stack
      deployment_tier: apps
      portainer_agent: false

    compose_requirements: |
      Single service, nginx:1.27-alpine, pinned tag (not latest). Port
      80:80/tcp only. No volumes, no bind mounts -- fully ephemeral,
      serves the image's own default welcome page. container_name:
      smoketest-stack-web. restart: unless-stopped. No environment
      variables needed.

    compose_forbidden: |
      a custom top-level networks: block, any volume or bind mount, an
      unpinned "latest" image tag, any service beyond the single nginx
      container, any environment variables.

    contract_facts: |
      - Purpose: disposable smoke-test stack validating the
        LXC-provision-then-Ansible-configure pipeline for the
        agent-design methodology -- not a real service, safe to destroy
        anytime
      - Zone: plain LAN bridge (vmbr0), no SDN zone
      - IP: 192.168.1.99/24, confirmed free in lxcprov-00
      - Gateway: 192.168.1.1
      - VMID: 99010, confirmed free in lxcprov-00
      - Inputs: none beyond platform defaults
      - Provides: http, port 80, protocol tcp
      - Dependencies: none, nothing depends on this stack
      - No persistent state of any kind
      - Playbook: deploy-smoketest-stack, using docker_base plus a
        compose file
      - Implementation files: terraform/lxc/stacks/smoketest-stack/
        stack.yaml, terragrunt.hcl (both new), terraform/lxc/ansible/
        playbooks/deploy-smoketest-stack.yml (new)

    playbook_content: |
      ---
      - name: Deploy smoketest stack
        hosts: all
        become: true
        gather_facts: true

        vars:
          stack_name: smoketest-stack
          smoketest_compose_content: "{{ lookup('file', '../../stacks/' + stack_name + '/docker-compose.yml') }}"
          smoketest_stack_dir: "/opt/stacks/{{ stack_name }}"

        roles:
          - lxc_base
          - docker_base

        tasks:
          - name: Create stack directory
            ansible.builtin.file:
              path: "{{ smoketest_stack_dir }}"
              state: directory
              mode: "0755"

          - name: Write docker-compose.yml to stack directory
            ansible.builtin.copy:
              content: "{{ smoketest_compose_content }}"
              dest: "{{ smoketest_stack_dir }}/docker-compose.yml"
              mode: "0644"

          - name: Validate docker compose configuration
            ansible.builtin.command:
              cmd: docker compose config
              chdir: "{{ smoketest_stack_dir }}"
            register: compose_config_check
            changed_when: false
            when: not ansible_check_mode

          - name: Start smoketest stack via docker compose
            ansible.builtin.command:
              cmd: docker compose up -d
              chdir: "{{ smoketest_stack_dir }}"
            register: compose_up
            changed_when: "'Started' in compose_up.stdout or 'Created' in compose_up.stdout"
            when: not ansible_check_mode

          - name: Wait for smoketest web server to accept TCP connections
            ansible.builtin.wait_for:
              host: "{{ ansible_host }}"
              port: 80
              timeout: 120
            when: not ansible_check_mode
            ignore_errors: "{{ ansible_check_mode }}"

scope:
  allowed_paths:
    - terraform/lxc/stacks/smoketest-stack/stack-request.yaml
  forbidden_actions:
    - "Running scaffold-stack.sh -- that's a separate operator step"
    - "Any terragrunt or provision.sh command"

gates:
  - id: stack-request-exists
    cmd: "test -f terraform/lxc/stacks/smoketest-stack/stack-request.yaml"
    expect: "exit 0"
    critical: true
  - id: stack-request-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/smoketest-stack/stack-request.yaml'))\""
    expect: "exit 0"
    critical: true
```

## Operator step: lxcprov-02-scaffold

Not a step block -- running `scaffold-stack.sh` is always an operator
action in this methodology, never handed to the local model. Depends on
`lxcprov-01-stack-request` (its input file).

Run `terraform/lxc/scaffold-stack.sh smoketest-stack` directly. It stops
on the first validator failure; if it fails partway, don't hand-edit any
of the five generated files -- check which validator failed and re-run.

```yaml
id: lxcprov-03-verify-generated-files
title: Verify the five scaffolded files match stack-request.yaml exactly
depends_on: [lxcprov-02-scaffold]

change: >
  Compare the five files scaffold-stack.sh generated in
  terraform/lxc/stacks/smoketest-stack/ (stack.yaml, docker-compose.yml,
  STACK_CONTRACT.md, terragrunt.hcl, and
  terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml) against
  the exact literal requirements already given in
  lxcprov-01-stack-request's stack-request.yaml (image
  nginx:1.27-alpine, port 80:80 only, no volumes, no extra services, no
  environment variables, vmid 99010, ip 192.168.1.99/24). If anything
  deviates from those literal requirements, fix only that specific
  deviation to match exactly. If everything already matches, make no
  changes at all -- do not "improve" anything that already matches the
  spec.

scope:
  allowed_paths:
    - terraform/lxc/stacks/smoketest-stack/
  forbidden_actions:
    - "Any terragrunt or provision.sh command"
    - "Editing stack-request.yaml itself -- that already landed in lxcprov-01"

gates:
  - id: compose-parses
    cmd: "docker compose -f terraform/lxc/stacks/smoketest-stack/docker-compose.yml config"
    expect: "exit 0"
    critical: true
  - id: correct-image-pinned
    cmd: "grep -q 'nginx:1.27-alpine' terraform/lxc/stacks/smoketest-stack/docker-compose.yml"
    expect: "exit 0"
    critical: true
  - id: no-latest-tag
    cmd: "! grep -qE 'nginx:latest|image:.*:latest' terraform/lxc/stacks/smoketest-stack/docker-compose.yml"
    expect: "exit 0 (no unpinned tag found)"
    critical: true
  - id: no-volumes
    cmd: "! grep -qE '^\\s*volumes:' terraform/lxc/stacks/smoketest-stack/docker-compose.yml"
    expect: "exit 0 (no volumes block present)"
    critical: true
```

## `lxcprov-04-provision` -- STOP: requires explicit operator go-ahead

This is the first step in this whole test arc that actually creates
real infrastructure -- a new LXC on pve-test-vm. Do not send this step
to `implement-step` just because `lxcprov-03`'s gates passed. Wait for
the operator to say specifically to proceed with this one.

```yaml
id: lxcprov-04-provision
title: Provision smoketest-stack (creates a real LXC + deploys the service)
depends_on: [lxcprov-03-verify-generated-files]

change: >
  Run exactly this command:

    ./with-secrets scripts/provision.sh --stack smoketest-stack

  This targets pve-test-vm by default (with-secrets' documented
  default). Before running it, confirm
  `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` prints
  `pve-test-vm` -- if it prints anything else, stop and report that
  instead of running provision.sh.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Running this against any node other than pve-test-vm"
    - "Any --stack value other than smoketest-stack"

gates:
  - id: target-node-is-test-vm
    cmd: "./with-secrets bash -c 'echo $TF_VAR_proxmox_node'"
    expect: "pve-test-vm"
    critical: true
  - id: provision-exits-clean
    cmd: "./with-secrets scripts/provision.sh --stack smoketest-stack"
    expect: "exit 0"
    critical: true
```

```yaml
id: lxcprov-05-verify-service
title: Confirm the deployed nginx container actually responds
depends_on: [lxcprov-04-provision]

change: >
  Run exactly this command and report its exact output:

    curl -s http://192.168.1.99/

scope:
  allowed_paths: []
  forbidden_actions:
    - "Any terragrunt or provision.sh command"
    - "Any change to any file"

gates:
  - id: nginx-responds
    cmd: "curl -s http://192.168.1.99/ | grep -q 'Welcome to nginx'"
    expect: "exit 0"
    critical: true
```

## Operator step: lxcprov-06-teardown

Not a step block -- destroying infrastructure is never handed to the
local model. Run regardless of how far this test got, so
`smoketest-stack` doesn't linger on pve-test-vm.

SSH to pve-test-vm and run `pct stop 99010 && pct destroy 99010`, then
remove `terraform/lxc/stacks/smoketest-stack/` and
`terraform/lxc/environments/pve-test-vm/smoketest-stack/` and
`terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml` from the
repo.
