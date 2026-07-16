# Workflow Instructions

## Branch Model

```
feat/* / fix/* / task/* / work/*   ← active development (temporary)
       ↓  appropriate validation tier (see below)
stable                             ← validated on pve-test-vm, ready for pve
       ↓  incremental deploy on pve + smoke test passes
main                               ← current production state
```

| Branch | Meaning | Promotion gate |
|---|---|---|
| `stable` | Validated on pve-test-vm, cleared for incremental deploy to pve. | Appropriate validation tier for the change class. |
| `main` | Deployed to pve; smoke test passed. | Incremental deploy on pve succeeds with no regressions. |

`dev/pve-test` is retired (archival only — do not use as a PR target).
`baseline/teardown-validated` is frozen as a historical marker — do not use as a development base or PR target.

Do not develop directly on `stable` or `main`. All active work happens on short-lived `feat/`, `fix/`, `task/`, or `work/*` branches cut from the current working HEAD.
If the operator explicitly names a merge target, use that exact target and do not silently retarget.

## Branching

- All work: cut `feat/`, `fix/`, `task/`, or `work/*` from the current working HEAD.
- Validate on the short-lived branch (live runs, tests, syntax checks).
- Promote to `stable` once the appropriate validation tier passes on pve-test-vm.
- `stable` is a **promotion target only** — never use it as the base for a new development branch.
- If validation fails, stop and present options — do not merge until resolved or explicitly accepted.
- PR `stable` → `main` only after a successful incremental deploy to pve.

## Validation Tiers

Match validation depth to change risk. Run the minimum required tier.

| Change class | Minimum validation before promoting to `stable` |
|---|---|
| Python logic with unit tests | `python3 -m unittest discover -s . -p "test_*.py"` |
| Ansible comment or nosonar changes | `ansible-playbook --syntax-check` on affected playbooks |
| Ansible task or role changes | `scripts/provision.sh --stack <affected>` on pve-test-vm |
| Terraform / network / SDN / firewall | Full teardown cycle on pve-test-vm |
| Authentik, Traefik, or cross-stack integration changes | Full teardown cycle on pve-test-vm |

A full teardown cycle is **not required for every promotion** — only for high-risk structural changes.

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

- Use `./with-secrets <command>` for commands that need credentials. It injects non-secret local config plus SOPS-backed secrets from `terraform/secrets.common.enc.yaml`; do not rely on `source .env` for secret-bearing workflows.
- Treat `.env` as gitignored non-secret config only: hostnames, node names, IPs, usernames, and workspace names. Real passwords, tokens, API keys, and service secrets belong in `terraform/secrets.common.enc.yaml` via SOPS.
- New Terraform secrets in SOPS should use the exact `TF_VAR_*` environment variable name Terraform expects, such as `TF_VAR_lxc_password` or `TF_VAR_pm_api_token_secret`, rather than adding a separate mapping layer.
- Edit SOPS secrets with `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.common.enc.yaml`. Do not decrypt secrets into plaintext files or commit private age keys.
- `with-secrets` defaults to the `pve-test-vm` workflow and refuses `pve` targets unless `ALLOW_PVE=true` is explicitly set for intentional production work.
- GitHub Actions secrets are for CI-only values and CI SOPS decryption. Local infrastructure automation should prefer SOPS plus `with-secrets`.
- Generated files under `terraform/lxc/.generated/` are runtime output, not source of truth. Regenerate them from manifests immediately before publish or validation.
- Prefer dry-run-first workflows for reconcilers and edge changes. Use full baseline reconciler checks after applies when validating stack-owned edge state.
- For planning and refactor work under `docs/`, keep transient handoffs, prompts, transcripts, logs, approval packets, and scratch notes under a local ignored `docs/<workspace>/artifacts/` directory. Do not create new tracked `handoffs/`, `evidence/`, `reports/`, or `prompts/` trees under `docs/`.
- Keep runtime evidence, logs, backups, and large snapshots under ignored timestamped evidence directories; summarize results in tracked docs instead of committing bulky artifacts or secrets.
- When temporary material becomes durable, fold the conclusion back into tracked docs such as `README.md`, `current-state.md`, `plan.md`, or `runbook.md`, then clean up stale artifact contents.
- See `docs/workflow/documentation-workspaces.md` for the canonical workspace pattern.
