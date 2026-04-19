# Workflow Instructions

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

Run the appropriate scan(s) before merging any branch, based on what changed:

| Change type | Command |
| --- | --- |
| Terraform files modified | `/home/steve/.local/bin/snyk iac test terraform/` |
| Code files modified (Python, shell, YAML) | `source .env && sonar-scanner` |

If a scan returns new issues, **stop and present options** — do not merge until the issues are resolved or explicitly accepted by the user.

## Execution Guardrails

- Before any `terragrunt apply` or deployment validation run, verify `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` returns `pve-test`; otherwise stop and treat it as a targeting error.
- For direct Ansible validation against inline inventories like `-i '10.57.x.x,'`, always pass `-u root`; otherwise Ansible can silently fall back to the local workstation username and report misleading SSH failures.
