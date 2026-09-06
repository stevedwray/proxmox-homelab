# Terraform Environment Runtime Isolation

**Status as of June 29, 2026:** Merged to `main` and `stable` as
`fe05636` (`feat(infra): per-environment Terragrunt layout for runtime
isolation (#386)`). Steps 1–5 and 8 are complete. Step 9 (pve state
migration) is partially complete. Steps 6, 7, and 10 remain pending.

| Step | Status |
|------|--------|
| 1. Environment path helpers in provision.sh | ✅ Done |
| 2. Terragrunt entrypoints for pve + pve-test-vm | ✅ Done (24 stacks each) |
| 3. `generated_dir` variable + `output_dir` local in main.tf | ✅ Done |
| 4. provision.sh reads env inventories (with fallback) | ✅ Done |
| 5. Edge generated output scoped to env (reconcile-edge.py) | ✅ Done |
| 6. Root CA scoping (`certs/homelab-root.crt` → env dir) | ⬜ Deferred |
| 7. Legacy script audit and updates | ⬜ Deferred |
| 8. `.gitignore` environment runtime entries | ✅ Done |
| 9. Migrate pve (inventories pre-populated; state migration deferred) | ⚠️ Partial |
| 10. Enable pve-test-vm (fresh apply from env entrypoints) | ⬜ Pending |

**Step 9 note:** `environments/pve/<stack>/inventory.yml` files pre-populated by
direct copy from `stacks/*/inventory.yml` (all confirmed pve base-range IPs). Full
Terraform state migration is deferred because `null_resource.configure_network_sdn_attachment`
has `sdn_vars_file = local_file.network_sdn_vars[0].filename` as a trigger — changing
`output_dir` from `stacks/` to `environments/pve/` would fire the trigger and run
Ansible SDN playbooks on pve unexpectedly. Migration requires targeted `-target` or
`terraform state mv` approach, or waiting until the SDN attachment null_resource is
refactored. The fallback in provision.sh (`stacks/` if env inventory missing) covers
this gap in the interim.

This is the next structural prerequisite for safe parallel work on `pve` and
`pve-test-vm`.

**Problem:** `pve` and `pve-test-vm` shared runtime outputs in one working
tree. A run against one environment could overwrite files later consumed by the
other environment. That was one half of the June 24 production incident; the
other half was environment processing that allowed stale `TF_VAR_lab_*` values
to survive across sessions when the selected env's `LAB_*` values should have
won. This document covers the structural file-path isolation piece:

- `terraform/lxc/stacks/<stack>/terraform.tfstate`
- `terraform/lxc/stacks/<stack>/inventory.yml`
- `terraform/lxc/stacks/<stack>/network-*-vars.yml`
- `terraform/lxc/.generated/traefik/`
- `terraform/lxc/.generated/coredns/`
- `certs/homelab-root.crt`

**Goal:** Shared source inputs, isolated runtime outputs. Work on `pve-test-vm`
must not mutate, overwrite, or reuse generated files for `pve`, and work on
`pve` must not mutate, overwrite, or reuse generated files for `pve-test-vm`.

---

## Current Contamination Paths

### Terraform and Terragrunt

The root Terragrunt config stores state beside the active stack config:

```hcl
path          = "${get_original_terragrunt_dir()}/terraform.tfstate"
workspace_dir = "${get_original_terragrunt_dir()}/terraform.tfstate.d"
```

Today the runnable Terragrunt files live under `terraform/lxc/stacks/<stack>/`,
so both environments compete for the same state path.

Terraform also derives `local.stack_dir = dirname(var.stack_yaml_path)` and
writes generated handoff files there:

- `inventory.yml`
- `network-sdn-vars.yml`
- `network-firewall-vars.yml`
- `network-vnet-firewall-vars.yml`

### Provisioning

`scripts/provision.sh` discovers stack source config under
`terraform/lxc/stacks`, which is correct, but it also reads generated inventory
from the same shared directory. That makes a stale or overwritten inventory a
live deployment target.

### Edge Output

Edge renderers default to shared generated output:

- `terraform/lxc/.generated/traefik/`
- `terraform/lxc/.generated/coredns/coredns-lab.zone`

If those files were last rendered for `pve-test-vm`, a later `pve` proxy or DNS
deploy can publish test routes or test zones to production.

### Root CA

`certs/homelab-root.crt` is a single global file. Rebuilding `pve-test-vm`
step-ca can replace it with the test root, and a later `pve` provision can
install that wrong root CA into production containers.

---

## Target Layout

Committed source config stays shared:

