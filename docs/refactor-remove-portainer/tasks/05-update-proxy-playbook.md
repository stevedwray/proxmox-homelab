# Task 05: Update `deploy-proxy-stack.yml`

## Type

Development

## Objective

Remove Portainer from the Traefik proxy deployment playbook. Remove `portainer_agent`
from Play 1 and add the agent service mask task. The proxy stack deploys via
`community.docker.docker_compose_v2` inline — that mechanism is unchanged.

## Files

- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`

## Preconditions

- Task 01 complete.

## Background

The playbook currently has two plays:
1. `Configure Docker base and Portainer Agent` — roles: lxc_base, docker_base,
   portainer_agent; plus inline tasks for daemon.json (Docker registry trust) and
   handler to restart Docker
2. `Deploy Traefik compose stack` — inline tasks writing: Traefik directory structure,
   ACME storage files, `.env` (Cloudflare DNS API token), `traefik.yml` static config,
   `authentik.yml` forward-auth middleware, `certs.yml` wildcard cert config,
   `docker-compose.yml`; tasks for publishing generated Traefik dynamic files;
   `docker_compose_v2` deploy

The `app_stack` role is **not used**. The only change needed is removing
`portainer_agent` and masking the service.

**Play 2 must not be modified.** It generates the full Traefik static and dynamic
configuration. In particular, `traefik.yml` contains certificate resolver config
(LE staging + step-ca), the `authentik.yml` forward-auth middleware, and the
`traefik_generated_source_dir` logic for publishing reconciler-generated dynamic
files. All of this is load-bearing for the edge infrastructure.

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

   - Remove any vars in Play 1 that exist solely for `portainer_agent`.

3. Rename the play from `Configure Docker base and Portainer Agent` to
   `Configure Docker base`.

4. Do not touch Play 2.

## Postconditions

- Playbook deploys Traefik with no Portainer dependency.
- All Traefik-specific configuration steps in Play 2 are intact.

## Validation

```bash
grep -in "portainer" terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml
# The only acceptable match is the mask task's service name string

ansible-lint terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml
```

## Stop Conditions

- Stop if Play 1 contains any task (not a role) that does Portainer-specific work
  — report before removing.
- Stop if Play 2 references `portainer_agent_*` variables — report before proceeding.
