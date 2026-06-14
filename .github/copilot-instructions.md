# Workflow Instructions

## Branch Model

```
feat/* / fix/* / task/* / work/*   ← active development (temporary)
       ↓  teardown + redeploy validated
baseline/teardown-validated        ← known-good state
       ↓  stable and tested
main
```

| Branch | Meaning | Promotion gate |
|---|---|---|
| `baseline/teardown-validated` | Full infrastructure teardown and redeploy has been validated from this state. | Run and pass a complete teardown + infrastructure redeploy cycle. |

`dev/pve-test` is retired (archival only — do not use as a PR target).

Do not develop directly in `baseline/teardown-validated`. All active work happens on short-lived `feat/`, `fix/`, `task/`, or `work/*` branches cut from the current working HEAD.
Promotion merges into `baseline/teardown-validated` require the teardown gate to have been satisfied.
If the operator explicitly names a merge target, use that exact target and do not silently retarget.

## Branching

- All work: cut `feat/`, `fix/`, `task/`, or `work/*` from the current working HEAD.
- Validate on the short-lived branch (live runs, tests, populate checks).
- Promote to `baseline/teardown-validated` once a full teardown + redeploy cycle confirms the branch is known-good.
- `baseline/teardown-validated` is a **promotion target only** — never use it as the base for a new development branch.
- If validation fails, stop and present options — do not merge until resolved or explicitly accepted.
- PR `baseline/teardown-validated` → `main` only when stable and tested.

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
