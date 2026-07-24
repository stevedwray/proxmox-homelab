# Stage 10 — First Application-Tier Stack Exemplar (`minecraft-stack`)

## Why this stage exists

Stages 3–9 proved the contract-driven process (`stack.yaml` +
`STACK_CONTRACT.md`, Terraform day-1 / Ansible day-2, check → live → rerun →
health validation) end-to-end, but only against platform/infra stacks
(harbor, apt-cacher, netbox, portainer, monitoring, dns, step-ca, authentik,
proxy, ci-runner-01). The existing user-facing app stacks
(`torrent-stack`, `media-stack`, `gaming-stack`) predate this process
entirely — they're legacy LAN-bridge LXCs deployed via a generic
`migrate-portainer-stack` playbook, with no `STACK_CONTRACT.md`, no SDN
zone, no involvement in Stage 6–9 validation. `docs/application-migration/`
sketches a future migration for them but its VLAN pre-conditions
(`dl_seg`/`media_seg`/`game_seg`) were never created.

This stage is the first real test of whether the Stage 3–9 pattern actually
extends to a genuinely new application container, not another platform
stack. Minecraft was picked as the simplest possible case, deliberately
decoupled from the legacy `gaming-stack` LXC (fresh world, no data
migration).

This is also the first real-world (non-synthetic) task for the OpenCode/
Ollama coding-agent decision recorded in `docs/framework-ubuntu/
coding-agents-findings.md` — see "Execution" below.

## Scope

**Target:** `pve-test-vm` only. No production node involved, no
`TASK_APPROVAL` needed.

