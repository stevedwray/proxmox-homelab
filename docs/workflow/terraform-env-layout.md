# Terraform Environment Layout Refactor

**Status:** Not started. Prerequisite: lab (pve) restored and verified.

**Problem:** Two environments (`pve` and `pve-test-vm`) cannot run concurrently
from the same working tree because every stack has exactly one `inventory.yml`
and one `terraform.tfstate`, both written to `terraform/lxc/stacks/<name>/`.
Whichever environment ran Terraform most recently owns both. This caused the
2026-06-23 incident (see `session-handoff-2026-06-23.md`).

**Goal:** Give each environment its own generated files and state so that
pve-test-vm Terraform cannot overwrite pve inventory, and vice-versa.

---

## How it works today

```
terraform/lxc/
  main.tf                        ← shared module
  stacks/
    dns-stack/
      stack.yaml                 ← stack definition (config, committed)
      terragrunt.hcl             ← calls main.tf as source
      terraform.tfstate          ← state (generated, not committed)
      inventory.yml              ← ansible host (generated, not committed)
      network-sdn-vars.yml       ← generated
      network-firewall-vars.yml  ← generated
      network-vnet-firewall-vars.yml  ← generated
```

`stack_dir = dirname(stack_yaml_path)` is a single path. All generated files
land there. The root `terragrunt.hcl` stores state at
`${get_original_terragrunt_dir()}/terraform.tfstate`, which resolves to the
same directory. Running Terraform for pve-test-vm overwrites the pve files.

`provision.sh` is hardcoded to `STACKS_DIR=terraform/lxc/stacks` and finds
everything there.

---

## Target layout

```
terraform/lxc/
  main.tf                        ← unchanged (shared module)
  stacks/
    dns-stack/
      stack.yaml                 ← unchanged (shared config, committed)
      terragrunt.hcl             ← REMOVED (or kept as legacy; see migration)
  environments/
    pve/
      dns-stack/
        terragrunt.hcl           ← NEW (thin, committed)
        terraform.tfstate        ← generated, not committed
        inventory.yml            ← generated, not committed
        network-sdn-vars.yml     ← generated, not committed
        ...
    pve-test-vm/
      dns-stack/
        terragrunt.hcl           ← NEW (thin, committed)
        terraform.tfstate        ← generated, not committed
        inventory.yml            ← generated, not committed
        ...
```

The shared `stack.yaml` stays in `stacks/`. The per-environment `terragrunt.hcl`
points to it. Generated files land in the environment directory, not the shared
stack directory. Environments are fully isolated.

---

## Implementation

### Step 1 — Add `generated_dir` variable to `main.tf`

File: `terraform/lxc/main.tf`

Add a new input variable near the top (after the existing variables):

```hcl
variable "generated_dir" {
  type        = string
  default     = ""
  description = "Directory where generated files (inventory, firewall vars) are written. Defaults to the stack source directory when empty."
}
```

Add a new local derived from it:

```hcl
locals {
  stack_dir   = dirname(var.stack_yaml_path)          # …/stacks/<name>  (read-only source)
  lxc_root    = dirname(dirname(local.stack_dir))     # …/terraform/lxc  (unchanged)
  output_dir  = var.generated_dir != "" ? var.generated_dir : local.stack_dir
  # ... rest of locals unchanged
}
```

Replace every occurrence of `${local.stack_dir}/` in `local_file` filenames
and in null_resource commands with `${local.output_dir}/`:

| Resource | Old | New |
|---|---|---|
| `local_file.ansible_inventory` | `"${local.stack_dir}/inventory.yml"` | `"${local.output_dir}/inventory.yml"` |
| `local_file.network_sdn_vars` | `"${local.stack_dir}/network-sdn-vars.yml"` | `"${local.output_dir}/network-sdn-vars.yml"` |
| `local_file.network_firewall_vars` | `"${local.stack_dir}/network-firewall-vars.yml"` | `"${local.output_dir}/network-firewall-vars.yml"` |
| `local_file.network_vnet_firewall_vars` | `"${local.stack_dir}/network-vnet-firewall-vars.yml"` | `"${local.output_dir}/network-vnet-firewall-vars.yml"` |

The null_resource provisioner commands that pass `-i '${local.stack_dir}/inventory.yml'`
must also change to `${local.output_dir}/inventory.yml`.

Grep to confirm all locations:

