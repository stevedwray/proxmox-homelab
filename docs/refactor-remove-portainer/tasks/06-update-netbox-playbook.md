# Task 06: Update `deploy-netbox-stack.yml`

## Type

Development

## Objective

NetBox is the only Tier 1 stack that currently uses both `portainer_api` and
`app_stack`. This is the most substantial playbook change in the refactor. Remove
`portainer_agent` from Play 1, replace the Portainer API + app_stack deployment play
(Play 3) with `direct_stack`, update the container name reference in Play 4, and add
the agent service mask task.

## Files

- `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`

## Preconditions

- Task 01 complete — `direct_stack` role exists.

## Background

The playbook currently has four plays:
1. `Configure Docker base and Portainer Agent` — roles: lxc_base, docker_base,
   portainer_agent; plus inline tasks for daemon.json
2. `Provision NetBox configuration files on host` — copies four Python config files
   from `stacks/netbox-stack/configuration/` to `/srv/docker/netbox/configuration/`
3. `Register endpoint and deploy stack via Portainer API` — roles: portainer_api,
   app_stack
4. `Create NetBox superuser and API token` — inline tasks using `docker exec`

**Play 2 and Play 4 must not be modified** except as explicitly described below.

**Docker Compose project naming:** The existing Play 3 deploys via Portainer with
`app_stack_name` defaulting to `netbox-stack` (the stack directory name). Portainer
names containers as `<stack_name>-<service>-<N>`, so the NetBox container is currently
`netbox-stack-netbox-1`.

`direct_stack` with `project_src: /srv/docker/netbox` will name the project `netbox`
(from the directory name), making the container `netbox-netbox-1`. **Play 4 must be
updated** to use the new container name.

## Operations

1. Read the full playbook before editing.

2. In Play 1 (`Configure Docker base and Portainer Agent`):
   - Remove `portainer_agent` from the `roles:` list.
   - Add the mask task to the `tasks:` section after the `Flush handlers` task:

     ```yaml
     - name: Mask portainer-agent service (platform tier — no agent on this host)
       ansible.builtin.systemd:
         name: portainer-agent.service
         masked: true
         enabled: false
       failed_when: false
     ```

   - Remove vars that exist solely for `portainer_agent`. Rename play to
     `Configure Docker base`.

3. Leave Play 2 (`Provision NetBox configuration files on host`) entirely unchanged.
   It correctly uses `/srv/docker/netbox/configuration/`.

4. Replace Play 3 (`Register endpoint and deploy stack via Portainer API`) with:

   ```yaml
   - name: Deploy NetBox compose stack
     hosts: all
     become: true
     gather_facts: false

     vars:
       direct_stack_name: "netbox"
       direct_stack_compose_dir: "/srv/docker/netbox"
       direct_stack_compose_content: "{{ lookup('file', '../../stacks/' + stack_name + '/docker-compose.yml') }}"
       direct_stack_env:
         - name: NETBOX_DB_PASSWORD
           value: "{{ lookup('env', 'NETBOX_DB_PASSWORD') | mandatory('NETBOX_DB_PASSWORD env var is not set') }}"
         - name: NETBOX_REDIS_PASSWORD
           value: "{{ lookup('env', 'NETBOX_REDIS_PASSWORD') | mandatory('NETBOX_REDIS_PASSWORD env var is not set') }}"
         - name: NETBOX_REDIS_CACHE_PASSWORD
           value: "{{ lookup('env', 'NETBOX_REDIS_CACHE_PASSWORD') | mandatory('NETBOX_REDIS_CACHE_PASSWORD env var is not set') }}"
         - name: NETBOX_SECRET_KEY
           value: "{{ lookup('env', 'NETBOX_SECRET_KEY') | mandatory('NETBOX_SECRET_KEY env var is not set') }}"
         - name: NETBOX_API_TOKEN_PEPPER
           value: "{{ lookup('env', 'NETBOX_API_TOKEN_PEPPER') | mandatory('NETBOX_API_TOKEN_PEPPER env var is not set') }}"
         - name: REGISTRY_HOST
           value: "{{ registry_host | default('10.57.3.10') }}"

     roles:
       - direct_stack
   ```

5. In Play 4 (`Create NetBox superuser and API token`), update the container name var:

   ```yaml
   # Before
   netbox_container: "{{ app_stack_name }}-netbox-1"
   # After
   netbox_container: "netbox-netbox-1"
   ```

   Remove any remaining reference to `app_stack_name` in Play 4.

6. Register a playbook syntax check in the teardown-test harness. In
   `scripts/teardown-deploy-test.sh`, inside `run_source_preflight_checks`, add
   the following before the closing `}`:

   ```bash
   run_logged "syntax-check-deploy-netbox-stack" \
       bash -lc "ANSIBLE_ROLES_PATH='${ANSIBLE_DIR}/roles' \
         ANSIBLE_CONFIG='${ANSIBLE_DIR}/ansible.cfg' \
         ansible-playbook --syntax-check \
           '${ANSIBLE_DIR}/playbooks/deploy-netbox-stack.yml'"
   ```

   `ANSIBLE_DIR` is defined at line 21 of the harness as `"${TERRAFORM_LXC}/ansible"`.

## Postconditions

- Playbook deploys NetBox via `direct_stack` with no Portainer API dependency.
- Configuration files from Play 2 are in `/srv/docker/netbox/configuration/` before
  the compose stack starts (Play 2 runs before Play 3 in playbook order).
- Play 4 uses container name `netbox-netbox-1`.
- No reference to `portainer_api`, `app_stack`, or `portainer_agent` roles remains.
- `scripts/teardown-deploy-test.sh source-preflight` runs `syntax-check-deploy-netbox-stack`
  and it passes.

## Validation

```bash
grep -in "portainer\|app_stack" terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml
# Expected: only the mask task's service name string

cd terraform/lxc/ansible
ansible-lint playbooks/deploy-netbox-stack.yml

scripts/teardown-deploy-test.sh source-preflight
# Expected: syntax-check-deploy-netbox-stack passes
```

## Stop Conditions

- Stop if the `app_stack_env` list in Play 3 contains any env var not listed in the
  Operations section above — report the additional var before proceeding.
- Stop if Play 4's container name pattern is not `{{ app_stack_name }}-netbox-1` —
  report the actual pattern before updating.
- Stop if `stacks/netbox-stack/docker-compose.yml` does not exist at the path
  used in Play 3's `lookup('file', ...)` — report the actual compose file location.