**Network — simplified for this first pass:** plain LAN bridge (`vmbr0`,
`192.168.1.0/24`), same as `docker-socket-proxy-test` and the legacy app
stacks — **not** a new `game_seg` SDN zone. A dedicated gaming VLAN is
reasonable long-term (see CLAUDE.md's now-split additive-SDN-change tier),
but for an initial exemplar/local-AI test it's unnecessary scope: putting
the container on the same subnet as the workstation means reachability
from the workstation needs no MikroTik change at all, and defers the SDN
work to a later stage once the pattern itself is proven.

- Candidate IP: `192.168.1.60` — not found in any tracked `inventory.yml`/
  `stack.yaml`/doc as of 2026-07-22, but that's a repo-text search, not a
  live lease check. **Confirm free before applying** (e.g. `arp -a` / ping
  from the workstation, or `pvesh get /nodes/pve-test-vm/lxc` — read-only,
  no approval needed).
- Candidate VMID: `170` — pick a value confirmed unused on `pve-test-vm`
  via `pct list` (read-only) before applying.

**In scope:**
- New stack directory `terraform/lxc/stacks/minecraft-stack/` (`stack.yaml`,
  `STACK_CONTRACT.md`, `terragrunt.hcl`, `inventory.yml`,
  `docker-compose.yml`), modeled directly on `docker-socket-proxy-test`'s
  shape (simplest existing exemplar: plain LAN bridge, no zone, no Harbor
  dependency assumptions to untangle).
- `docker-compose.yml`: single service, `itzg/minecraft-server:stable-java21`
  (same image already in use in the legacy `gaming-stack` box, per the
  `.hold/minecraft/stack.yaml` discovery notes — known-good image choice).
- New bounded Ansible playbook `deploy-minecraft-stack.yml` — `docker_base`
  role + compose up, check-mode guards on the compose/startup tasks
  following the Stage 5/6 pattern (`not ansible_check_mode` /
  `ignore_errors: "{{ ansible_check_mode }}"` where the container/service
  doesn't exist yet on a fresh host).
- `portainer_agent: false` — Portainer registration is explicitly out of
  scope for this first pass (see "Deliberately deferred" below for why).
- Health check: TCP reachability on `25565` + a server-list-ping status
  check (no RCON/auth needed for basic validation).

**Explicitly out of scope for this stage:**
- No new SDN zone / `game_seg` (deferred to a later stage, now that
  CLAUDE.md's additive-SDN tier makes it cheap to validate when it happens)
- No Traefik route (raw TCP game protocol, not HTTP)
- No Authentik (game servers are the one auth class in the existing
  `application-migration` model with "None")
- No world-data migration from the legacy `gaming-stack` LXC
- No `terraform test` fixtures — the local `bpg/proxmox` provider handshake
  bug from the coding-agent bake-off is still open; validate with
  `terragrunt apply`/`plan` + Ansible functional checks only, same as every
  Stage 6 exemplar
- No Portainer registration (see "Deliberately deferred" below)

### Deliberately deferred: Portainer registration

Earlier drafts of this stage set `portainer_agent: true`, assuming it would
register the stack with `portainer-stack`. It would not have: at the
Terraform layer `portainer_agent` only fires `null_resource.stack_cleanup`
(`terraform/lxc/main.tf`, explicitly commented "Legacy Portainer cleanup
resource kept only for state retirement") — real agent registration only
happens when a playbook explicitly includes the `portainer_agent` role, as
`deploy-stack.yml` does for `deployment_tier: apps` stacks. `ci-runner-01`,
this stage's structural template, is `deployment_tier: platform` and never
takes that path, so copying its shape while also claiming Portainer
registration was internally inconsistent. Rather than resolve the Tier
1-vs-2 question for a first opencode run, this stage drops Portainer
entirely: `portainer_agent: false`, no registration claim, no reachability
check. Revisit as a separate, explicitly scoped follow-up once the
`portainer-agent-contract.md` subsystem contract exists to make the correct
pattern unambiguous.

## Validation sequence

Matches `docs/stack-lifecycle-refactor/validation.md`'s standard shape,
Ansible-task/role tier (CLAUDE.md) — no full teardown needed, this is a
plain LAN-bridge stack with no SDN change at all:

```
terragrunt plan    (target guard: TF_VAR_proxmox_node=pve-test-vm)
terragrunt apply
./with-secrets scripts/provision.sh --stack minecraft-stack --check
./with-secrets scripts/provision.sh --stack minecraft-stack
./with-secrets scripts/provision.sh --stack minecraft-stack   (idempotent rerun)
health check: TCP connect + server-list ping on :25565
```

Evidence under `docs/sessions/evidence/slr-10-minecraft-exemplar/`.

**Done when:** apply → check → live → rerun → health all pass and
`STACK_CONTRACT.md` reflects reality (including `portainer_agent: false`
and why).

## Execution — using the local coding agent, not this session

This stage is the exemplar task for the OpenCode/Ollama bake-off decision:
one coordinating OpenCode 1.18.4 session against Ollama
(`eval-qwen3-coder-30b-a3b:q4_k_m`), in a disposable `task/slr-10-minecraft-
exemplar` worktree, never `main`. Run as bounded slices (matching what
actually passed cleanly in the bake-off, rather than one large prompt):

1. Author `stack.yaml` + `STACK_CONTRACT.md` + `docker-compose.yml`
   (context: `docker-socket-proxy-test/` and `ci-runner-01/
   STACK_CONTRACT.md` as templates). Include the `## Implementation Files`
   section (see `terraform/lxc/README.md`'s Validation section for why) —
   list the exact new paths being created under
   `terraform/lxc/stacks/minecraft-stack/` and
   `terraform/lxc/ansible/playbooks/deploy-minecraft-stack.yml`, and state
   plainly that none of them exist yet, so the agent creates rather than
   searches for them.
2. `terragrunt.hcl` + `inventory.yml`, `terragrunt plan`
3. `deploy-minecraft-stack.yml` with check-mode guards
4. Run check → live → rerun → health, fix whatever check-mode reveals
5. Evidence capture + close out `STACK_CONTRACT.md`/this doc

Since target is `pve-test-vm`, not a production node, there's no
`with-secrets-prod`/`TASK_APPROVAL` gate — OpenCode can run
`terragrunt`/`provision.sh` itself inside the worktree via `./with-secrets`.
Review the diff and command output at each slice boundary rather than
pre-approving, per CLAUDE.md's normal commit-after-verified flow. If
OpenCode stalls on a slice, drop to Aider on the same worktree/model for
that slice only (its assigned fallback role per the bake-off decision).

## Open follow-ups (not blocking this stage)

- Portainer registration for minecraft-stack — deferred (see "Deliberately
  deferred" above). Do this only after `portainer-agent-contract.md` exists
  and after deciding whether minecraft-stack should move to
  `deployment_tier: apps` (Tier 2 `deploy-stack.yml`/`app_stack` path) or
  stay Tier 1-shaped with the `portainer_agent` role added explicitly to its
  own playbook.
- `game_seg` SDN zone + MikroTik trunk/rule for workstation reachability —
  deferred; now cheap to validate under CLAUDE.md's additive-SDN tier when
  it happens.
- Attaching `framework.gibbsgreatly.xyz`'s AI containers (Ollama, ComfyUI,
  llama.cpp) to the lab Portainer via Edge Agent mode (port 8000,
  outbound-only from framework) — separate task, touches a production-trust
  node, goes through `with-secrets-prod-framework` + `TASK_APPROVAL`.
- Switching the coding-agent Ollama endpoint from raw IP
  (`192.168.1.8:11434`) to the DNS name (`framework.gibbsgreatly.xyz:11434`)
  — trivial, no infra change, not yet done.
- Routing Ollama through Traefik (`llm.${LAB_DOMAIN}`-style) — defer until
  the existing no-auth gap on that route (LM Studio's `auth.mode: none`,
  flagged in `docs/framework-ubuntu/plan.md` Phase 6) is actually closed;
  doing it sooner adds a hop without closing the real gap.
