# Graylog Integration Test Plan (throwaway)

Written with `.github/prompts/plan-change.prompt.md` per
`docs/agent-design/step-packet-schema.md`. Tests the next capability
class beyond bare LXC provisioning: adding a real platform integration
(Graylog log forwarding) to an already-deployed stack. `smoketest-stack`
is the same disposable single-container nginx stack used in
`docs/agent-design/lxc-provision-test/` -- safe to destroy at any point,
no persistent data, nothing depends on it.

## Preflight facts (checked 2026-08-27, before writing this plan)

- VMID `99010` and IP `192.168.1.99` were fully torn down and removed
  after the first worked example (`docs/agent-design/lxc-provision-test/`)
  -- confirmed via `pct list` on pve-test-vm and `git log` showing the
  tracked files removed. `gli-00` re-checks this for real at execution
  time.
- `rsyslog_forward`'s defaults (`terraform/lxc/ansible/roles/rsyslog_forward/defaults/main.yml`)
  already point `rsyslog_forward_target_host` at `lookup('env', 'LAB_IP_GRAYLOG')`
  with no other vars required for a normal (non-relay) stack --
  confirmed `LAB_IP_GRAYLOG=192.168.20.114` resolves via
  `PVE_ENV=pve-test-vm ./with-secrets`. No `vars:` override needed when
  including this role.
- The Graylog REST search API and query shape were confirmed live
  against pve-test-vm's real Graylog instance before writing this plan:
  `GET /api/search/universal/relative?query=<lucene>&range=<seconds>&limit=<n>`,
  Basic auth (`admin` / `GRAYLOG_ROOT_PASSWORD`), `Accept: application/json`
  and `X-Requested-By: <anything>` headers required. Tested against both
  a real matching query (`query=*`, real messages returned) and a
  deliberately non-matching one (the exact marker text used in
  `gli-11` below, confirmed 0 matches before this stack exists).
- The playbook edit in `gli-08` (appending `rsyslog_forward` to an
  existing `roles:` list) was syntax-checked for real against a copy of
  the file before writing this plan -- `ansible-playbook --syntax-check`
  passes clean (exit 0) from `terraform/lxc/ansible/` as the working
  directory (its `roles_path = roles` in `ansible.cfg` is relative to
  that directory, not the repo root or the playbook's own directory --
  confirmed by testing, not assumed).
- The ad-hoc Graylog-marker step (`gli-10`) has not been tested against
  a live host yet, since the host doesn't exist until `gli-05` runs for
  real. If the exact `ansible -i <inventory> all -m command -a "..."`
  invocation needs adjusting once a real inventory.yml exists, that's a
  gap to fix then, the same way `lxc-provision-test` found and fixed its
  own two real gaps mid-run.

