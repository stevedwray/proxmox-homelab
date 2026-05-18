# Next Session Handoff

## Goal
Test a real Day 2 change after the Day 1 baseline deploy by changing an already
deployed container through Ansible rather than through Terraform/container
recreate.

The point of the session is to prove that we can:

- pick an existing service running on `pve-test`
- change its post-deploy configuration through the stack Ansible flow
- apply and verify that change cleanly on a live container
- capture what worked well and what needs hardening for repeatable Day 2 ops

## Current Baseline
- `baseline/teardown-validated` now contains the validated storage refactor and
  SSD cutover.
- Full teardown + redeploy gate passed for the SSD-backed storage policy.
- Next session should start from the promoted baseline and use a fresh short-lived
  branch.

## Recommended Day 2 Target
Use `apt-cacher-stack` first.

Why this is a good first Day 2 exercise:
- it is simple compared with the Docker Compose application stacks
- it is a systemd-managed service, so change/verify loops are fast
- configuration changes are easy to observe through HTTP and service status
- it avoids mixing the Day 2 workflow test with a large application bootstrap

Primary files to inspect first:
- `terraform/lxc/stacks/apt-cacher-stack/stack.yaml`
- `terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml`
- `terraform/lxc/ansible/roles/apt_cacher_stack/`

## Suggested Change Types
Pick one concrete change and push it end-to-end through Ansible.

Preferred first option:
- add or change a templated apt-cacher-ng configuration value that can be
  validated with:
  - systemd service status
  - HTTP response from port `3142`
  - config file content on the container

Good alternatives if the apt-cacher role is too thin:
- `dns-stack`: adjust a managed CoreDNS setting or zone/render input and verify
  via `dig`
- `proxy-stack`: adjust a Traefik-managed runtime setting and verify via HTTP
- `monitoring-stack`: adjust a Grafana/VictoriaMetrics config value with a clear
  health check

## Session Plan
1. Create a fresh short-lived branch from the current `baseline/teardown-validated`.
2. Inspect the chosen stack’s playbook, role, templates, and vars layout.
3. Pick one small Day 2 change that is clearly service-owned and Ansible-managed.
4. Implement the config change in Ansible/templates/defaults as appropriate.
5. Apply only the relevant Day 2 change path rather than rerunning a full
   teardown unless the session explicitly expands in scope.
6. Verify the live service behavior after the change.
7. Document what command path should become the standard Day 2 reconfiguration
   workflow for that stack.

## Acceptance Criteria
- The target stack is updated in place through Ansible on an already deployed
  container.
- Verification proves the new config is actually live.
- The workflow is documented clearly enough to repeat in a later session.
- No Terraform-driven container rebuild is required for the selected change.

## Suggested Start Commands
```bash
git checkout baseline/teardown-validated
git pull --ff-only origin baseline/teardown-validated
git checkout -b work/day2-ansible-change-01
./scripts/teardown-deploy-test.sh live-preflight
```

If using the apt-cacher stack, likely useful follow-up inspection commands:
```bash
sed -n '1,220p' terraform/lxc/stacks/apt-cacher-stack/stack.yaml
find terraform/lxc/ansible/roles/apt_cacher_stack -maxdepth 3 -type f | sort
sed -n '1,220p' terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml
```

## Guardrails
- Keep the session scoped to Day 2 operations, not another storage or baseline
  refactor.
- Use a fresh short-lived branch only.
- Run the appropriate required scan before merge:
  - shell/Python/YAML/Ansible changes:
    `./with-secrets /home/steve/.local/bin/sonar-scanner`
- Avoid destructive teardown unless the session explicitly decides to widen the
  scope.
