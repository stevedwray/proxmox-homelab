# Framework Desktop Integration

Workspace for bringing the Framework Desktop into the platform as a fully
IaC-managed environment (`pve-framework`), hosting a new AI/LLM application
stack behind the existing Traefik / Authentik / step-ca / Technitium /
Harbor / NetBox platform.

> **Superseded for the *hosting* question (2026-07-20).** The Proxmox/LXC
> memory model turned out to have a real, diagnosed reliability problem —
> `llm-gpu-stack`'s 8GB LXC memory ceiling was silently OOM-killing the LLM
> service under real usage, misread overnight as a "probabilistic Vulkan
> crash." Combined with the operator's actual intent (one flexible GPU
> resource, not two statically-partitioned containers), `pve-framework` is
> being rebuilt bare-metal on Ubuntu 26 — see
> **[`docs/framework-ubuntu/plan.md`](../framework-ubuntu/plan.md)** for the
> migration plan and
> **[`lessons-learned.md`](./lessons-learned.md)** for what's durable from
> this Proxmox/LXC chapter versus what's now historical.
>
> **Still live and unaffected by this move**: everything below about model
> selection, server choice, tool-calling behavior, and client integration —
> [`findings-plan.md`](./findings-plan.md) and
> [`vscode-tool-calling-investigation-2026-07-19.md`](./vscode-tool-calling-investigation-2026-07-19.md)
> remain the current reference for the AI stack itself, independent of
> which host it runs on.
>
> Everything else in this README describes the Proxmox/LXC-era state as it
> stood before that decision — kept for context, not as current guidance
> on how to host this.

Status: **The reinstall happened (2026-07-18) — `pve-framework` is now the
real, permanently-named host at `192.168.1.8`, not the disposable
exploration-phase `fe-pve` box.** Phase 0 (host bootstrap) and Phase 1
(network onboarding) are both done and live-verified against this fresh
install:

- Host bootstrap: repo/subscription-nag fix, fresh Terraform token
  (live-verified against the real API), unified-memory GTT tuning
  (computed from actual RAM), `vmbr0` made VLAN-aware — all confirmed
  live post-reboot, not just trusted from the Ansible run completing.
- `ai_seg` (VLAN 50) is live end-to-end — SDN zone/VNet/subnet
  recreated via `pvesh`, reachability re-confirmed with a real
  `ping`+`tcpdump` capture. The physical MikroTik/switch path worked
  cleanly on the first attempt this time (unlike the three-bug original
  bring-up), confirming it genuinely survived the reinstall unchanged.
- Secrets/environment handling (Decision 6) has real data flowing
  through it again: `terraform/secrets.pve-framework.enc.yaml` holds
  this fresh host's actual Terraform token, `with-secrets-prod-framework`
  verified end-to-end including its mutating-command approval gate.

Full current facts: [current-state.md](./current-state.md). Concrete
next-step runbook: [post-reinstall-plan.md](./post-reinstall-plan.md) —
**Phase 3 prerequisites are next**: no container templates exist yet on
the fresh install (`pveam list local` is empty), and `llm-gpu-stack`/
`comfyui-stack` — written and `plan`-clean but never `apply`'d — are
still genuinely untested against a real host.

Not yet done: container templates on the fresh host (blocks everything
below), actually `apply`-ing `llm-gpu-stack`/`comfyui-stack` against
`pve-framework` for the first time, DNS/NetBox/registry onboarding
(Phase 2 — scoped and mostly straightforward, see plan.md), and the
dual-workload gateway (depends on both GPU stacks existing as real
systemd services first).

**ComfyUI (image/video generation) — bake-off complete and successful.**
A committed Phase 3 stack, not a gated candidate — see
`docs/framework/comfyui-image-video-gen-findings.md`. The bake-off ran
live in its own container (9002) on the old exploration-phase box,
separate from `llm-gpu-stack`'s container by deliberate design (Decision
5, revised) — a real host-wide OOM incident during the bake-off validated
that separation directly. That container didn't survive the reinstall;
its recipe is now `comfyui_stack`'s Ansible role, written and
`plan`-validated but not yet run against a real host. A follow-on design
(not yet built) for running both GPU workloads without statically halving
host memory between them: `docs/framework/dual-workload-gateway-design.md`.

Relationship to `docs/framework/`: that directory is the completed OS
bake-off and hardware-enablement research (which OS to run, how GPU
passthrough works on this hardware, which model to use). This workspace
is the follow-on work of wiring that already-chosen design into the rest
of the repo's IaC and platform services. Read `docs/framework/` first for
the "why Proxmox, why this GPU setup, why this model" reasoning; this
workspace doesn't repeat it.

## Read in this order