```yaml
id: gli-00-preflight-check
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
id: gli-01-stack-files
title: Author the four smoketest-stack source files (stack.yaml, docker-compose.yml, STACK_CONTRACT.md, terragrunt.hcl)
depends_on: [gli-00-preflight-check]

change: >
  Create these four files in terraform/lxc/stacks/smoketest-stack/ with
  exactly this content -- this is proven-good content from the first
  worked example, transcribe it literally rather than modeling on some
  other stack's shape:

  terraform/lxc/stacks/smoketest-stack/stack.yaml:

    hostname: smoketest-stack
    ip_address: 192.168.1.99/24
    gateway: 192.168.1.1
    dns_server: 192.168.1.1
    vmid: 99010
    cores: 1
    memory: 512
    swap: 256
    rootfs_size: 4
    storage_profile: platform-default
    docker_storage_size: 2G
    template_name: debian-13.1-2-docker-template.tar.gz
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

  terraform/lxc/stacks/smoketest-stack/docker-compose.yml:

    version: '3.8'

    services:
      web:
        image: nginx:1.27-alpine
        container_name: smoketest-stack-web
        ports:
          - "80:80/tcp"
        restart: unless-stopped

  terraform/lxc/stacks/smoketest-stack/STACK_CONTRACT.md:

    # smoketest-stack — Stack Contract

    ## Purpose

    Disposable smoke-test stack validating the LXC-provision-then-Ansible-configure
    pipeline for the agent-design methodology, now extended to also
    validate adding a real platform integration (Graylog log forwarding)
    to an already-deployed stack. Not a real service -- safe to destroy
    at any point. A single nginx container serving its own default
    welcome page, nothing else.

    ## Network

    | Field        | Value                    |
    |--------------|--------------------------|
    | Zone         | plain LAN bridge (vmbr0) |
    | IP           | 192.168.1.99/24          |
    | Gateway      | 192.168.1.1              |
    | VMID         | 99010                    |

    ## Inputs

    *No inputs beyond platform defaults.*

    ## Provides

    | Service | Port | Protocol | Notes |
    |---------|------|----------|-------|
    | http    | 80   | tcp      | nginx default welcome page, no custom content |

    ## Dependencies

    None.

    ## Persistent State

    *No persistent state.*

    ## What May Depend On This Stack

    Nothing depends on this stack.

    ## What Must Not Be Edited Casually

    Nothing -- this stack is fully disposable and carries no shared state or
    downstream consumers.

  terraform/lxc/stacks/smoketest-stack/terragrunt.hcl:

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

scope:
  allowed_paths:
    - terraform/lxc/stacks/smoketest-stack/stack.yaml
    - terraform/lxc/stacks/smoketest-stack/docker-compose.yml
    - terraform/lxc/stacks/smoketest-stack/STACK_CONTRACT.md
    - terraform/lxc/stacks/smoketest-stack/terragrunt.hcl
  forbidden_actions:
    - "Any terragrunt or provision.sh command"
    - "Creating stack-request.yaml or running scaffold-stack.sh -- not part of this plan"
    - "Creating the ansible playbook -- that's a separate step (gli-02)"

gates:
  - id: stack-yaml-exists
    cmd: "test -f terraform/lxc/stacks/smoketest-stack/stack.yaml"
    expect: "exit 0"
    critical: true
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
  - id: contract-exists
    cmd: "test -f terraform/lxc/stacks/smoketest-stack/STACK_CONTRACT.md"
    expect: "exit 0"
    critical: true
  - id: terragrunt-hcl-exists
    cmd: "test -f terraform/lxc/stacks/smoketest-stack/terragrunt.hcl"
    expect: "exit 0"
    critical: true
```

```yaml
id: gli-02-playbook
title: Author the deploy-smoketest-stack Ansible playbook
depends_on: [gli-01-stack-files]

change: >
  Create terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml with
  exactly this content -- proven-good content from the first worked
  example, transcribe it literally. Do not add rsyslog_forward to the
  roles list in this step -- that's a separate later step (gli-08),
  after the stack is already live:

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
    - terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml
  forbidden_actions:
    - "Any terragrunt or provision.sh command"
    - "Adding rsyslog_forward or any role beyond lxc_base/docker_base in this step"

gates:
  - id: playbook-exists
    cmd: "test -f terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml"
    expect: "exit 0"
    critical: true
  - id: playbook-syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check playbooks/deploy-smoketest-stack.yml"
    expect: "exit 0"
    critical: true
  - id: only-two-roles
    cmd: "! grep -A3 '^  roles:' terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml | grep -q rsyslog_forward"
    expect: "exit 0 (rsyslog_forward not present yet -- added later in gli-08)"
    critical: true
```

```yaml
id: gli-03-verify-generated-files
title: Verify the four stack files and the playbook match spec exactly
depends_on: [gli-02-playbook]

change: >
  Compare all five files authored in gli-01 and gli-02 against the
  literal content given in those two steps (image nginx:1.27-alpine,
  port 80:80 only, no volumes, no extra services, no environment
  variables, vmid 99010, ip 192.168.1.99/24, roles lxc_base+docker_base
  only). If anything deviates from those literal requirements, fix only
  that specific deviation to match exactly. If everything already
  matches, make no changes at all -- do not "improve" anything that
  already matches the spec.

scope:
  allowed_paths:
    - terraform/lxc/stacks/smoketest-stack/
    - terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml
  forbidden_actions:
    - "Any terragrunt or provision.sh command"

gates:
  - id: compose-parses
    cmd: "docker compose -f terraform/lxc/stacks/smoketest-stack/docker-compose.yml config"
    expect: "exit 0"
    critical: true
  - id: playbook-syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check playbooks/deploy-smoketest-stack.yml"
    expect: "exit 0"
    critical: true
```

