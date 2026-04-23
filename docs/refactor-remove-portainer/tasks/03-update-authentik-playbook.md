# Task 03: Update `deploy-authentik-stack.yml`

## Type

Development

## Objective

Remove Portainer from the Authentik deployment playbook. The change is minimal: remove
the `portainer_agent` role from Play 1 and add the agent service mask task. Authentik
deploys via `community.docker.docker_compose_v2` inline — that mechanism is unchanged.

## Files

- `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`

## Preconditions

- Task 01 complete.

## Background

The playbook currently has two plays:
1. `Configure Docker base and Portainer Agent` — roles: lxc_base, docker_base,
   portainer_agent
2. `Deploy Authentik compose stack` — inline tasks using
   `community.docker.docker_compose_v2`

The `app_stack` role is **not used** in this playbook. Docker deployment is already
Portainer-independent. The only change needed is removing `portainer_agent` from Play 1
and masking the service.

**Play 2 must not be modified.** It contains Authentik-specific configuration: env
file writing with `AUTHENTIK_BOOTSTRAP_TOKEN` and `AUTHENTIK_BOOTSTRAP_PASSWORD`,
daemon.json Docker trust config, compose validation, the `docker_compose_v2` call, and
live/ready health checks. All of this is load-bearing for the bootstrap sequence.

## Operations

1. Read the full playbook before editing.

2. In Play 1 (`Configure Docker base and Portainer Agent`):
   - Remove `portainer_agent` from the `roles:` list.
   - If Play 1 has no `tasks:` section, add one. Add the mask task at the end:

     ```yaml
     tasks:
       - name: Mask portainer-agent service (platform tier — no agent on this host)
         ansible.builtin.systemd:
           name: portainer-agent.service
           masked: true
           enabled: false
         failed_when: false
     ```

   - Remove any vars in Play 1 that exist solely for `portainer_agent`.

3. Rename the play from `Configure Docker base and Portainer Agent` to
   `Configure Docker base`.

4. Do not touch Play 2.

5. Register a playbook syntax check in the teardown-test harness. In
   `scripts/teardown-deploy-test.sh`, inside `run_source_preflight_checks`, add
   the following before the closing `}`:

   ```bash
   run_logged "syntax-check-deploy-authentik-stack" \
       bash -lc "ANSIBLE_ROLES_PATH='${ANSIBLE_DIR}/roles' \
         ANSIBLE_CONFIG='${ANSIBLE_DIR}/ansible.cfg' \
         ansible-playbook --syntax-check \
           '${ANSIBLE_DIR}/playbooks/deploy-authentik-stack.yml'"
   ```

   `ANSIBLE_DIR` is defined at line 21 of the harness as `"${TERRAFORM_LXC}/ansible"`.

## Postconditions

- Playbook deploys Authentik with no Portainer dependency.
- Play 2 with its health checks and bootstrap credential injection is intact.
- `scripts/teardown-deploy-test.sh source-preflight` runs `syntax-check-deploy-authentik-stack`
  and it passes.

## Validation

```bash
grep -in "portainer" terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml
# Expected: no output (the portainer-agent.service string in the mask task is acceptable
# — grep -i portainer will match it; confirm the only hit is the mask task itself)

cd terraform/lxc/ansible
ansible-lint playbooks/deploy-authentik-stack.yml

scripts/teardown-deploy-test.sh source-preflight
# Expected: syntax-check-deploy-authentik-stack passes
```

## Stop Conditions

- Stop if Play 1 contains any task (not a role) that is doing Portainer-specific work
  — report the task before removing it.
- Stop if the `portainer_agent` role is used in Play 2 — report before proceeding
  (this would be unexpected).
