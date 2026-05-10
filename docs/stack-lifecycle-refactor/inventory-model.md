# Inventory Model

## Direction

The shared inventory model should evolve from `stack.yaml`, not replace it immediately.

The goal is a higher-level stack contract that can drive:

- Terraform inputs
- Ansible inventory and variables
- generated publish artifacts
- validation metadata

## Current Implemented Baseline

The new model should not assume a blank slate.

Current contract and generation machinery already exist in:

- `terraform/lxc/PLATFORM_CONTRACT.md`
- `terraform/lxc/templates/inventory.tpl`
- `terraform/lxc/main.tf`
- Python generation and reconciliation scripts under `terraform/lxc/`, including:
  - `generate-zone-members-index.py`
  - `render-edge-coredns.py`
  - `render-edge-traefik.py`
  - `edge_manifest.py`
  - `reconcile-edge.py`
  - `reconcile-authentik-edge.py`

Stage 1 should treat these as prior art and transition inputs, not ignore them.

## Source Of Truth Guidance

### Source Of Truth Inputs

- stack identity
- sizing and storage intent
- network attachment intent
- dependencies
- service profile
- validation profile
- maintenance policy

### Derived Artifacts

- Terraform vars or rendered inputs
- Ansible inventory
- Ansible vars artifacts
- generated DNS or ingress publish files
- rendered Proxmox-side network/firewall vars

Derived artifacts should not be hand-edited.

Existing Python-based generation and reconciliation tooling should be explicitly considered when deciding whether a derived artifact is:

- retained as-is
- extended
- wrapped by the new contract model
- eventually replaced

## Early Schema Themes

The shared contract will likely need sections for:

- `identity`
- `infrastructure`
- `network`
- `services`
- `maintenance`
- `validation`
- `integrations`

## Open Design Questions

- what remains per-stack vs environment-level
- what belongs in shared network intent rather than per-stack config
- how non-secret vars should be layered
- how to represent special-case behavior without overcomplicating the base schema

## Example: render + reconcile flow (invocation)

The repository includes small Python scripts that render derived artifacts and
perform lightweight reconciliation. Below is an example flow that the SLR docs
should document as an implementer example.

1. Generate the edge manifest (creates a platform view of stacks and zones):

```bash
python3 terraform/lxc/edge_manifest.py --env pve-test \
  > .git/ai/sessions/evidence/session-01/edge-manifest.json
```

Expected: JSON manifest containing stack entries and zone mappings.

2. Render DNS/ingress publish artifacts (example for CoreDNS and Traefik):

```bash
python3 terraform/lxc/render-edge-coredns.py \
  --manifest .git/ai/sessions/evidence/session-01/edge-manifest.json \
  --out out/coredns.zone

python3 terraform/lxc/render-edge-traefik.py \
  --manifest .git/ai/sessions/evidence/session-01/edge-manifest.json \
  --out out/traefik-routes.yml
```

Expected: `out/coredns.zone` and `out/traefik-routes.yml` with rendered entries for
the current stacks.

3. (Optional) Reconcile runtime state against the manifest:

```bash
python3 terraform/lxc/reconcile-edge.py --manifest .git/ai/sessions/evidence/session-01/edge-manifest.json
```

Expected: printed summary of differences and optional dump of corrective actions
to a `reconcile-*.json` file.

Notes:
- Add these example commands and expected outputs to `inventory-model.md` so
  implementers have an immediate way to reproduce the generated artifacts.
- Link the script paths from this doc to the implementation files in
  `terraform/lxc/`.
