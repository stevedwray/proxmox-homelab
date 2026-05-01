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
|---|---|
| Terraform files modified | `/home/steve/.local/bin/snyk iac test terraform/` |
| Code files modified (Python, shell, YAML) | `./with-secrets /home/steve/.local/bin/sonar-scanner` |

If a scan returns new issues, **stop and present options** — do not merge until the issues are resolved or explicitly accepted by the user.

## Workspace Operating Patterns

- Use `./with-secrets <command>` for commands that need credentials. It injects non-secret local config plus SOPS-backed secrets from `terraform/secrets.enc.yaml`; do not rely on `source .env` for secret-bearing workflows.
- Treat `.env` as gitignored non-secret config only: hostnames, node names, IPs, usernames, and workspace names. Real passwords, tokens, API keys, and service secrets belong in `terraform/secrets.enc.yaml` via SOPS.
- New Terraform secrets in SOPS should use the exact `TF_VAR_*` environment variable name Terraform expects, such as `TF_VAR_lxc_password` or `TF_VAR_pm_api_token_secret`, rather than adding a separate mapping layer.
- Edit SOPS secrets with `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml`. Do not decrypt secrets into plaintext files or commit private age keys.
- `with-secrets` defaults to the `pve-test` workflow and refuses non-`pve-test` targets unless `ALLOW_PVE=true` is explicitly set for intentional production work.
- GitHub Actions secrets are for CI-only values and CI SOPS decryption. Local infrastructure automation should prefer SOPS plus `with-secrets`.
- Generated files under `terraform/lxc/.generated/` are runtime output, not source of truth. Regenerate them from manifests immediately before publish or validation.
- Prefer dry-run-first workflows for reconcilers and edge changes. Use full baseline reconciler checks after applies when validating stack-owned edge state.
- Keep runtime evidence, logs, backups, and large snapshots under ignored timestamped evidence directories; summarize results in tracked docs instead of committing bulky artifacts or secrets.