1. [current-state.md](./current-state.md) — as-found facts about the box
   today (hardware, storage, network, gaps versus the platform contract).
2. [decisions.md](./decisions.md) — the architecture decisions this plan
   is built on, each with a recommended default and rationale. Flag any
   before implementation starts if you want a different call.
3. [plan.md](./plan.md) — the phased integration plan: host bootstrap →
   network onboarding → DNS/PKI/IPAM/registry onboarding → AI stack
   build-out → validation/promotion.
4. [post-reinstall-plan.md](./post-reinstall-plan.md) — **read this before
   doing anything with the box right now.** The concrete runbook for what
   happens once it's wiped and reinstalled, and what needs to be built
   first so that's a clean, low-risk operation.

## Key conclusions up front

- `fe-pve` becomes a new environment, `pve-framework` — it can't literally
  "become" `pve-test-vm` or `pve` (different Proxmox API endpoint each) —
  see Decision 1.
- "Develop against test, pivot to lab" maps to *validation rigor* on
  `pve-framework` itself, not to changing which environment it is — see
  Decision 2.
- New dedicated SDN VLAN zone (`ai_seg`), not reuse of `mgmt_seg`/`edge_seg`
  — matches `docs/design/network.md`'s already-reserved "Future zones:
  `app_seg`" slot — see Decision 4. **Live and verified end-to-end against
  the real `pve-framework` host as of 2026-07-18** — VLAN 50,
  `192.168.50.0/24`, gateway `192.168.50.1`.
- One GPU-passthrough exception LXC **per distinct GPU workload class**
  (not a single universal one) plus one-LXC-per-service for everything
  else — see Decision 5, revised with real evidence from the bake-off:
  `llm-gpu-stack` and `comfyui-stack` are two separate GPU-passthrough
  containers, validated by a real host-wide OOM incident that occurred
  when they were memory-heavy at the same time. Both are now real
  Terraform (`stack.yaml`) + Ansible (`llm_gpu_stack`/`comfyui_stack`
  roles), `plan`-validated but not yet `apply`'d against `pve-framework`.
- Secrets/environment handling is now generalized rather than
  per-node-hardcoded: `terraform/PRODUCTION_NODES` declares which nodes
  are production, `./with-secrets`'s safety rail blocks both `pve` and
  `pve-framework` uniformly, and `with-secrets-prod-framework` is now
  fully live with a real Terraform token in
  `terraform/secrets.pve-framework.enc.yaml` — see Decision 6.
- The box gets rebuilt from Ansible, not automated around its
  hand-tuned exploration-phase state — see Decision 7. **Done
  2026-07-18** — the rebuild happened, hostname is `pve-framework` from
  install time, and Phase 0/1 have both been re-run and re-verified
  against the fresh host rather than assumed to carry over.
- Authentik integration for the AI stack defaults to native OIDC per
  service (this platform's actual established pattern, not a new one),
  validated end-to-end rather than assumed — `llama-server` uses its own
  API-key auth instead, since it's a machine API, not a browser login —
  see Decision 8.

## Related documentation

- `docs/framework/` — OS bake-off and GPU-enablement research (source
  material for Phase 0's Ansible role and Phase 3's `llm-gpu-stack`).
- `docs/framework/comfyui-gpu-bakeoff-prep.md` — scoping doc for the
  ComfyUI bake-off (kept for the reasoning; see the findings doc for the
  result).
- `docs/framework/comfyui-image-video-gen-findings.md` — the completed
  ComfyUI bake-off: setup, two upstream bugs fixed, model survey, and the
  host-wide OOM incident + fix that shaped Decision 5's revision.
- `docs/framework/dual-workload-gateway-design.md` — design (not built)
  for sharing the host's memory safely between `llm-gpu-stack` and
  `comfyui-stack`.
- `docs/reference/sdn-segment-routing.md` — the VLAN-zone pattern this
  plan's Phase 1 follows.
- `docs/design/network.md`, `docs/design/architecture.md` — platform-wide
  network and architecture contract this plan integrates against.
- `docs/environment-isolation/` — the per-environment Terragrunt layout
  this plan's Phase 3 must follow correctly from day one.
- `docs/dns-refactor/`, `docs/step-ca-implementation/` — DNS/PKI patterns
  Phase 2 reuses rather than reinvents.
- [pentesting.md](./pentesting.md) — exploratory feasibility scan for
  running PentestGPT against the local model stack; not started, gated on
  `findings-plan.md`'s client/server validation landing first.
- [lessons-learned.md](./lessons-learned.md) — consolidated Proxmox/LXC/
  Terraform-era findings, curated for anyone evaluating a similar setup on
  different hardware; superseded here by `docs/framework-ubuntu/`.