```yaml
id: gli-04-create-environment-config
title: Create the environment-level Terragrunt config for smoketest-stack on pve-test-vm
depends_on: [gli-03-verify-generated-files]

change: >
  Create terraform/lxc/environments/pve-test-vm/smoketest-stack/terragrunt.hcl
  with exactly this content (fixed boilerplate, byte-identical in shape
  to every other stack's own environment-level terragrunt.hcl in this
  repo -- copied verbatim from the real
  terraform/lxc/environments/pve-test-vm/harness-target/terragrunt.hcl,
  not written from memory of what this shape "should" look like):

    include "root" {
      path = find_in_parent_folders()
    }

    terraform {
      source = "${get_repo_root()}/terraform/lxc//"
    }

    inputs = {
      stack_name      = basename(get_terragrunt_dir())
      stack_yaml_path = "${get_repo_root()}/terraform/lxc/stacks/${basename(get_terragrunt_dir())}/stack.yaml"
      generated_dir   = get_terragrunt_dir()
    }

scope:
  allowed_paths:
    - terraform/lxc/environments/pve-test-vm/smoketest-stack/terragrunt.hcl
  forbidden_actions:
    - "Any terragrunt or provision.sh command in this step -- authoring the file only"
    - "Copying stack.yaml or any other file into this directory -- only terragrunt.hcl"

gates:
  - id: env-terragrunt-exists
    cmd: "test -f terraform/lxc/environments/pve-test-vm/smoketest-stack/terragrunt.hcl"
    expect: "exit 0"
    critical: true
  - id: matches-existing-pattern
    cmd: "diff terraform/lxc/environments/pve-test-vm/smoketest-stack/terragrunt.hcl terraform/lxc/environments/pve-test-vm/harness-target/terragrunt.hcl"
    expect: "exit 0 (identical content -- this file is fixed boilerplate, not stack-specific beyond its own directory name)"
    critical: true
```

## `gli-05-terragrunt-apply` -- STOP: requires explicit operator go-ahead

This is the step that actually creates real infrastructure -- a new LXC
on pve-test-vm. Do not send this step to `implement-step` just because
`gli-04`'s gates passed. Wait for the operator to say specifically to
proceed with this one.

```yaml
id: gli-05-terragrunt-apply
title: Apply Terraform for smoketest-stack (creates the real LXC container)
depends_on: [gli-04-create-environment-config]

change: >
  First confirm `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'`
  prints `pve-test-vm` -- if it prints anything else, stop and report
  that instead of continuing. Then run exactly this command:

    ./with-secrets terragrunt --working-dir terraform/lxc/environments/pve-test-vm/smoketest-stack apply -auto-approve

scope:
  allowed_paths: []
  forbidden_actions:
    - "Running this against any node other than pve-test-vm"
    - "Any --working-dir other than terraform/lxc/environments/pve-test-vm/smoketest-stack"

gates:
  - id: target-node-is-test-vm
    cmd: "./with-secrets bash -c 'echo $TF_VAR_proxmox_node'"
    expect: "pve-test-vm"
    critical: true
  - id: apply-exits-clean
    cmd: "./with-secrets terragrunt --working-dir terraform/lxc/environments/pve-test-vm/smoketest-stack apply -auto-approve"
    expect: "exit 0"
    critical: true
  - id: inventory-generated
    cmd: "test -f terraform/lxc/environments/pve-test-vm/smoketest-stack/inventory.yml"
    expect: "exit 0"
    critical: true
