# Workflow Instructions

## Branch Model

```
feat/* / fix/* / task/* / work/*   ← active development (temporary)
       ↓  appropriate validation tier (see below)
stable                             ← validated per its tier, ready for pve
       ↓  incremental deploy on pve + smoke test passes
main                               ← current production state
```

**`pve-test-vm` is reserved for structural/high-blast-radius validation only**
(Terraform/SDN/firewall zone work, full teardown cycles — see Validation
Tiers below). It is no longer the default validation target for routine
changes. Everything else — Ansible task/role changes, Authentik/Traefik/
Harbor config, and similar app-level work — validates directly against
`pve`, through the normal production approval flow (see Production
Credential Controls), not on pve-test-vm first.

| Branch | Meaning | Promotion gate |
|---|---|---|
| `stable` | Validated per the appropriate tier for the change class — `pve-test-vm` for structural/high-blast-radius changes, `pve` directly (under the production approval flow) for everything else. | See Validation Tiers below. |
| `main` | Deployed to pve; smoke test passed. | Incremental deploy on pve succeeds with no regressions. |

`baseline/teardown-validated` is frozen as a historical marker (last full-teardown-validated state). Do not use as a development base.
`dev/pve-test` is retired (archival only — do not use as a PR target).

Do not develop directly on `stable` or `main`. All active work happens on short-lived `feat/`, `fix/`, `task/`, or `work/*` branches cut from the current working HEAD.

See [docs/workflow/branch-model.md](docs/workflow/branch-model.md) for full details.

## Branching

- All work: cut `feat/`, `fix/`, `task/`, or `work/*` from the current working HEAD.
- Validate on the short-lived branch (live runs, tests, populate checks).
- Promote to `stable` once the appropriate validation tier passes — on `pve-test-vm` for structural/high-blast-radius changes, directly on `pve` (under the production approval flow) for everything else.
- `stable` is a **promotion target only** — never use it as the base for a new development branch.
- If validation fails, stop and present options — do not merge until resolved or explicitly accepted.
- PR `stable` → `main` only after a successful incremental deploy to pve.
- If the operator explicitly names a merge target, use that exact target and do not silently retarget.

## Validation Tiers

Match validation depth to change risk. A full teardown is required only for high-risk structural changes, not every promotion.

**`pve-test-vm` is reserved for the structural/high-blast-radius tiers below**
(Terraform/SDN/firewall zone work, full teardown cycles). Every other tier
validates directly against `pve`, via `./with-secrets-prod`/
`./with-secrets-prod-framework` under the normal production approval flow
(Preflight Summary → Operator Approval → `TASK_APPROVAL` → execute — see
Production Credential Controls). `scripts/teardown-deploy-test.sh` is
pve-test-vm-only (it self-wraps `with-secrets`, not `with-secrets-prod`) and
does not apply to tiers validated on `pve`.

| Change class | Minimum validation |
|---|---|
| Python logic with unit tests | `python3 -m unittest discover -s . -p "test_*.py"` |
| Ansible comment or nosonar changes | `ansible-playbook --syntax-check` on all affected playbooks |
| Ansible task or role changes | `scripts/provision.sh --stack <affected-stack>` directly on `pve`, under the production approval flow |
| Terraform / network / SDN / firewall — additive only (new zone/vnet/subnet, new narrowly-scoped cross-zone rule; `terragrunt plan` shows zero changes/deletions to existing resources) | On `pve-test-vm`: apply, then `scripts/provision.sh --stack <affected-stack>` against 1–2 existing stacks in adjacent zones to confirm no regression. Full teardown still owed before promotion past `stable`, but not required per iteration. |
| Terraform / network / SDN / firewall — modifying or removing an existing zone, vnet, subnet, or cross-zone rule | Full teardown cycle on pve-test-vm |
| Authentik, Traefik, or other changes where an outage would break login or routing for stacks that are already running (not just new deploys) | Redeploy the changed stack plus a small, explicit sample of its real consumers directly on `pve`, under the production approval flow, and check their actual login/routing paths (targeted `scripts/provision.sh --stack <name>` calls via `./with-secrets-prod`/`./with-secrets-prod-framework`, in dependency order). A full teardown cycle (`scripts/teardown-deploy-test.sh cycle` / `destroy`, always on pve-test-vm) is never the default — run one only when the operator explicitly asks for it by name. |
| Harbor (or another shared internal registry/cache) — version bump or config change that doesn't alter what consumers pull or push against | `scripts/provision.sh --stack harbor-stack` directly on `pve`, under the production approval flow, then re-run `scripts/provision.sh --stack <name>` for 1–2 stacks that actually pull through it (cover at least one native-adapter project and one proxy-cache project) to confirm no regression. Full teardown not required — unlike Authentik/Traefik, a Harbor outage doesn't break stacks that are already running (their images are already resident locally); it only blocks new pulls, deploys, and scans. |