```text
terraform/lxc/
  main.tf
  stacks/
    <stack>/
      stack.yaml
      edge.yaml
      docker-compose.yml
      smoke-test.sh
      STACK_CONTRACT.md
```

Generated runtime state moves under environment roots:

```text
terraform/lxc/
  environments/
    pve/
      <stack>/
        terragrunt.hcl
        terraform.tfstate
        terraform.tfstate.d/
        inventory.yml
        network-sdn-vars.yml
        network-firewall-vars.yml
        network-vnet-firewall-vars.yml
      .generated/
        traefik/
        coredns/
          coredns-lab.zone
      certs/
        homelab-root.crt

    pve-test-vm/
      <stack>/
        terragrunt.hcl
        terraform.tfstate
        terraform.tfstate.d/
        inventory.yml
        network-sdn-vars.yml
        network-firewall-vars.yml
        network-vnet-firewall-vars.yml
      .generated/
        traefik/
        coredns/
          coredns-lab.zone
      certs/
        homelab-root.crt
```

Only thin environment Terragrunt files are committed under
`terraform/lxc/environments/<env>/<stack>/`. State, inventories, network vars,
edge render output, and certs are generated and gitignored.

---

## Design Rules

- `terraform/lxc/stacks/` is source-of-truth config only.
- `terraform/lxc/environments/<env>/` is runtime output for exactly one
  environment.
- No mutating command may silently fall back to `stacks/*/inventory.yml`.
- `PVE_ENV` must be explicit for mutating Terraform, Terragrunt, Ansible,
  provision, edge render, and rebuild commands.
- `PVE_ENV` and `TF_VAR_proxmox_node` must agree before any apply or deploy.
- Production commands must continue to use `./with-secrets-prod`; test commands
  must use `PVE_ENV=pve-test-vm ./with-secrets`.
- Shared `.generated/` and global `certs/homelab-root.crt` are legacy paths
  only after this refactor. New code should not write or consume them.

---

## Implementation Plan

### Step 1 - Add Environment Path Helpers

Create one convention for runtime paths:

```text
ENV_ROOT=terraform/lxc/environments/${PVE_ENV}
ENV_STACK_DIR=${ENV_ROOT}/${stack}
ENV_GENERATED_DIR=${ENV_ROOT}/.generated
ENV_CERT_DIR=${ENV_ROOT}/certs
```

Scripts should derive these paths once and pass them through explicitly. Avoid
ad hoc recomputation in individual functions.

### Step 2 - Move Runnable Terragrunt Entrypoints

For each stack that can run in an environment, create:

```text
terraform/lxc/environments/<env>/<stack>/terragrunt.hcl
```

Pattern:

```hcl
include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "${get_repo_root()}/terraform/lxc//"
}

inputs = {
  stack_name      = basename(get_terragrunt_dir())
  stack_yaml_path = "${get_repo_root()}/terraform/lxc/stacks/${basename(get_terragrunt_dir())}/stack.yaml"
  generated_dir   = get_terragrunt_dir()
}
```

Running Terragrunt from `environments/<env>/<stack>` makes local state
environment-scoped because the existing root config uses
`get_original_terragrunt_dir()`.

Do not remove the old `stacks/<stack>/terragrunt.hcl` files until pve state has
been migrated and verified.

### Step 3 - Make Terraform Generated Files Environment-Scoped

Add an input to `terraform/lxc/main.tf`:

```hcl
variable "generated_dir" {
  type        = string
  default     = ""
  description = "Directory where generated runtime files are written. Defaults to the stack source directory only for legacy compatibility."
}
```

Add:

```hcl
locals {
  stack_dir  = dirname(var.stack_yaml_path)
  lxc_root   = dirname(dirname(local.stack_dir))
  output_dir = var.generated_dir != "" ? var.generated_dir : local.stack_dir
}
```

Then change generated-file writes and local-exec references from
`local.stack_dir` to `local.output_dir` for:

- `inventory.yml`
- `network-sdn-vars.yml`
- `network-firewall-vars.yml`
- `network-vnet-firewall-vars.yml`

Keep `local.stack_dir` for committed stack assets only.

### Step 4 - Update Provisioning to Read Env Inventories

Update `scripts/provision.sh` so stack discovery stays source-based:

```bash
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"
```

but generated runtime paths are environment-based:

```bash
ENV_ROOT="${REPO_ROOT}/terraform/lxc/environments/${PVE_ENV:?PVE_ENV is required}"
ENV_GENERATED_DIR="${ENV_ROOT}/.generated"
ENV_CERT_DIR="${ENV_ROOT}/certs"
```

