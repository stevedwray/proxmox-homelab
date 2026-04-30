# Workflow Instructions

## Protected Branches

**Do not commit to or merge into these branches without explicit instruction.**

| Branch | Purpose | Rule |
|---|---|---|
| `baseline/teardown-validated` | Preserved snapshot of system state after teardown was validated. Intentionally 3 commits ahead of `dev/pve-test` (SOPS updates and docs not yet integrated). | **READ-ONLY. Never commit or merge into it.** |
| `dev/pve-test` | Known-good integration branch for the test server. | Only receives: (1) work fully validated on a working branch, (2) AI tooling/workflow changes. **Never merge task, fix, exec, or chore branches directly.** |

All development work goes to a **working branch** cut from `dev/pve-test`. Only after validation (tests pass, playbook runs clean, scans pass) does it merge to `dev/pve-test`.

## Branching

- `dev/pve-test` is the long-running integration branch tracking the test server state
- Cut short-lived branches from `dev/pve-test` (e.g. `fix/terraform-fmt`, `feat/harbor-deployment`)
- Validate changes in the short-lived branch (tests pass, playbook runs clean) before merging, if issues are encountered in validation stop and offer options.
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
