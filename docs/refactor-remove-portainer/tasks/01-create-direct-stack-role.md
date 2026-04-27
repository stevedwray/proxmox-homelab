# Task 01: Create `direct_stack` Ansible role

## Type

Development

## Objective

Create a reusable Ansible role that deploys a Docker Compose stack directly on the
target LXC, with no Portainer dependency. This role is the standard deployment
mechanism for new platform stacks and is the explicit replacement for `app_stack` in
the NetBox playbook (Task 06).

## Files

- `terraform/lxc/ansible/roles/direct_stack/defaults/main.yml` (create)
- `terraform/lxc/ansible/roles/direct_stack/tasks/main.yml` (create)

## Preconditions

- Task 00 complete.
- `terraform/lxc/ansible/roles/app_stack/` exists and is readable.

## Background

The existing `app_stack` role deploys stacks via the Portainer API. The `direct_stack`
role replaces it for platform stacks with an identical variable interface so playbooks
can switch with minimal changes.

The deployment mechanism is `community.docker.docker_compose_v2` with `state: present`.
This is the same module used by the existing platform playbooks (authentik, monitoring,
proxy). `state: present` ensures containers are running even if the compose file has
not changed since the last run — correctly handling the reboot case without requiring a
content diff.

The compose file is written to disk with a SHA256 idempotency check so the write
operation is skipped when content is unchanged. The `state: present` deploy runs
unconditionally on every invocation to guarantee running state.

## Operations

1. Read `terraform/lxc/ansible/roles/app_stack/defaults/main.yml` and
   `terraform/lxc/ansible/roles/app_stack/tasks/main.yml` before writing anything.
   Note the variable names and the `{name, value}` dict structure for env vars.

2. Create `defaults/main.yml`:

```yaml
---
direct_stack_name: "{{ inventory_hostname }}"
direct_stack_compose_dir: "/opt/{{ direct_stack_name }}"
direct_stack_compose_path: "{{ direct_stack_compose_dir }}/docker-compose.yml"
direct_stack_compose_content: ""    # caller must set
direct_stack_env: []                # list of {name: X, value: Y} dicts — matches app_stack interface
direct_stack_prune_on_update: true
```

3. Create `tasks/main.yml` implementing these steps in order:

   a. Ensure compose directory exists (mode `0750`)

   b. Write `.env` file from `direct_stack_env` — convert `{name, value}` dicts to
      `NAME=VALUE` lines, mode `0600`, `no_log: true`

   c. Slurp the current compose file if it exists (`failed_when: false`), compute its
      SHA256. Compute SHA256 of `direct_stack_compose_content`.

   d. Write compose file only when the SHA256 differs (mode `0640`).

   e. When compose file was written or is new: validate with
      `docker compose -f "{{ direct_stack_compose_path }}" config -q`
      (`changed_when: false`)

   f. Deploy using `community.docker.docker_compose_v2`:
      ```yaml
      community.docker.docker_compose_v2:
        project_src: "{{ direct_stack_compose_dir }}"
        state: present
        remove_orphans: "{{ direct_stack_prune_on_update }}"
      ```
      This runs **unconditionally** (not gated on SHA256 change) so that stopped
      containers are restarted on every playbook run.

4. `no_log: true` on the .env write task and any task that loops over
   `direct_stack_env`.

5. Ensure `changed_when: false` on the compose validate command task.

## Postconditions

- Role exists and passes `ansible-lint`.
- Running the role twice against a deployed stack with unchanged compose content
  produces no `changed` tasks on the second run (the compose write is skipped;
  `docker_compose_v2` with `state: present` on an already-running stack reports
  no changes).
- No reference to Portainer, `app_stack`, or any Portainer API URL in the role.

## Validation

```bash
cd terraform/lxc/ansible
ansible-lint roles/direct_stack/
grep -r "portainer\|app_stack" terraform/lxc/ansible/roles/direct_stack/
# Expected: no output
```

## Stop Conditions

- Stop if `app_stack` uses a variable name or env dict structure not documented here
  — report the discrepancy before writing `direct_stack`.
- Stop if `community.docker.docker_compose_v2` is not available in the Ansible
  environment — report the collection version and do not use raw `docker compose`
  shell commands as a substitute.
