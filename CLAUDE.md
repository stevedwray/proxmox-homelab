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

- **snyk**: `/home/steve/.local/bin/snyk iac test terraform/` — Terraform IaC only, not Ansible
- **sonar-scanner**: `source .env && sonar-scanner` — config in `sonar-project.properties`

## Production Credential Controls

Production (`pve`) access is strictly controlled and defaults to read-only.

### Secrets Storage

- **Dev secrets:** `terraform/secrets.enc.yaml` — loaded by `./with-secrets`
- **Prod secrets:** `terraform/secrets.pve.enc.yaml` — loaded by `./with-secrets-prod` only
- Both are encrypted with SOPS (age key at `~/.config/sops/age/keys.txt`)

### Wrappers

- **`./with-secrets`** (development, pve-test default)
  - Use for all normal infrastructure work
  - Fails if attempting `pve` without explicit `ALLOW_PVE=true`
  - Cannot load production secrets (separate file)

- **`./with-secrets-prod`** (production, strict controls)
  - Use only for intentional production workflows
  - Enforces `TF_VAR_proxmox_node=pve`
  - Loads production secrets ONLY
  - Allows only a narrow read-only command set without approval
  - Blocks mutating or ambiguous commands unless `TASK_APPROVAL` is set

### Command Classification

**Read-only (allowed by default):**
- `pct list`, `qm list`, `pvesm status`, `pvesh get`
- `terragrunt plan`, `terragrunt validate`, `terragrunt show`, `terragrunt output`
- `terraform plan`, `terraform validate`, `terraform version`
- `dig`, `ping`, `ansible-inventory`

**Mutating (blocked without explicit approval):**
- `terragrunt apply`, `terraform apply`
- `pct create`, `pct destroy`, `pct set`, `qm create`, `qm destroy`
- SDN/firewall/storage changes
- Service deployments, migrations, container control on production
- Ambiguous tools like `ssh`, `scp`, `curl`, and `ansible-playbook`

### Approval Flow For Production Mutations

1. **Preflight Summary** — Session reports to operator:
   - target environment (pve)
   - whether mutating or read-only
   - exact objects to be changed
   - specific commands
   - explicit out-of-scope items

2. **Operator Approval** — Operator says in chat: "Proceed" or similar

3. **Execute With Approval** — Operator sets and runs:
   ```bash
   export TASK_APPROVAL="task-name-from-docs"
   ./with-secrets-prod <command>
   ```
   This acknowledges an approval already given in chat; the wrapper cannot
   verify chat history by itself.

4. **After-Action Summary** — Session reports to operator:
   - what changed
   - success/failure
   - confirmation state matches expectations
   - follow-up actions needed

### Production Session Rules

- **Default-deny:** Production mutations are blocked until explicit approval
- **Per-task:** Each distinct task requires new approval (no standing blanket approval)
- **Chat-based:** Approval is recorded in the session; no approval packet files
- **Scoped:** Only run commands required for the named task; forbid unrelated changes
- **Read-only by default:** Use `./with-secrets-prod` for inspection and planning
- **Conservative classifier:** If a command is ambiguous, treat it as mutating
- **Preflight + summary:** Always report before and after production access to the operator

### Related Documentation

- [Production Credentials Reference](/home/steve/git/proxmox-homelab/docs/reference/production-credentials.md)
- [Task 01: Production Credential Controls](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/01-credential-controls.md)