```

```yaml
id: gli-06-provision
title: Provision smoketest-stack (deploys the nginx service via Ansible)
depends_on: [gli-05-terragrunt-apply]

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
  - id: provision-actually-ran-not-skipped
    cmd: "./with-secrets scripts/provision.sh --stack smoketest-stack 2>&1 | tee /tmp/gli-provision-out.log; ! grep -qE 'SKIP smoketest-stack:' /tmp/gli-provision-out.log"
    expect: "exit 0 (provision.sh exits 0 even when it silently skips a stack -- e.g. because inventory.yml doesn't exist yet -- so checking bare exit code alone is not enough; this gate fails explicitly if the output shows the stack was skipped rather than actually run)"
    critical: true
```

```yaml
id: gli-07-verify-service
title: Confirm the deployed nginx container actually responds
depends_on: [gli-06-provision]

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

## The new capability under test: adding Graylog log forwarding to an already-live stack

Everything above this point is the already-proven deploy/provision
pipeline from `lxc-provision-test`, reused here only to get a live
target to attach the new integration to. The steps below are the actual
subject of this test.

```yaml
id: gli-08-add-rsyslog-forward-role
title: Add the rsyslog_forward role to smoketest-stack's playbook and document it in the contract
depends_on: [gli-07-verify-service]

change: >
  Edit terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml: in
  the existing `roles:` list, add `rsyslog_forward` as a third entry
  after `docker_base`, so the list reads exactly:

    roles:
      - lxc_base
      - docker_base
      - rsyslog_forward

  Do not add any `vars:` alongside this role -- its defaults
  (`terraform/lxc/ansible/roles/rsyslog_forward/defaults/main.yml`)
  already read `LAB_IP_GRAYLOG` from the environment, which is exactly
  what a normal (non-relay) stack needs. Do not touch any other task or
  role in this file.

  Also edit terraform/lxc/stacks/smoketest-stack/STACK_CONTRACT.md: in
  the `## Dependencies` section, replace the current `None.` with
  exactly:

    - `graylog-stack` (this stack's own logs are forwarded to it via
      the `rsyslog_forward` Ansible role -- see
      `terraform/lxc/ansible/roles/rsyslog_forward/`).

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml
    - terraform/lxc/stacks/smoketest-stack/STACK_CONTRACT.md
  forbidden_actions:
    - "Any terragrunt or provision.sh command in this step -- editing files only"
    - "Adding any vars: override for rsyslog_forward -- defaults are correct here"
    - "Editing docker-compose.yml, stack.yaml, or terragrunt.hcl in this step"

gates:
  - id: role-added
    cmd: "grep -A4 '^  roles:' terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml | grep -q rsyslog_forward"
    expect: "exit 0"
    critical: true
  - id: no-vars-override-added
    cmd: "! grep -A2 'rsyslog_forward' terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml | grep -qE 'rsyslog_forward_target_host|rsyslog_inbound_enabled'"
    expect: "exit 0 (no vars override present -- defaults are used)"
    critical: true
  - id: playbook-syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check playbooks/deploy-smoketest-stack.yml"
    expect: "exit 0"
    critical: true
  - id: contract-documents-graylog-dependency
    cmd: "grep -q 'graylog-stack' terraform/lxc/stacks/smoketest-stack/STACK_CONTRACT.md"
    expect: "exit 0"
    critical: true
```

## `gli-09-reprovision` -- STOP: requires explicit operator go-ahead

This step reconfigures the already-running container (installs
`rsyslog`, rewrites its syslog config, restarts the service). Do not
send this step to `implement-step` just because `gli-08`'s gates
passed. Wait for the operator to say specifically to proceed with this
one.

```yaml
id: gli-09-reprovision
title: Reprovision smoketest-stack to apply the new rsyslog_forward role
depends_on: [gli-08-add-rsyslog-forward-role]

change: >
  Run exactly this command:

    ./with-secrets scripts/provision.sh --stack smoketest-stack

  Before running it, confirm
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
  - id: reprovision-exits-clean-not-skipped
    cmd: "./with-secrets scripts/provision.sh --stack smoketest-stack 2>&1 | tee /tmp/gli-reprovision-out.log; ! grep -qE 'SKIP smoketest-stack:' /tmp/gli-reprovision-out.log"
    expect: "exit 0 (same skip-detection gate as gli-06 -- provision.sh exits 0 even on a silent skip)"
    critical: true
  - id: no-failed-tasks
    cmd: "! grep -qE 'failed=[1-9]' /tmp/gli-reprovision-out.log"
    expect: "exit 0 (PLAY RECAP shows failed=0)"
    critical: true