Change inventory lookups to:

```bash
"${ENV_ROOT}/${stack}/inventory.yml"
```

This applies to:

- normal stack provisioning
- proxy inventory during edge reconcile
- Portainer environment registration
- any helper that shells out to `ansible-playbook -i`

Smoke tests and compose files remain under `STACKS_DIR` because they are
committed source assets, not generated runtime files.

### Step 5 - Scope Edge Generated Output

Change render and reconcile defaults from shared `.generated` to the active
environment generated directory.

Required behavior:

- `render-edge-traefik.py` writes to
  `terraform/lxc/environments/${PVE_ENV}/.generated/traefik/`
- `render-edge-coredns.py` writes to
  `terraform/lxc/environments/${PVE_ENV}/.generated/coredns/coredns-lab.zone`
- `reconcile-edge.py` uses the same environment output paths
- `deploy-proxy-stack.yml` receives `traefik_generated_source_dir` from the
  active environment
- `deploy-coredns.yml` receives `coredns_generated_zone_src` from the active
  environment

Keep explicit CLI flags for unusual cases, but default behavior must be
environment-scoped.

### Step 6 - Scope Root CA Files

Replace the global local root CA path with:

```text
terraform/lxc/environments/<env>/certs/homelab-root.crt
```

Update callers that currently reference `certs/homelab-root.crt`:

- `deploy-step-ca.yml`
- `trust-homelab-ca.yml`
- `lxc_base`
- step-ca smoke test
- teardown/rebuild harness
- any curl or `step ca health` checks that use the local root

Pass the active cert path as an Ansible variable or environment variable. Do not
let playbooks discover a global cert path implicitly.

### Step 7 - Update Legacy Script Consumers

Search for direct consumers of shared stack inventories and generated paths:

```bash
rg -n "stacks/.*/inventory.yml|stacks/\\$\\{.*\\}/inventory.yml|\\.generated/|certs/homelab-root.crt|terraform.tfstate.d" scripts terraform/lxc
```

Update active scripts to use the environment runtime root. Mark obsolete phase
scripts as legacy if they are no longer safe to run.

Known consumers to review:

- `scripts/teardown-deploy-test.sh`
- `scripts/rebuild-gate-destroy.sh`
- `scripts/deploy-phase-04*.sh`
- `terraform/lxc/validate-*.sh`
- `scripts/resize-lxc-mount.sh`
- `scripts/test-docker-mount-resize.sh`

### Step 8 - Update `.gitignore`

Add environment runtime ignores:

```gitignore
terraform/lxc/environments/**/terraform.tfstate
terraform/lxc/environments/**/terraform.tfstate.*
terraform/lxc/environments/**/terraform.tfstate.d/
terraform/lxc/environments/**/inventory.yml
terraform/lxc/environments/**/inventory.generated.yml
terraform/lxc/environments/**/network-*-vars.yml
terraform/lxc/environments/**/.generated/
terraform/lxc/environments/**/certs/
```

Keep old stack-dir generated ignores during the transition.

### Step 9 - Migrate pve First

Production migration is the safety gate.

1. Create `terraform/lxc/environments/pve/<stack>/terragrunt.hcl`.
2. Copy existing pve state from `terraform/lxc/stacks/<stack>/terraform.tfstate`
   to `terraform/lxc/environments/pve/<stack>/terraform.tfstate`.
3. Run pve plans from the new layout and require no creates or destroys.
4. Generate pve inventories into `environments/pve/<stack>/`.
5. Run a targeted pve provision only after the inventory IPs are confirmed to be
   base-range pve addresses.

Use repo-root commands so wrappers resolve correctly:

```bash
PVE_ENV=pve ./with-secrets-prod terragrunt run-all plan \
  --terragrunt-working-dir terraform/lxc/environments/pve
```

If any pve plan wants to create or destroy existing production containers, stop.
Do not continue to pve-test-vm until production state migration is understood.

### Step 10 - Enable pve-test-vm

After pve is no-op from the new layout:

1. Create `terraform/lxc/environments/pve-test-vm/<stack>/terragrunt.hcl`.
2. Run a low-risk pve-test-vm stack from the new layout.
3. Confirm all generated files land under
   `terraform/lxc/environments/pve-test-vm/`.
4. Confirm `terraform/lxc/environments/pve/` does not change.
5. Run the appropriate pve-test-vm validation tier.

---

## Validation Proof

The refactor is complete only when these checks pass:

1. `pve` plan from `terraform/lxc/environments/pve` is no-op.
2. `pve-test-vm` apply/provision writes only under
   `terraform/lxc/environments/pve-test-vm`.
3. `pve-test-vm` apply/provision does not change anything under
   `terraform/lxc/environments/pve`.
4. `pve` provision reads inventories only from `environments/pve`.
5. `pve-test-vm` provision reads inventories only from `environments/pve-test-vm`.
6. No active script writes to shared `terraform/lxc/.generated/`.
7. No active playbook or smoke test reads global `certs/homelab-root.crt`.
8. Shared `terraform/lxc/stacks/*/inventory.yml` is no longer a deployment input.
9. Direct searches for legacy runtime paths are either empty or documented as
   legacy-only:

```bash
rg -n "stacks/.*/inventory.yml|\\.generated/|certs/homelab-root.crt|terraform.tfstate.d" scripts terraform/lxc
```

10. A final pve smoke test confirms production still targets pve base IPs.

---

## What Remains Shared

These are source inputs and should remain shared:

- `terraform/lxc/main.tf`
- `terraform/lxc/stacks/*/stack.yaml`
- `terraform/lxc/stacks/*/edge.yaml`
- stack compose/config files
- smoke-test scripts
- Ansible playbooks and roles
- docs and stack contracts

Environment-specific differences should come from `.env.<env>`, SOPS secrets,
and generated runtime outputs under `terraform/lxc/environments/<env>/`.

---

## Operational Guidance Until Complete

Until environment runtime isolation is implemented, safest practice is one
worktree per environment:

- use one checkout for pve production operations
- use a separate checkout for pve-test-vm rebuild and validation work
- do not alternate pve and pve-test-vm Terraform/provision runs in the same
  checkout without re-verifying inventories, generated edge files, and root CA
- **always drive deploys through `scripts/provision.sh --stack <name>`**
  (with `./with-secrets` or `./with-secrets-prod` and the right `PVE_ENV`),
  never a hand-typed `ansible-playbook -i <path>` call. `provision.sh`
  resolves `terraform/lxc/environments/<env>/<stack>/inventory.yml` first
  and runs `assert_inventory_matches_env()` as a guard; a manual invocation
  gets neither, even for a stack (like `proxy-stack`) that's already fully
  migrated to the per-environment layout. See the incident below for what
  bypassing it costs.

This is a mitigation only. The target state is structural isolation in one repo.

### Incident: 2026-08-16, prod-intended deploy landed on pve-test-vm

While upgrading `proxy-stack` (Traefik) on `pve`, a hand-typed
`ansible-playbook -i terraform/lxc/stacks/proxy-stack/inventory.yml ...`
call was used instead of `scripts/provision.sh`. That path is the stale,
gitignored, non-environment-scoped fallback file (last written by whichever
environment's Terraform ran most recently in that checkout) — not
`terraform/lxc/environments/pve/proxy-stack/inventory.yml`, which already
existed and was correct. The deploy ran with `pve` secrets/domain but
against pve-test-vm's real host, overwriting its Docker registry trust,
full Traefik dynamic router table, and ACME resolvers with `pve`'s values.
Real DNS-01 challenges were attempted against the production Cloudflare
zone for two hostnames using the shared `CF_DNS_API_TOKEN` (both failed
validation; 4 stale `_acme-challenge` TXT records were left behind and
required manual cleanup via the Cloudflare API — `dig` against public
resolvers lagged the actual zone state, so confirm cleanup via the
Cloudflare API directly, not `dig`), and 11 real certificates were issued
by production's step-ca for production hostnames, left inert in
pve-test-vm's `acme.json` (step-ca is internal-only; no public trust/CT-log
exposure). Both environments were fully restored and re-verified after the
fact. `proxy-stack` was already on the per-environment layout — the
guardrail (`assert_inventory_matches_env()`) that would have caught this
was simply never invoked, because `provision.sh` itself was bypassed.

Full incident writeup: `feedback_env_isolation_rules` in the operator's
Claude Code memory (Recurrence, 2026-08-16).

---

## Effort Estimate

- Terraform/Terragrunt environment layout: 2-3 hours
- `provision.sh` environment runtime paths: 1-2 hours
- edge generated output scoping: 1-2 hours
- root CA scoping through Ansible/smoke tests: 2-3 hours
- legacy script audit and updates: 2-4 hours
- pve state migration and no-op validation: 1-2 hours
- pve-test-vm validation: depends on live stack behavior; expect one focused
  validation session

Total: roughly 1-2 working days including validation, assuming no pve state
drift.