Batch related changes during development and run the appropriate tier.

**Ansible changes are not low-risk even when they appear comment-only.** A `# nosonar` comment placed inside a Jinja `{{ }}` expression block or a `content: |` env file block becomes runtime-evaluated content that can silently break deployments. Always run `--syntax-check` on the affected playbooks after any Ansible edit, no matter how trivial it looks. See `docs/teardown-test/lessons-learned.md` §12–13 for specific failure modes.

## Commits and Issues

- After a fix is verified (tests pass, playbook runs clean), commit and close the issue immediately — do not wait to be asked
- Commit with `Closes #N` in the message
- Run `gh issue close N --comment "Fixed in commit <sha>"` after committing
- Do both before reporting back

## Security Scanning

- **snyk**: `/home/steve/.local/bin/snyk iac test terraform/` — Terraform IaC only, not Ansible
- **sonar-scanner**: `./with-secrets /home/steve/.local/bin/sonar-scanner` — config in `sonar-project.properties`; `SONAR_TOKEN` is SOPS-backed, not in plain `.env`, so it must run through `./with-secrets`

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

## Workspace Operating Patterns

- Use `./with-secrets <command>` for commands that need credentials. It injects non-secret local config plus SOPS-backed secrets from `terraform/secrets.common.enc.yaml`; do not rely on `source .env` for secret-bearing workflows.
- Treat `.env` as gitignored non-secret config only: hostnames, node names, IPs, usernames, and workspace names. Real passwords, tokens, API keys, and service secrets belong in `terraform/secrets.common.enc.yaml` via SOPS.
- New Terraform secrets in SOPS should use the exact `TF_VAR_*` environment variable name Terraform expects, such as `TF_VAR_lxc_password` or `TF_VAR_pm_api_token_secret`, rather than adding a separate mapping layer.
- Edit SOPS secrets with `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.common.enc.yaml`. Do not decrypt secrets into plaintext files or commit private age keys.
- GitHub Actions secrets are for CI-only values and CI SOPS decryption. Local infrastructure automation should prefer SOPS plus `with-secrets`.
- Generated files under `terraform/lxc/.generated/` are runtime output, not source of truth. Regenerate them from manifests immediately before publish or validation.
- Prefer dry-run-first workflows for reconcilers and edge changes. Use full baseline reconciler checks after applies when validating stack-owned edge state.

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
| `technitium-stack` | Docker Compose (Technitium DNS) | **The live authoritative DNS** on both `pve` and `pve-test-vm` — MikroTik's zone-delegate rule points here. `dig` query against its IP |
| `dns-stack` | systemd (CoreDNS) | **Rollback-only, not the active delegate target** since the cutover documented in `docs/dns-refactor/README.md` — do not assume this is live DNS just because it's deployed. `dig` query against the DNS container IP if you do need to check it |
| `step-ca-stack` | systemd (step-ca) | HTTPS GET to `/acme/acme/directory` |
| `ci-runner-01` | systemd (GitHub Actions runner) | Check systemd unit `actions.runner.*.service` |
| `harbor-stack` | Docker Compose | `curl` to registry API or health endpoint |
| `authentik-stack` | Docker Compose | `curl` to `/-/health/live/` |
| `proxy-stack` | Docker Compose (Traefik) | `curl` to Traefik ingress |
| `monitoring-stack` | Docker Compose | `curl` to Grafana and VictoriaMetrics |
| `netbox-stack` | Docker Compose | `curl` to NetBox HTTP port |
| `portainer-stack` | Docker Compose | `curl` to Portainer API `/api/system/status` |

## Execution Guardrails

- Before any `terragrunt apply` or deployment validation run, confirm the target matches the change's validation tier (see Validation Tiers): for structural/high-blast-radius tiers, `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` must return `pve-test-vm`; for every other tier, the run goes through `./with-secrets-prod`/`./with-secrets-prod-framework` against `pve`/`pve-framework` under the production approval flow instead. Either way, stop and treat a mismatch between the intended target and the actual one as a targeting error.
- For direct Ansible validation against inline inventories like `-i '10.57.x.x,'`, always pass `-u root`; otherwise Ansible can silently fall back to the local workstation username and report misleading SSH failures.
- `pvesh` runs only on a Proxmox node itself; it is not installed on the operator's workstation. For read-only API checks from the workstation, use `./with-secrets` and curl against `${TF_VAR_proxmox_api_url}` with the `PROXMOX_READONLY_TOKEN_ID`/`PROXMOX_READONLY_TOKEN_SECRET` header (`Authorization: PVEAPIToken=<id>=<secret>`), or SSH to the target node and run `pvesh`/`pct list` there.
