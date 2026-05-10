# Shared Stack Contract — Draft

This is a first-pass proposal for the shared `stack.yaml` contract used by
Terraform (platform/day-1) and Ansible (day-2). It documents the canonical
fields, ownership (authoritative vs derived), and recommendations for
backwards-compatible extension.

## Principles

- Keep stack-authored fields authoritative for intent (size, zone, features).
- Keep generated artifacts derived and clearly annotated in generated inventory.
- Prefer additive changes; renaming/removing fields is a breaking contract change.

## Top-level contract (recommended YAML shape)

```yaml
name: <stack-dir-name>
hostname: <string>           # authoritative
deployment_tier: platform|apps
network:
  zone: <string>             # authoritative (optional)
  ip_address: <cidr>         # authoritative (optional)
resources:
  vmid: <int>                # optional (prefer not to collide)
  cores: <int>
  memory: <int>
  rootfs_size: <int>
  extra_mount:
    path: <string>
    size: <string>
    storage: <string>
features:
  portainer_agent: <bool>
  keyctl: <bool>
ansible:
  playbook: <string>         # consumed by `scripts/provision.sh`
  provides: [<string>]
  depends_on: [<string>]
overrides:
  registry_host: <string>    # optional per-stack override of platform defaults
  apt_cacher_host: <string>
  portainer_server_ip: <string>
metadata:
  tags: [<string>]
  description: <string>
```

## Ownership mapping

- Authoritative (stack author controls):
  - `hostname`, `deployment_tier`, `network.zone`, `resources.*`, `features.*`,
    `ansible.playbook`, `ansible.depends_on`, `metadata.*`.

- Platform-derived (produced by Terraform into generated inventory):
  - `ip_address` (if computed), `registry_host`, `apt_cacher_host`,
    `portainer_server_ip`, `network_zone` (resolved), any host-specific
    hostvars required by Ansible playbooks.

- Runtime/Ansible-owned (managed inside the container at day-2):
  - application secrets, DB passwords, tokens, runtime service state.

## Validation metadata

- `validation`: optional block (used by platform and CI to validate expectations):

```yaml
validation:
  must_reach:
    - service: apt-proxy
      host_port: 10.57.3.11:3142
  inventory_hash: <sha256>   # optional hash of generated inventory to assert immutability
```

## Backwards-compatibility recommendations

- When adding a new field, default to non-breaking behavior and document the
  generated inventory change in `PLATFORM_CONTRACT.md` and per-stack
  `STACK_CONTRACT.md`.
- Avoid renaming existing template keys in `templates/inventory.tpl` — prefer
  adding aliases and a deprecation period.

## Next steps

- Reconcile this draft with `terraform/lxc/PLATFORM_CONTRACT.md` and per-stack
  `STACK_CONTRACT.md` files to enumerate gaps and conflicts (audit matrix).
- Produce a minimal JSON Schema for `stack.yaml` once the draft fields settle.

## Contract reconciliation audit matrix

The audit matrix below is a concise, actionable checklist for Stage-1 that
captures where the implemented contracts (`PLATFORM_CONTRACT.md` and
per-stack `STACK_CONTRACT.md`) align or diverge from this shared draft.

| Source | Exemplar stacks | Notes |
|---|---|---|
| `terraform/lxc/PLATFORM_CONTRACT.md` | apt-cacher-stack, harbor-stack, portainer-stack, step-ca-stack | Platform-level fields that must be reconciled with shared draft |
| `terraform/lxc/stacks/apt-cacher-stack/STACK_CONTRACT.md` | apt-cacher-stack | Record any field name mismatches and derived expectations |
| `terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md` | harbor-stack | Record required service endpoints and validation metadata |
| `terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md` | portainer-stack | Surface Portainer-specific overrides (eg. `registry_host`) |
| `terraform/lxc/stacks/step-ca-stack/STACK_CONTRACT.md` | step-ca-stack | Surface required TLS/ACME endpoints and validation probes |

Stage-1 implementers should populate the matrix rows with:

- `Covered` / `Partial` / `Missing` status per field group
- Notes about required generator changes (Terraform) or playbook expectations (Ansible)
- Evidence links to PRs or commits that reconcile the differences

The executor session for Stage-1 will assert the presence of this header and
that the exemplar stacks above are at least referenced in the draft as the
initial audit coverage.

## Generated vs authoritative boundaries

- Authoritative: fields authored by the stack owner and intended as source-of-truth for intent and topology (for example `hostname`, `deployment_tier`, `resources.*`, `features.*`).
- Generated/Derived: fields produced by the platform (Terraform) or reconcilers and should be treated as read-only in stack author source (for example computed `ip_address`, resolved `network.zone`, generated inventory hostvars).
- Runtime/Ansible-owned: values created or managed at day-2 by playbooks or running services (for example runtime secrets, service state).

Explicitly declaring which fields are authoritative prevents accidental drift when generated tooling overwrites inventory outputs.

## Open schema questions

- Should `network.ip_address` be a single CIDR string, or a structured object (address + prefix + gateway)?
- How should `overrides.*` prioritize platform defaults vs stack overrides? (merge rules required)
- What is the required/optional policy for `resources.vmid` allocation and collision avoidance?
- Do we include a `generated:` metadata block in every stack to record computed fields and an inventory `inventory_hash` for CI assertions?

These will inform the minimal JSON Schema and validator behavior.

## Exemplar-stage validation gates

- Inventory schema validation (JSON Schema): fail on required missing authoritative fields.
- Inventory immutability check: assert `inventory_hash` matches computed hash for generated artifacts in CI.
- Smoke service checks: for stacks that expose services (eg. `apt-cacher-stack`, `harbor-stack`), run lightweight TCP/HTTP probes as part of the stage validation.
- Contract reconciliation report: produce an audit matrix comparing `PLATFORM_CONTRACT.md` and per-stack `STACK_CONTRACT.md` against this shared draft and surface conflicts.

Each gate should be runnable from CI and record machine-readable evidence for the executor session.
