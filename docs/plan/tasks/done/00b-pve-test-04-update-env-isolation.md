# 00b-pve-test-04 — Update .env.pve-test and verify pve-test isolation

> Historical archived task. Useful for implementation history only.
> Do not use this as the current deployment procedure.
> Active docs under `docs/design/` and `docs/plan/` take precedence.

## Status

PENDING

## Phase

Phase 00b — pve-test Management Bootstrap

## Prerequisites

- Task 00b-03 complete: Portainer running at `192.168.1.20:9000`
- Admin login verified working

## Objective

`TF_VAR_portainer_server_ip=192.168.1.20` is set in `.env.pve-test` and all subsequent `terragrunt apply` runs on pve-test register Portainer agents with the local server, not the production server at `192.168.1.4`.

## Scope

- Add `TF_VAR_portainer_server_ip=192.168.1.20` to `.env.pve-test`
- Add a placeholder comment for this variable in `.env.template`
- Commit and push the changes
- Verify that pve-test no longer requires production Portainer at `192.168.1.4`

> **Naming note**: Once pve-test has its own Portainer server, all subsequent stacks deployed
> through it use their **canonical names** (e.g., `netbox-stack`, `harbor-stack`) with no
> `-test` suffix. The `-test` suffix on `netbox-stack-test` existed only because the original
> deployment shared the production Portainer. With an isolated Portainer server at
> `192.168.1.20`, pve-test stacks are fully namespaced by server — no naming workaround needed.

## Out of Scope

- Redeploying any stacks to test the new variable (that happens in subsequent phases)
- Modifying the Terraform portainer_agent module
- Any changes to production `.env`

## Inputs

- `.env.pve-test` — current content
- `.env.template` — add comment-only placeholder
- `docs/plan/phase-00b-pve-test-management.md` — Part D for exact content

## Expected Outputs

- `.env.pve-test` — updated with `TF_VAR_portainer_server_ip=192.168.1.20` line
- `.env.template` — comment added noting that pve-test override lives in `.env.pve-test`
- Commit on branch `feat/pve-test-portainer` pushed to `dev/pve-test`

## Constraints and Conventions

- `.env.pve-test` is committed to the repo (it contains no secrets, only override values)
- `.env` is NOT committed (contains secrets)
- The export line in `.env.pve-test` must use `export` prefix to be effective when sourced
- Phase 00b commit message follows the pattern in the phase doc

## Acceptance Criteria

- [ ] `.env.pve-test` contains `export TF_VAR_portainer_server_ip=192.168.1.20`
- [ ] `.env.template` has a comment explaining the pve-test override
- [ ] `source .env && source .env.pve-test && echo $TF_VAR_portainer_server_ip` prints `192.168.1.20`
- [ ] Branch `feat/pve-test-portainer` committed and merged to `dev/pve-test`
- [ ] `git push origin dev/pve-test` succeeds
- [ ] Phase 00b acceptance criteria checklist in `docs/plan/phase-00b-pve-test-management.md` is fully satisfied

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Update .env.pve-test to point pve-test stack deployments at the local Portainer server
(192.168.1.20) instead of the production server (192.168.1.4). Then commit and push.

BEFORE EDITING, READ:
  .env.pve-test          (current content — add the new variable)
  .env.template          (add a note-only placeholder — no secrets in this file)
  docs/plan/phase-00b-pve-test-management.md  (Part D for exact instructions)

CHANGES NEEDED:

1. .env.pve-test — add this line (keep it alongside other TF_VAR overrides):
   # Portainer server for pve-test (overrides production default of 192.168.1.4)
   export TF_VAR_portainer_server_ip=192.168.1.20

2. .env.template — add a comment block (no actual values, just documentation):
   # pve-test overrides — set in .env.pve-test, not here
   # TF_VAR_portainer_server_ip=192.168.1.20   # pve-test Portainer (overrides prod 192.168.1.4)

VERIFY THE CHANGE:
  source .env && source .env.pve-test
  echo $TF_VAR_portainer_server_ip
  # Expected: 192.168.1.20

COMMIT:
  cd /home/steve/git/proxmox-homelab
  git add terraform/lxc/stacks/portainer-stack/stack.yaml \
          terraform/lxc/stacks/portainer-stack/terragrunt.hcl \
          terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml \
          .env.pve-test \
          .env.template

  git commit -m "feat(pve-test): deploy standalone Portainer server at 192.168.1.20

- portainer-stack LXC (VMID 120) on pve-test at 192.168.1.20
- stack.yaml and terragrunt.hcl for portainer-stack
- deploy-portainer-stack.yml: docker_base + compose deploy + admin init
- TF_VAR_portainer_server_ip=192.168.1.20 in .env.pve-test
- pve-test no longer depends on production Portainer at 192.168.1.4"

  git push origin feat/pve-test-portainer

SECURITY SCAN (run before merging — stop and present options if new issues are found):
  /home/steve/.local/bin/snyk iac test terraform/
  cd /home/steve/git/proxmox-homelab && source .env && sonar-scanner

  git checkout dev/pve-test
  git merge feat/pve-test-portainer
  git push origin dev/pve-test

DONE WHEN: Variable is in .env.pve-test, commit is on dev/pve-test, and sourcing both
env files produces TF_VAR_portainer_server_ip=192.168.1.20.
```
