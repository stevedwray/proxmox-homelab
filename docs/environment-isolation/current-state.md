# Current State — Per-Environment Terragrunt Layout

## How the working pattern works (25 stacks, e.g. `dns-stack`)

Each environment gets its own Terragrunt directory under
`terraform/lxc/environments/<env>/<stack>/`, containing only a
`terragrunt.hcl`:

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

The critical field is `generated_dir = get_terragrunt_dir()`: it tells the
shared Terraform module (`terraform/lxc//`, one copy for every stack) to
write its generated `inventory.yml`, `.terraform.lock.hcl`, and state
**into this environment-specific directory**, not back into the shared
`terraform/lxc/stacks/<stack>/` location. `stack.yaml` itself (resource
sizing, `network:` zone, `ansible_playbook`, etc.) stays a single shared
file under `stacks/<stack>/` — only the *generated, environment-specific*
output is isolated per environment.

Running `terragrunt apply` from `environments/pve/dns-stack/` and from
`environments/pve-test-vm/dns-stack/` therefore produces and reads two
completely separate Terraform state files and two separate
`inventory.yml`s — one per environment, permanently. Neither can overwrite
the other. `scripts/provision.sh`'s `ENV_ROOT` variable
(`terraform/lxc/environments/${PVE_ENV}`) is what makes this automatic:
when `PVE_ENV` is set, it looks for
`${ENV_ROOT}/<stack>/inventory.yml` first.

`inventory.yml` files under `environments/**/` are gitignored (generated
artifacts, not tracked) — only each environment's `terragrunt.hcl` is
committed.

## How `technitium-stack` (and 10 others) fell through

`technitium-stack` was scaffolded directly under
`terraform/lxc/stacks/technitium-stack/` with its own `terragrunt.hcl`
(not one per environment) and no `terraform/lxc/environments/<env>/technitium-stack/`
directory at all. `scripts/provision.sh`'s `ENV_ROOT` lookup finds nothing
there for either environment, so it always falls back to the single shared
`stacks/technitium-stack/inventory.yml` — which reflects whichever
environment's Terraform was applied *last*, regardless of what the current
`PVE_ENV`/`--target-env` says.

Confirmed via `terragrunt run -- workspace list` in
`stacks/technitium-stack/`: only `default` and `pve` Terraform workspaces
exist. There is no dedicated `pve-test-vm` workspace — `pve-test-vm`'s real,
running Technitium container (confirmed live: VMID 20015 on
`pve-test-vm.gibbsgreatly.xyz`, `192.168.20.115`) was deployed at some
point without ever getting its own tracked Terraform state, likely via
ad hoc workspace switching rather than the isolated-directory pattern. Its
Terraform-tracked existence is therefore on shakier footing than every
other stack's `pve-test-vm` deployment, independent of the inventory
problem.

## Which stacks are affected (checked 2026-07-07)

```bash
comm -23 <(ls terraform/lxc/stacks | sort) <(ls terraform/lxc/environments/pve | sort)
```

11 stacks lack the per-environment layout. Classified by whether
`stack.yaml` has a `network:` zone (the signal that a stack is SDN-VLAN-
attached and genuinely runs a separate per-environment instance):

| Stack | Has `network:` zone? | Real risk? |
|---|---|---|
| `technitium-stack` | yes (`mgmt_seg`) | **Yes — the 2026-07-06 incident** |
| `dhcp-test-client-01` | yes (`test_dhcp_seg`) | No — Stage A's disposable DHCP-refactor test fixture, inherently `pve-test-vm`-only by design, never meant to exist on `pve` |
| `analysis-stack` | no | No — physical/`pve`-only |
| `cloud-stack` | no | No — physical/`pve`-only |
| `elastic-stack` | no | No — physical/`pve`-only |
| `gaming-stack` | no | No — physical/`pve`-only |
| `headscale-stack` | no | No — physical/`pve`-only |
| `management-stack` | no | No — physical/`pve`-only |
| `media-stack` | no | No — physical/`pve`-only |
| `security-stack` | no | No — physical/`pve`-only |
| `torrent-stack` | no | No — physical/`pve`-only |

**Only `technitium-stack` needs migrating.** The 9 physical/`pve`-only
stacks have no test-environment counterpart to conflict with — there is
nothing to isolate. `dhcp-test-client-01` is already safely handled by the
guardrail below (it would correctly block an attempt to provision it
against `pve`, since it should never exist there).

## Interim mitigations already in place (2026-07-06/07, same session as the incident)

Two stopgaps exist now, neither of which is the structural fix this
workspace is for:

1. **`scripts/provision.sh` guardrail** — `assert_inventory_matches_env()`,
   called from `provision_stack()`, hard-fails if a stack's resolved
   inventory's `pve_host` doesn't match what `PVE_ENV` expects, scoped to
   stacks with a `network:` zone. This converts a silent misdirect into a
   loud failure but does not fix the shared-state root cause.
2. **Manually-placed `inventory.yml` files** for `technitium-stack` under
   both `terraform/lxc/environments/pve/technitium-stack/inventory.yml`
   and `terraform/lxc/environments/pve-test-vm/technitium-stack/inventory.yml`,
   hand-written to match the correct per-environment values (cross-checked
   against `dns-stack`'s known-correct `pve-test-vm` inventory for the
   shared fields — `portainer_server_ip: 192.168.20.120`,
   `apt_cacher_host: 192.168.40.111` — and against `technitium-stack`'s own
   already-correct production values for the rest). This makes
   `scripts/provision.sh`'s `ENV_ROOT` lookup succeed for both
   environments *today*, without touching Terraform state at all.
   **These are hand-maintained, not Terraform-generated** — they will not
   be kept in sync if `stack.yaml` or environment IP conventions change,
   and they are exactly what the real migration (below) should eventually
   supersede with a proper `terragrunt.hcl` per environment.

## What "properly migrated" needs to look like

Matching the `dns-stack` pattern exactly:

- `terraform/lxc/environments/pve/technitium-stack/terragrunt.hcl`
- `terraform/lxc/environments/pve-test-vm/technitium-stack/terragrunt.hcl`
- Each environment's Terraform state (currently the single shared
  `stacks/technitium-stack/terraform.tfstate.d/{default,pve}`) split into
  two independent, isolated state files — one per environment — **without**
  destroying and recreating either live container. See plan.md for the
  safety-gated procedure.
