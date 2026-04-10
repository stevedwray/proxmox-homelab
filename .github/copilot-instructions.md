# Workflow Instructions

## Branching

- `dev/pve-test` is the long-running integration branch tracking the test server state
- Cut short-lived branches from `dev/pve-test` (e.g. `fix/terraform-fmt`, `feat/harbor-deployment`)
- Validate changes in the short-lived branch (tests pass, playbook runs clean) before merging
- Merge short-lived branches → `dev/pve-test`, not `main`
- PR `dev/pve-test` → `main` only when stable and tested on the test server
- After merging to `main`, pull `main` back into `dev/pve-test` to stay in sync
- Never PR directly to `main` unless already on `dev/pve-test` and tested

## Commits and Issues

- After a fix is verified (tests pass, playbook runs clean), commit and close the issue immediately — do not wait to be asked
- Commit with `Closes #N` in the message
- Run `gh issue close N --comment "Fixed in commit <sha>"` after committing
- Do both before reporting back

## Security Scanning

- **snyk**: `/home/steve/.local/bin/snyk iac test terraform/` — Terraform IaC only, not Ansible
- **sonar-scanner**: `source .env && sonar-scanner` — config in `sonar-project.properties`
