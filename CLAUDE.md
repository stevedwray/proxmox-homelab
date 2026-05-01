# Workflow Instructions

## Branch Model

```
work/* branches                    ← active development
       ↓  full infrastructure teardown + redeploy validated
baseline/teardown-validated        ← infrastructure foundation known good
       ↓  application stacks deploy successfully on top
dev/pve-test                       ← application deployment known good
       ↓  stable and tested
main
```

| Branch | Meaning | Promotion gate |
|---|---|---|
| `baseline/teardown-validated` | Full infrastructure teardown and redeploy has been validated from this state. | Run and pass a complete teardown + infrastructure redeploy cycle. |
| `dev/pve-test` | Application stacks deploy successfully on the infrastructure. | Validate application stacks on top of `baseline/teardown-validated`. |

**Never merge directly into either branch** — work must pass its promotion gate first. Active development happens on `work/*` or short-lived `feat/`, `fix/`, `task/` branches.

## Branching

- Infrastructure work: cut `work/*` from the current working state; validate through a full teardown + redeploy cycle; promote to `baseline/teardown-validated`.
- Application stack work: cut `feat/`, `fix/`, or `task/` from `dev/pve-test`; validate stacks on top of `baseline/teardown-validated`; promote to `dev/pve-test`.
- AI tooling / workflow changes: cut `feat/` from `dev/pve-test`; merge directly to `dev/pve-test` (no infrastructure gate required).
- Validate in the short-lived branch before merging. If validation fails, stop and present options — do not merge until resolved or explicitly accepted.
- PR `dev/pve-test` → `main` only when stable and tested on the test server.
- After merging to `main`, pull `main` back into `dev/pve-test` to stay in sync.

## Commits and Issues

- After a fix is verified (tests pass, playbook runs clean), commit and close the issue immediately — do not wait to be asked
- Commit with `Closes #N` in the message
- Run `gh issue close N --comment "Fixed in commit <sha>"` after committing
- Do both before reporting back

## Security Scanning

- **snyk**: `/home/steve/.local/bin/snyk iac test terraform/` — Terraform IaC only, not Ansible
- **sonar-scanner**: `source .env && sonar-scanner` — config in `sonar-project.properties`
