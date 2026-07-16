# Framework Desktop Integration

Planning workspace for bringing the Framework Desktop (`fe-pve`,
`192.168.1.121`) into the platform as a fully IaC-managed environment
(`pve-framework`), hosting a new AI/LLM application stack behind the existing
Traefik / Authentik / step-ca / Technitium / Harbor / NetBox platform.

Status: **planning, plus one piece of implemented plumbing.** No
Terraform, Ansible, or MikroTik changes have been made against `pve` or
`fe-pve` — but Decision 6's secrets/environment generalization
(`terraform/PRODUCTION_NODES`, `scripts/with-secrets-prod-lib.sh`,
`with-secrets-prod-framework`, `.env.pve-framework`) is real, committed-
ready code, not just a proposal. See Decision 6 for what changed and why.

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
  `app_seg`" slot — see Decision 4. **Requires an out-of-band MikroTik/
  switch trunk change before any container can be deployed.**
- One GPU-passthrough exception LXC (`llm-gpu-stack`, router mode) plus
  one-LXC-per-service for everything else — see Decision 5.
- Secrets/environment handling is now generalized rather than
  per-node-hardcoded: `terraform/PRODUCTION_NODES` declares which nodes
  are production, `with-secrets-prod-framework` is a real (if not yet
  usable — no secrets file exists until Phase 0) wrapper for this node,
  and `./with-secrets`'s safety rail now blocks both `pve` and
  `pve-framework` uniformly — see Decision 6.
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
