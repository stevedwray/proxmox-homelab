# Workflow Instructions

## Branch Model

```
work/*, feat/*, fix/*, task/*      ← active development
       ├─→ baseline/teardown-validated  ← pve-test infrastructure foundation known good
       │         ↓  application stacks deploy successfully on top
       │   dev/pve-test                  ← pve-test application deployment known good
       │         ↓  stable and tested
       │        main
       └─→ prod/pve-infra                ← production pve infrastructure/services known good
```

| Branch | Meaning | Promotion gate |
|---|---|---|
| `baseline/teardown-validated` | Full infrastructure teardown and redeploy has been validated from this state. | Run and pass a complete teardown + infrastructure redeploy cycle. |
| `dev/pve-test` | Application stacks deploy successfully on the infrastructure. | Validate application stacks on top of `baseline/teardown-validated`. |
| `prod/pve-infra` | Production-targeted infrastructure and production access flows are validated on `pve`. | Validate the intended production `pve` stacks and operator sign-in paths from the source branch before promotion. |

Do not develop directly in any promotion branch. Active development happens on `work/*` or short-lived `feat/`, `fix/`, `task/` branches.
Promotion merges into a promotion branch are allowed once the corresponding gate is satisfied.
If the operator explicitly names a merge target (`baseline/teardown-validated`, `dev/pve-test`, or `prod/pve-infra`), use that exact target and do not silently retarget.

## Branching

- Infrastructure work: cut `work/*` from the intended stable base branch for that effort, normally `baseline/teardown-validated`; validate through a full teardown + redeploy cycle; promote to `baseline/teardown-validated`.
- Application stack work: cut `feat/`, `fix/`, or `task/` from the intended stable base branch for that effort, normally `baseline/teardown-validated`; validate stacks on top of `baseline/teardown-validated`; promote to `dev/pve-test`.
- Production `pve` infrastructure/service work: cut `work/*` from `prod/pve-infra` once it exists, or from the current production work branch while the promotion is being established; validate on `pve`; promote to `prod/pve-infra`.
- AI tooling / workflow changes: cut `feat/` from the current working HEAD; merge directly to `dev/pve-test` (no infrastructure gate required).
- `dev/pve-test`, `baseline/teardown-validated`, and `prod/pve-infra` are promotion branches. Do not develop directly on them, but do branch from the appropriate one when starting new work.
- Validate in the short-lived branch before merging. If validation fails, stop and present options — do not merge until resolved or explicitly accepted.
- PR `dev/pve-test` → `main` only when stable and tested on the test server.
- After merging to `main`, pull `main` back into `dev/pve-test` to stay in sync.

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

## Script Credential Handling

Some scripts call `./with-secrets` internally; others rely on it being in the environment. Use this table when writing gate commands:

| Script | Credential handling | How to invoke |
|---|---|---|
| `scripts/provision.sh` | None — relies on env vars injected by caller | `./with-secrets scripts/provision.sh --stack <name>` |
| `scripts/rebuild-gate-destroy.sh` | Self-wrapping — calls `${WITH_SECRETS}` internally | `./scripts/rebuild-gate-destroy.sh --execute` |
| `scripts/teardown-deploy-test.sh` | Self-wrapping — calls `with-secrets` internally | `./scripts/teardown-deploy-test.sh <args>` |

For `scripts/teardown-deploy-test.sh cycle`, pass `--approval-packet <path>` by default.
When session context sets `env.disposable: true`, pass `--disposable` and omit `--approval-packet`.

When adding a new script, check whether it calls `${WITH_SECRETS}` or `with-secrets` internally before deciding whether to prefix with `./with-secrets`.

## Stack Service Types

Not all stacks run Docker containers. When writing health/verify gate commands, derive the check from the actual service type — do not assume Docker. Reference the deployment playbook in `terraform/lxc/ansible/playbooks/` to confirm.

| Stack | Service type | Verify approach |
|---|---|---|
| `apt-cacher-stack` | systemd (apt-cacher-ng) | Check systemd unit or HTTP port 3142 |
| `dns-stack` | systemd (CoreDNS) | `dig` query against the DNS container IP |
| `step-ca-stack` | systemd (step-ca) | HTTPS GET to `/acme/acme/directory` |
| `ci-runner-01` | systemd (GitHub Actions runner) | Check systemd unit `actions.runner.*.service` |
| `harbor-stack` | Docker Compose | `curl` to registry API or health endpoint |
| `authentik-stack` | Docker Compose | `curl` to `/-/health/live/` |
| `proxy-stack` | Docker Compose (Traefik) | `curl` to Traefik ingress |
| `monitoring-stack` | Docker Compose | `curl` to Grafana and VictoriaMetrics |
| `netbox-stack` | Docker Compose | `curl` to NetBox HTTP port |
| `portainer-stack` | Docker Compose | `curl` to Portainer API `/api/system/status` |

## Execution Guardrails

- Before any `terragrunt apply` or deployment validation run, verify `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` returns `pve-test`; otherwise stop and treat it as a targeting error.
- For direct Ansible validation against inline inventories like `-i '10.57.x.x,'`, always pass `-u root`; otherwise Ansible can silently fall back to the local workstation username and report misleading SSH failures.
