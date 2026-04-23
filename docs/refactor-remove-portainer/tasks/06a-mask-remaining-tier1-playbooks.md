# Task 06a: Add Tier 1 agent-service masking to remaining playbooks

## Type

Development

## Objective

Add the standard Tier 1 `portainer-agent.service` mask task to the remaining
platform playbooks that do not currently use Portainer roles directly but still
must actively suppress the agent service under the single-template model.

## Files

- `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml`
- `terraform/lxc/ansible/playbooks/deploy-step-ca.yml`
- `terraform/lxc/ansible/playbooks/deploy-coredns.yml`
- `terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml`
- `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`

## Preconditions

- None.

## Background

Under the refactor's single-template decision, Tier 1 safety does not come from
using a different base image. It comes from playbooks actively masking
`portainer-agent.service`.

These five playbooks do not currently call `portainer_agent`, `portainer_api`,
or `app_stack`, but they still need the standard Tier 1 mask task to enforce
the target model consistently.

## Operations

1. Read each playbook in full before editing.
2. Add the standard mask task to each playbook:

   ```yaml
   - name: Mask portainer-agent service (platform tier — no agent on this host)
     ansible.builtin.systemd:
       name: portainer-agent.service
       masked: true
       enabled: false
     failed_when: false
   ```

3. Place the task in a stable, early point in the playbook where it does not
   alter unrelated behavior. Prefer immediately after existing base-role or
   reachability/bootstrap tasks.
4. Do not add any Portainer API, endpoint-registration, or agent-deployment
   behavior.
5. Run `ansible-lint` against the edited playbooks.

## Postconditions

- All five playbooks contain the standard Tier 1 mask task.
- No playbook gains any new Portainer deployment or registration logic.
- `ansible-lint` passes for the edited playbooks.

## Validation

```bash
rg -n "Mask portainer-agent service|portainer-agent.service" \
  terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml \
  terraform/lxc/ansible/playbooks/deploy-step-ca.yml \
  terraform/lxc/ansible/playbooks/deploy-coredns.yml \
  terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml \
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

ansible-lint \
  terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml \
  terraform/lxc/ansible/playbooks/deploy-step-ca.yml \
  terraform/lxc/ansible/playbooks/deploy-coredns.yml \
  terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml \
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml
```

## Stop Conditions

- Stop if any of the five playbooks already contains a different
  `portainer-agent.service` management task — report the file and lines before
  editing.
- Stop if adding the mask task requires restructuring unrelated playbook logic.