```

```yaml
id: gli-10-emit-verification-log
title: Emit a uniquely identifiable log line from the smoketest-stack container
depends_on: [gli-09-reprovision]

change: >
  Run exactly this command and report its exact output:

    ansible -i terraform/lxc/environments/pve-test-vm/smoketest-stack/inventory.yml all -m command -a "logger -t gli-verify GLI7X9K2QM"

  This uses Ansible's ad-hoc command mode to run `logger` (a standard
  syslog CLI utility already present on the base image) on the
  smoketest-stack container itself, tagged `gli-verify`, with the fixed
  marker text `GLI7X9K2QM`. This marker is deliberately fixed and
  distinctive -- not something to invent or vary -- so gli-11's search
  query below is unambiguous.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Any file edit"
    - "Any terragrunt or provision.sh command"
    - "Any marker text other than GLI7X9K2QM"

gates:
  - id: logger-command-succeeds
    cmd: "ansible -i terraform/lxc/environments/pve-test-vm/smoketest-stack/inventory.yml all -m command -a \"logger -t gli-verify GLI7X9K2QM\""
    expect: "exit 0"
    critical: true
```

```yaml
id: gli-11-verify-in-graylog
title: Confirm the marker log line actually arrived in Graylog
depends_on: [gli-10-emit-verification-log]

change: >
  Run exactly this command and report its exact output:

    PVE_ENV=pve-test-vm ./with-secrets bash -c 'curl -s --max-time 10 -u "admin:${GRAYLOG_ROOT_PASSWORD}" -H "Accept: application/json" -H "X-Requested-By: gli-verify" "http://${LAB_IP_GRAYLOG}:9000/api/search/universal/relative?query=source%3Asmoketest-stack%20AND%20message%3AGLI7X9K2QM&range=300&limit=5"'

  This queries Graylog's real REST search API (not the container, not
  the compose logs) for messages from source `smoketest-stack`
  containing the exact marker `GLI7X9K2QM` emitted in gli-10, within
  the last 300 seconds. This is the real proof the integration works
  end-to-end -- the role installing/starting without error is not
  sufficient on its own.

scope:
  allowed_paths: []
  forbidden_actions:
    - "Any file edit"
    - "Any terragrunt or provision.sh command"
    - "Querying any source other than smoketest-stack or any marker other than GLI7X9K2QM"

gates:
  - id: marker-message-found-in-graylog
    cmd: "PVE_ENV=pve-test-vm ./with-secrets bash -c 'curl -s --max-time 10 -u \"admin:${GRAYLOG_ROOT_PASSWORD}\" -H \"Accept: application/json\" -H \"X-Requested-By: gli-verify\" \"http://${LAB_IP_GRAYLOG}:9000/api/search/universal/relative?query=source%3Asmoketest-stack%20AND%20message%3AGLI7X9K2QM&range=300&limit=5\"' | python3 -c \"import json,sys; d=json.load(sys.stdin); msgs=d.get('messages',[]); print('match_count:', len(msgs)); sys.exit(0 if len(msgs) > 0 else 1)\""
    expect: "exit 0, match_count >= 1 (confirmed 0 matches for this exact query before smoketest-stack existed, at plan-write time -- see Preflight facts above)"
    critical: true
```

## Operator step: gli-12-teardown

Not a step block -- destroying infrastructure is never handed to the
local model. Run regardless of how far this test got, so
`smoketest-stack` doesn't linger on pve-test-vm.

Run `./with-secrets terragrunt --working-dir terraform/lxc/environments/pve-test-vm/smoketest-stack destroy -auto-approve`
first (only needed if `gli-05-terragrunt-apply` actually ran), then
remove `terraform/lxc/stacks/smoketest-stack/`,
`terraform/lxc/environments/pve-test-vm/smoketest-stack/`, and
`terraform/lxc/ansible/playbooks/deploy-smoketest-stack.yml` from the
repo.
