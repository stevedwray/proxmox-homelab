# Framework Desktop Integration

Planning workspace for bringing the Framework Desktop (`fe-pve`,
`192.168.1.121`) into the platform as a fully IaC-managed environment
(`pve-framework`), hosting a new AI/LLM application stack behind the existing
Traefik / Authentik / step-ca / Technitium / Harbor / NetBox platform.

Status: **Phase 0 (host bootstrap) and Phase 1 (network onboarding) are
both done and live-verified.** This is no longer planning-only — real
changes have been applied to `fe-pve`, the MikroTik, and the Terraform
network/storage model, all confirmed working:

- Host bootstrap: repo/subscription-nag fix, Terraform token (live-
  verified against the real API), unified-memory GTT tuning (computed
  from actual RAM, not hardcoded), `vmbr0` made VLAN-aware.
- `ai_seg` (VLAN 50) is live end-to-end — MikroTik, physical switch, and
  `fe-pve` all confirmed working together via an actual `ping`/packet
  capture, not just config checks. Three distinct bugs were found and
  fixed getting here; see Decision 4 and `plan.md` Phase 1 step 1 for the
  full trail.
- `terraform/lxc/network/pve-framework.yaml` and
  `terraform/lxc/storage/pve-framework.yaml` added, and the actual Proxmox
  SDN zone (`tvai`, VLAN 50) applied live via `pvesh` — confirmed present,
  existing LXCs unaffected.
- Secrets/environment handling generalized (Decision 6) and now has real
  data flowing through it: `terraform/secrets.pve-framework.enc.yaml`
  holds this node's actual Terraform token.

Not yet done: `terraform/lxc/environments/pve-framework/` per-stack
scaffolding, DNS/NetBox/registry onboarding (Phase 2), the AI stack itself
(Phase 3), and a full teardown-cycle validation before this is promoted
past the current `work/framework-integration` branch.

Relationship to `docs/framework/`: that directory is the completed OS
bake-off and hardware-enablement research (which OS to run, how GPU
passthrough works on this hardware, which model to use). This workspace
is the follow-on work of wiring that already-chosen design into the rest
of the repo's IaC and platform services. Read `docs/framework/` first for
the "why Proxmox, why this GPU setup, why this model" reasoning; this
workspace doesn't repeat it.

## Read in this order

1. [current-state.md](./current-state.md) — as-found facts about the box
   today (hardware, storage, network, existing unmanaged guests, gaps
   versus the platform contract).
2. [decisions.md](./decisions.md) — the architecture decisions this plan
   is built on, each with a recommended default and rationale. Flag any
   before implementation starts if you want a different call.
3. [plan.md](./plan.md) — the phased integration plan: host bootstrap →
   network onboarding → DNS/PKI/IPAM/registry onboarding → AI stack
   build-out → validation/promotion.

## Key conclusions up front

- `fe-pve` becomes a new environment, `pve-framework` — it can't literally
  "become" `pve-test-vm` or `pve` (different Proxmox API endpoint each) —
  see Decision 1.
- "Develop against test, pivot to lab" maps to *validation rigor* on
  `pve-framework` itself, not to changing which environment it is — see
  Decision 2.
- New dedicated SDN VLAN zone (`ai_seg`), not reuse of `mgmt_seg`/`edge_seg`
  — matches `docs/design/network.md`'s already-reserved "Future zones:
  `app_seg`" slot — see Decision 4. **Live and verified end-to-end as of
  2026-07-17** — VLAN 50, `192.168.50.0/24`, gateway `192.168.50.1`, all
  confirmed working from `fe-pve` itself.
- One GPU-passthrough exception LXC (`llm-gpu-stack`, router mode) plus
  one-LXC-per-service for everything else — see Decision 5. Not yet built.
- Secrets/environment handling is now generalized rather than
  per-node-hardcoded: `terraform/PRODUCTION_NODES` declares which nodes
  are production, `./with-secrets`'s safety rail blocks both `pve` and
  `pve-framework` uniformly, and `with-secrets-prod-framework` is now
  fully live with a real Terraform token in
  `terraform/secrets.pve-framework.enc.yaml` — see Decision 6.
- The box gets rebuilt from Ansible, not automated around its current
  hand-tuned state — see Decision 7.

## Related documentation

- `docs/framework/` — OS bake-off and GPU-enablement research (source
  material for Phase 0's Ansible role and Phase 3's `llm-gpu-stack`).
- `docs/reference/sdn-segment-routing.md` — the VLAN-zone pattern this
  plan's Phase 1 follows.
- `docs/design/network.md`, `docs/design/architecture.md` — platform-wide
  network and architecture contract this plan integrates against.
- `docs/environment-isolation/` — the per-environment Terragrunt layout
  this plan's Phase 3 must follow correctly from day one.
- `docs/dns-refactor/`, `docs/step-ca-implementation/` — DNS/PKI patterns
  Phase 2 reuses rather than reinvents.