```bash
grep -n "stack_dir}/inventory\|stack_dir}/network-" terraform/lxc/main.tf
```

There should be no remaining `stack_dir}/inventory` or `stack_dir}/network-`
references in `local_file` filenames or null_resource commands after the edit.

The `lxc_root` derivation (`dirname(dirname(local.stack_dir))`) is intentionally
unchanged: it is derived from `stack_yaml_path` (the shared source) and must
continue to point to `terraform/lxc/` for peer-stack IP discovery to work.

### Step 2 — Create environment directories and terragrunt.hcl files

For each active stack, create a thin `terragrunt.hcl` in both environment
directories. The file is the same for both environments; the state and generated
files differ because `get_terragrunt_dir()` and `get_original_terragrunt_dir()`
resolve to the leaf directory where the file lives.

**Pattern** (`environments/<env>/<stack>/terragrunt.hcl`):

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

`get_terragrunt_dir()` resolves to `environments/pve/dns-stack/` or
`environments/pve-test-vm/dns-stack/` depending on where Terragrunt runs. The
root `terragrunt.hcl` stores state at `${get_original_terragrunt_dir()}/terraform.tfstate`,
which also resolves to the leaf directory — no change to the root config is needed.

**Active platform stacks to create in both `environments/pve/` and `environments/pve-test-vm/`:**

```
authentik-stack
apt-cacher-stack
dns-stack
harbor-stack
monitoring-stack
netbox-stack
portainer-stack
proxy-stack
step-ca-stack
```

Infrastructure stacks (ci-runner-01, net-build-01, etc.) are node-specific.
Create them only in the environment where they are actually deployed.

You can generate the files with a shell loop:

```bash
for env in pve pve-test-vm; do
  for stack in authentik-stack apt-cacher-stack dns-stack harbor-stack \
               monitoring-stack netbox-stack portainer-stack proxy-stack step-ca-stack; do
    dir="terraform/lxc/environments/${env}/${stack}"
    mkdir -p "$dir"
    cat > "${dir}/terragrunt.hcl" <<'EOF'
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
EOF
  done
done
```

Commit the `environments/` directory (terragrunt.hcl files only — generated
files are gitignored).

### Step 3 — Update `provision.sh`

File: `scripts/provision.sh`

Add a derived `ENV_DIR` constant alongside `STACKS_DIR`:

```bash
STACKS_DIR="${REPO_ROOT}/terraform/lxc/stacks"
ENV_DIR="${REPO_ROOT}/terraform/lxc/environments/${PVE_ENV:-pve}"
```

Change all generated-file lookups from `STACKS_DIR` to `ENV_DIR`:

| Location | Before | After |
|---|---|---|
| Line ~100 `proxy_inventory` | `"${stacks_dir}/proxy-stack/inventory.yml"` | `"${ENV_DIR}/proxy-stack/inventory.yml"` |
| Line ~382 `inventory_file` | `"${STACKS_DIR}/${stack}/inventory.yml"` | `"${ENV_DIR}/${stack}/inventory.yml"` |
| Line ~434 `smoke_script` | `"${STACKS_DIR}/${stack}/smoke-test.sh"` | (smoke scripts stay in `STACKS_DIR` — they are committed config, not generated) |

The `render_stack_ansible_extra_vars` function reads `stack_file` from `STACKS_DIR`
(the shared stack.yaml) — that stays unchanged. The `extra_vars["stack_dir"]` it
emits is the directory containing `stack.yaml`, which is in `STACKS_DIR`. This is
correct: ansible playbooks use `stack_dir` to find committed stack config files
(docker-compose.yml, etc.), not generated files like inventory.

The tier discovery Python block (~line 232) scans `stacks_dir` for `stack.yaml`
entries — that also stays unchanged.

After the edit, grep to confirm no `STACKS_DIR` reference reaches inventory:

```bash
grep -n "STACKS_DIR.*inventory\|stacks_dir.*inventory" scripts/provision.sh
```

Should return empty.

### Step 4 — Migrate existing state

For pve, copy each active stack's `terraform.tfstate` from the old location to
the new environment directory:

```bash
for stack in authentik-stack apt-cacher-stack dns-stack harbor-stack \
             monitoring-stack netbox-stack portainer-stack proxy-stack step-ca-stack; do
  src="terraform/lxc/stacks/${stack}/terraform.tfstate"
  dst="terraform/lxc/environments/pve/${stack}/terraform.tfstate"
  if [[ -f "$src" ]]; then
    cp "$src" "$dst"
    echo "Copied ${stack}"
  else
    echo "SKIP ${stack} (no state file)"
  fi
done
```

For pve-test-vm, the teardown/rebuild workflow regenerates state from scratch, so
no copy is needed — Terraform will create fresh state on the next apply.

Verify the migration for one stack before doing all of them:

```bash
cd terraform/lxc/environments/pve/dns-stack
PVE_ENV=pve ./with-secrets-prod terragrunt plan
```

Expected: no changes (state matches actual resources on pve).

If plan shows resources to create or destroy, the state copy is wrong — do not
proceed with other stacks until resolved.

### Step 5 — Update `.gitignore`

Add generated-file patterns for the environments directory:

```
terraform/lxc/environments/**/terraform.tfstate
terraform/lxc/environments/**/terraform.tfstate.d/
terraform/lxc/environments/**/inventory.yml
terraform/lxc/environments/**/network-sdn-vars.yml
terraform/lxc/environments/**/network-firewall-vars.yml
terraform/lxc/environments/**/network-vnet-firewall-vars.yml
```

Commit only the `terragrunt.hcl` files.

### Step 6 — Remove old terragrunt.hcl files from `stacks/`

Once the environment directories are working, the `terragrunt.hcl` in each
`stacks/<name>/` is no longer needed. Remove them to prevent accidental
double-targeting. The `stack.yaml` stays (it is the shared config source).

```bash
find terraform/lxc/stacks -name terragrunt.hcl \
  -not -path "*/.terragrunt-cache/*" -delete
```

The `stacks/` `terraform.tfstate` files can be left in place (they are gitignored)
or deleted once you have confirmed the environment-directory state is correct:

```bash
find terraform/lxc/stacks -name terraform.tfstate \
  -not -path "*/.terragrunt-cache/*" -delete
```

---

## Validation

After implementation:

```bash
# 1. Plan pve from the new layout — must show no changes
PVE_ENV=pve ./with-secrets-prod terragrunt run-all plan \
  --terragrunt-working-dir terraform/lxc/environments/pve

# 2. Verify provision.sh finds inventory in the right place for each env
PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --stack dns-stack
# Confirm it reads terraform/lxc/environments/pve-test-vm/dns-stack/inventory.yml

# 3. Run pve-test-vm dns-stack Terraform, then confirm pve inventory is untouched
PVE_ENV=pve-test-vm ./with-secrets terragrunt apply \
  --terragrunt-working-dir terraform/lxc/environments/pve-test-vm/dns-stack
grep ansible_host terraform/lxc/environments/pve/dns-stack/inventory.yml
# Must still show 192.168.20.13, not 192.168.20.113
```

---

## What this does NOT change

- `stacks/*/stack.yaml` — shared config, stays where it is
- `main.tf` module logic, variables, and resources — only `output_dir` is added
- Ansible playbooks, roles, templates — none of these reference `stack_dir` directly
- The root `terragrunt.hcl` — `get_original_terragrunt_dir()` already resolves
  to the leaf, so state paths update automatically without touching the config
- Peer-stack IP discovery (`fileset(lxc_root, "stacks/*/stack.yaml")`) — still
  scans the shared stacks directory, unaffected

---

## Effort estimate

- `main.tf` change (Step 1): ~30 min — add variable, change ~8 filename references
- Environment directories (Step 2): ~20 min — shell loop to generate terragrunt.hcl files
- `provision.sh` change (Step 3): ~20 min — 3-4 line changes
- State migration + validation (Step 4-5): ~45 min — copy + plan each stack
- Cleanup (Step 6): ~10 min

Total: roughly 2 hours including validation.

---

## Sequencing with the sprint

This refactor is a prerequisite for confident concurrent environment operation.
It is not a prerequisite for completing the current sprint to stable — the
manual isolation rules from `session-handoff-2026-06-23.md` are sufficient
guards in the short term.

Recommended order:

1. Restore lab (pve) — see `session-handoff-2026-06-23.md` Step 1
2. Complete pve-test-vm platform tier pass and promote to stable → main
3. Do this refactor on a new `task/terraform-env-layout` branch
4. Validate against pve (plan shows no changes)
5. Promote to stable → main
