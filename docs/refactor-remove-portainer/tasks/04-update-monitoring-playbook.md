# Task 04: Update `deploy-monitoring-stack.yml`

## Type

Development

## Objective

Remove Portainer from the monitoring deployment playbook. The change is minimal: remove
`portainer_agent` from Play 1 and add the agent service mask task. The monitoring stack
deploys via `community.docker.docker_compose_v2` inline — that mechanism is unchanged.

## Files

- `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`

## Preconditions

- Task 01 complete.

## Background

The playbook currently has two plays:
1. `Configure Docker base and Portainer Agent` — roles: lxc_base, docker_base,
   portainer_agent; plus inline tasks for daemon.json (Docker registry trust) and
   handler to restart Docker
2. `Deploy monitoring compose stack` — inline tasks generating config for Loki,
   Promtail, Grafana datasources; writing compose file inline; deploying via
   `community.docker.docker_compose_v2`; health checks for Grafana, VictoriaMetrics,
   Loki

The `app_stack` role is **not used**. The only change needed is removing
`portainer_agent` and masking the service.

**Play 2 must not be modified.** It generates and deploys the entire monitoring stack
configuration inline. Changes here risk breaking the monitoring deployment and health
checks that the teardown test validates.

## Operations

1. Read the full playbook before editing.

2. In Play 1 (`Configure Docker base and Portainer Agent`):
   - Remove `portainer_agent` from the `roles:` list.
   - Add the mask task to the `tasks:` section (it already has one):

     ```yaml
     - name: Mask portainer-agent service (platform tier — no agent on this host)
       ansible.builtin.systemd:
         name: portainer-agent.service
         masked: true
         enabled: false
       failed_when: false
     ```

     Place this task after the `Flush handlers` task at the end of Play 1's task list.

   - Remove any vars in Play 1 that exist solely for `portainer_agent`.

3. Rename the play from `Configure Docker base and Portainer Agent` to
   `Configure Docker base`.

4. Do not touch Play 2.

5. Register a playbook syntax check in the teardown-test harness. In
   `scripts/teardown-deploy-test.sh`, inside `run_source_preflight_checks`, add
   the following before the closing `}`:

   ```bash
   run_logged "syntax-check-deploy-monitoring-stack" \
       bash -lc "ANSIBLE_ROLES_PATH='${ANSIBLE_DIR}/roles' \
         ANSIBLE_CONFIG='${ANSIBLE_DIR}/ansible.cfg' \
         ansible-playbook --syntax-check \
           '${ANSIBLE_DIR}/playbooks/deploy-monitoring-stack.yml'"
   ```

   `ANSIBLE_DIR` is defined at line 21 of the harness as `"${TERRAFORM_LXC}/ansible"`.

## Postconditions

- Playbook deploys the monitoring stack with no Portainer dependency.
- Play 2 with its inline config generation and health checks is intact.
- `scripts/teardown-deploy-test.sh source-preflight` runs `syntax-check-deploy-monitoring-stack`
  and it passes.

## Validation

```bash
grep -in "portainer" terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
# The only acceptable match is the mask task's service name string

ansible-lint terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml

scripts/teardown-deploy-test.sh source-preflight
# Expected: syntax-check-deploy-monitoring-stack passes
```

## Stop Conditions

- Stop if Play 1 contains any task (not a role) that does Portainer-specific work —
  report the task before removing.
- Stop if removing `portainer_agent` from Play 1 would leave Play 1 with only roles
  and no tasks — that is fine, leave it as roles-only (the mask task is added).
