# Workflow Instructions

## Branch Model

```
feat/* / fix/* / task/* / work/*   ← active development (temporary)
       ↓  appropriate validation tier (see below)
stable                             ← validated on pve-test, ready for pve
       ↓  incremental deploy on pve + smoke test passes
main                               ← current production state
```

| Branch | Meaning | Promotion gate |
|---|---|---|
| `stable` | Validated on pve-test via the appropriate tier for the change class. | See Validation Tiers below. |
| `main` | Deployed to pve; smoke test passed. | Incremental deploy on pve succeeds with no regressions. |

`baseline/teardown-validated` is frozen as a historical marker (last full-teardown-validated state). Do not use as a development base.
`dev/pve-test` is retired (archival only — do not use as a PR target).

See [docs/workflow/branch-model.md](docs/workflow/branch-model.md) for full details.

## Branching

- All work: cut `feat/`, `fix/`, `task/`, or `work/*` from the current working HEAD.
- Validate on the short-lived branch (live runs, tests, populate checks).
- Promote to `stable` once the appropriate validation tier passes on pve-test.
- `stable` is a **promotion target only** — never use it as the base for a new development branch.
- If validation fails, stop and present options — do not merge until resolved or explicitly accepted.
- PR `stable` → `main` only after a successful incremental deploy to pve.
- If the operator explicitly names a merge target, use that exact target and do not silently retarget.

## Validation Tiers

Match validation depth to change risk. A full teardown is required only for high-risk structural changes, not every promotion.

| Change class | Minimum validation |
|---|---|
| Python logic with unit tests | `python3 -m unittest discover -s . -p "test_*.py"` |
| Ansible comment or nosonar changes | `ansible-playbook --syntax-check` on all affected playbooks |
| Ansible task or role changes | `scripts/provision.sh --stack <affected-stack>` on pve-test |
| Terraform / network / SDN / firewall — additive only (new zone/vnet/subnet, new narrowly-scoped cross-zone rule; `terragrunt plan` shows zero changes/deletions to existing resources) | Apply, then `scripts/provision.sh --stack <affected-stack>` against 1–2 existing stacks in adjacent zones to confirm no regression. Full teardown still owed before promotion past `stable`, but not required per iteration. |
| Terraform / network / SDN / firewall — modifying or removing an existing zone, vnet, subnet, or cross-zone rule | Full teardown cycle on pve-test |
| Authentik, Traefik, or cross-stack integration changes | Full teardown cycle on pve-test |

Batch related changes during development and run the appropriate tier.

**Ansible changes are not low-risk even when they appear comment-only.** A `# nosonar` comment placed inside a Jinja `{{ }}` expression block or a `content: |` env file block becomes runtime-evaluated content that can silently break deployments. Always run `--syntax-check` on the affected playbooks after any Ansible edit, no matter how trivial it looks. See `docs/teardown-test/lessons-learned.md` §12–13 for specific failure modes.

## Commits and Issues

- After a fix is verified (tests pass, playbook runs clean), commit and close the issue immediately — do not wait to be asked
- Commit with `Closes #N` in the message
- Run `gh issue close N --comment "Fixed in commit <sha>"` after committing
- Do both before reporting back

## Security Scanning

- **snyk**: `/home/steve/.local/bin/snyk iac test terraform/` — Terraform IaC only, not Ansible
- **sonar-scanner**: `source .env && sonar-scanner` — config in `sonar-project.properties`

## Documentation Workspace Pattern

- For planning or refactor work under `docs/`, keep transient handoffs, prompts,
  transcripts, logs, approval packets, and scratch notes under a local ignored
  `docs/<workspace>/artifacts/` directory.
- Do not create new tracked `handoffs/`, `evidence/`, `reports/`, or `prompts/`
  directories under `docs/`.
- Summarize durable conclusions back into tracked docs such as `README.md`,
  `current-state.md`, `plan.md`, or `runbook.md`.
- Clean up stale `artifacts/` contents as the plan progresses and at closeout.
- See `docs/workflow/documentation-workspaces.md` for the canonical rule.

## Production Credential Controls

Production access is strictly controlled and defaults to read-only. There
is more than one production-trust Proxmox node — see Production Nodes below —
but every node goes through the same controls, not a bespoke copy per node.

### Production Nodes

Declared in `terraform/PRODUCTION_NODES` (one node name per line) — currently
`pve` and `pve-framework`. This file is the single source of truth for
"which nodes are production"; both `./with-secrets`'s safety rail and the
`with-secrets-prod*` wrappers read it. Adding a node here, plus its own
`.env.<node>` and `terraform/secrets.<node>.enc.yaml`, is what's required to
bring a new node under production control — never hardcode a node name into
new automation. See `docs/framework-integration/decisions.md` Decision 6.

### Secrets Storage

- **Common secrets:** `terraform/secrets.common.enc.yaml` — every secret
  that's genuinely the same everywhere (the large majority); loaded by
  `./with-secrets` and merged into every `with-secrets-prod*` wrapper too
- **Per-node secrets:** `terraform/secrets.<node>.enc.yaml` — only secrets
  structurally tied to that node's own Proxmox API identity (its
  read-only/Terraform tokens, its LXC root password); loaded only by that
  node's `with-secrets-prod*` wrapper, merged on top of common
- All are encrypted with SOPS (age key at `~/.config/sops/age/keys.txt`).
  See `docs/reference/secrets-management.md` for the full split and where a
  new secret belongs.

### Wrappers

- **`./with-secrets`** (development, pve-test-vm default)
  - Use for all normal infrastructure work
  - Fails if targeting any node listed in `terraform/PRODUCTION_NODES`
    without explicit `ALLOW_PVE=true`
  - Cannot load production secrets (separate per-node files)

- **`./with-secrets-prod`** / **`./with-secrets-prod-framework`** (production, strict controls)
  - Thin per-node entrypoints over the shared `scripts/with-secrets-prod-lib.sh`
    engine — one wrapper file per production node, not duplicated logic
  - Use only for intentional production workflows against that node
  - Enforces `TF_VAR_proxmox_node=<that node>`
  - Loads that node's production secrets ONLY
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
   - target environment (which production node, e.g. `pve` or `pve-framework`)
   - whether mutating or read-only
   - exact objects to be changed
   - specific commands
   - explicit out-of-scope items

2. **Operator Approval** — Operator says in chat: "Proceed" or similar

3. **Execute With Approval** — Operator sets and runs:
   ```bash
   export TASK_APPROVAL="task-name-from-docs"
   ./with-secrets-prod <command>              # node = pve
   ./with-secrets-prod-framework <command>    # node = pve-framework
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
- **Read-only by default:** Use the target node's `with-secrets-prod*` wrapper for inspection and planning
- **Conservative classifier:** If a command is ambiguous, treat it as mutating
- **Preflight + summary:** Always report before and after production access to the operator

### Related Documentation

- [Production Credentials Reference](/home/steve/git/proxmox-homelab/docs/reference/production-credentials.md)
- [Task 01: Production Credential Controls](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/01-credential-controls.md)
