# Task 02: Update `deploy-harbor-stack.yml`

## Type

Development

## Objective

Remove Portainer from the Harbor deployment playbook. Harbor does not use `app_stack`
or `portainer_api` for its Docker deployment — it uses `harbor_installer`. The changes
are: remove the `portainer_agent` role from Play 1, remove Play 2 (the Portainer API
registration play) entirely, and add the agent service mask task.

## Files

- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`

## Preconditions

- Task 01 complete.

## Background

The playbook currently has four plays:
1. `Configure Docker base and Portainer Agent` — roles: lxc_base, docker_base,
   portainer_agent
2. `Register endpoint with Portainer` — roles: portainer_api
3. `Install and start Harbor` — roles: harbor_installer
4. `Configure Harbor (proxy cache, robot account)` — roles: harbor_postconfigure

Harbor's Docker deployment is entirely handled by `harbor_installer`. The `app_stack`
role is **not used** in this playbook. The Portainer involvement is only agent
installation (Play 1) and API registration (Play 2).

**Play 3 and Play 4 must not be modified.** Harbor has a specialised installer and
post-configuration workflow. Any change to those plays that breaks Harbor's deployment
will fail the rebuild validation.

## Operations

1. Read the full playbook before editing.

2. In Play 1 (`Configure Docker base and Portainer Agent`):
   - Remove `portainer_agent` from the `roles:` list.
   - Add the following task at the **end** of the `tasks:` section (or create a
     `tasks:` section if it only had roles):

     ```yaml
     - name: Mask portainer-agent service (platform tier — no agent on this host)
       ansible.builtin.systemd:
         name: portainer-agent.service
         masked: true
         enabled: false
       failed_when: false
     ```

   - Remove any vars in Play 1 that exist solely to configure `portainer_agent`
     (e.g. `portainer_agent_*` vars). Do not remove `docker_registry_host` or any
     var consumed by a retained role or task.

3. Remove Play 2 (`Register endpoint with Portainer`) entirely. Remove all vars
   scoped to that play (`portainer_api_server_ip`, `portainer_api_endpoint_name`,
   `portainer_api_agent_ip`).

4. Do not touch Play 3 or Play 4.

5. Update the comment block at the top of the file to remove the Portainer references.

6. Register a playbook syntax check in the teardown-test harness. In
   `scripts/teardown-deploy-test.sh`, inside `run_source_preflight_checks`, add
   the following before the closing `}`:

   ```bash
   run_logged "syntax-check-deploy-harbor-stack" \
       bash -lc "ANSIBLE_ROLES_PATH='${ANSIBLE_DIR}/roles' \
         ANSIBLE_CONFIG='${ANSIBLE_DIR}/ansible.cfg' \
         ansible-playbook --syntax-check \
           '${ANSIBLE_DIR}/playbooks/deploy-harbor-stack.yml'"
   ```

   `ANSIBLE_DIR` is defined at line 21 of the harness as `"${TERRAFORM_LXC}/ansible"`.
   This check runs on every `source-preflight` and catches YAML/structural errors
   without needing live infrastructure.

## Postconditions

- Playbook deploys Harbor with no Portainer dependency.
- `harbor_installer` and `harbor_postconfigure` roles are intact and unmodified.
- Play count is reduced from 4 to 3.
- `scripts/teardown-deploy-test.sh source-preflight` runs `syntax-check-deploy-harbor-stack`
  and it passes.

## Validation

```bash
grep -in "portainer" terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
# Expected: no output (the comment at top may reference portainer — remove it)

cd terraform/lxc/ansible
ansible-lint playbooks/deploy-harbor-stack.yml

scripts/teardown-deploy-test.sh source-preflight
# Expected: syntax-check-deploy-harbor-stack passes
```

## Stop Conditions

- Stop if Play 1 contains any `portainer_agent_*` variable that is also consumed by
  `harbor_installer` or `harbor_postconfigure` — flag the dependency before removing.
- Stop if Play 2 contains any task that is not a pure Portainer API operation —
  report the task name and content before removing the play.
