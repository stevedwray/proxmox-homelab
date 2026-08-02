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
  `docker-compose.yml`).
- New bounded Ansible playbook `deploy-minecraft-stack.yml` — `docker_base`
  role + compose up, check-mode guards on the compose/startup tasks
  following the Stage 5/6 pattern (`not ansible_check_mode` /
  `ignore_errors: "{{ ansible_check_mode }}"` where the container/service
  doesn't exist yet on a fresh host).
- `portainer_agent: false` — Portainer registration is explicitly out of
  scope for this first pass (see "Deliberately deferred" below for why).
- Health check: TCP reachability on `25565` + a server-list-ping status
  check (no RCON/auth needed for basic validation).

### Exact target content for slice 1

A prior attempt at this slice produced a `stack.yaml` with wrong field names
(`stack_name` instead of `hostname`), a fabricated nested `network:` block
holding `ip_address`/`gateway`/a non-existent `bridge` key, and several
required fields (`dns_server`, `deployment_tier`) dropped entirely — despite
being told to "model on" a real template file. The model pattern-matched
generic Docker/IaC shape instead of transcribing the referenced file's
actual fields. To remove that failure mode, `stack.yaml`'s content below is
the literal target to transcribe, not a shape to approximate —
`stack.yaml`'s schema is entirely repo-specific, so there's no competing
generic pattern for the model to fall back on, and copying it exactly is a
correctness win, not a shortcut. `docker-compose.yml` is different: it's
handled further below as a generation task with explicit constraints,
because a Minecraft Compose file is one of the most common patterns in
public training data, and two prior attempts both show that prior winning
out over instructions even when given literal content to copy. Two named
references only, each for a different part — copying more than these two
invites exactly the "triangulate five near-matches" problem this note
exists to prevent:

- **`stack.yaml` field shape**: `terraform/lxc/stacks/ci-runner-01/stack.yaml`
  (the current active exemplar, not `docker-socket-proxy-test`, which
  predates several now-required fields and isn't in the validator's active
  set).
- **`docker-compose.yml` shape**: `terraform/lxc/stacks/authentik-stack/docker-compose.yml`
  (`ci-runner-01` has no compose file — it's a systemd stack).

`terraform/lxc/stacks/minecraft-stack/stack.yaml`:

```yaml
hostname: minecraft-stack
ip_address: "192.168.1.60/24"
gateway: "192.168.1.1"
dns_server: "192.168.1.1"
vmid: 170
cores: 2
memory: 2048
swap: 512
rootfs_size: 8
storage_profile: platform-default
docker_storage_size: "10G"
template_name: "debian-13.1-2-docker-template.tar.gz"
tags:
  - docker
  - minecraft
  - game
depends_on: []
provides:
  - service: minecraft-java
    port: 25565
    protocol: tcp
ansible_playbook: "deploy-minecraft-stack"
deployment_tier: apps
portainer_agent: false
```

`deployment_tier: apps` is correct and intentional here even though the
playbook shape below mirrors `ci-runner-01` (`deployment_tier: platform`).
The tier label is orchestration-scope metadata (`scripts/provision.sh
--tier`) describing what this stack *is*, not which playbook pattern it
must use — those are two independent choices, and this stage deliberately
picks a Tier 1-shaped playbook for a Tier 2-tiered stack for its first
pass (see "Deliberately deferred" below). No `network:` block: this is a
plain LAN bridge with no SDN zone, and `network.zone`/`network.access_path`
are the only real keys under that block (see
`terraform/lxc/PLATFORM_CONTRACT.md`'s field table) — there is no `bridge:`
field in the schema at all.

`terraform/lxc/stacks/minecraft-stack/docker-compose.yml`: **author this one,
don't transcribe a fixed answer** — a Minecraft Compose file is one of the
most heavily-represented patterns in public training data, so the risk here
isn't guessing wrong from nothing, it's a strong pretrained prior overriding
this repo's actual conventions. Two prior attempts both fell into exactly
that: `itzg/minecraft-server:latest` instead of a pinned tag, and one
invented a custom top-level `networks:` block plus a separate templated
compose file living outside the stack directory entirely
(`terraform/lxc/templates/minecraft-compose.yml.j2`, rendered via Ansible
`template`) instead of a static `docker-compose.yml` in
`terraform/lxc/stacks/minecraft-stack/` — checked directly against
`terraform/lxc/ansible/playbooks/deploy-stack.yml`'s
`lookup('file', '../../stacks/' + stack_name + '/docker-compose.yml')`,
which is the one real precedent for how this repo reads a stack's compose
file, and confirmed no active stack does it any other way.

Requirements:
- Single service, `itzg/minecraft-server`, pinned to the `stable-java21` tag
  — not `latest` (see `.hold/minecraft/stack.yaml`'s discovery notes for why
  this tag is the known-good choice).
- `EULA: "TRUE"` in `environment:` — required by the image itself; without
  it the container starts, prints Mojang's EULA notice, and exits without
  running a server.
- Port `25565/tcp` only (not `25565:25565` bare, not UDP — see the port note
  in `.hold/minecraft/stack.yaml`).
- World data (`/data`) persisted via a named Docker volume declared in a
  top-level `volumes:` block — not a relative bind mount like `./data` or
  `./minecraft-data` (both prior attempts used a bind mount here) — follow
  `authentik-stack`'s pattern (`authentik-postgresql:/var/lib/postgresql/data`
  plus a matching top-level `volumes:` entry).
- `container_name: minecraft-stack-minecraft` and `restart: unless-stopped`,
  matching the `<stack>-<service>` naming convention used elsewhere.

Explicitly do not add, even though they're common in a typical public
Minecraft Compose example: a custom top-level `networks:` block, a pinned
`VERSION` environment variable, difficulty/MOTD/player-count/query env vars,
or a separately mounted `server.properties` file — none of that was asked
for, this is a deliberately minimal first pass (see Scope above), and
adding it is exactly the failure mode both prior attempts hit.

`STACK_CONTRACT.md`: copy `terraform/lxc/STACK_CONTRACT.template.md`, not
`ci-runner-01/STACK_CONTRACT.md` directly — the template exists specifically
so every required section heading (`## Provides`, `## Dependencies`, both
enforced by `validate-stack-metadata.sh --check-contract-sections`) is
present by construction rather than left to the prior attempt's ad hoc
one-paragraph contract, which had neither. Read `ci-runner-01`'s contract
alongside the template for how a filled-in example reads, but fill in the
template's placeholders rather than free-writing from the example.

**Checkpoint — run immediately after writing all three files, before
moving to slice 2:**

```bash
terraform/lxc/validate-stack-metadata.sh --check-contract-sections
terraform/lxc/validate-compose.sh --stack minecraft-stack
```

(No `./with-secrets` needed — both validators only read local YAML/Markdown
files, no credentials or network calls involved.)

Both are expected to fail before slice 1 (missing files) and should pass
with zero issues once all three files are written correctly. Between them
they mechanically catch every defect from both prior attempts: missing or
nested required `stack.yaml` fields, bad `ip_address` shape, invalid
`deployment_tier`, missing contract sections, an unpinned or `:latest`
image tag, a custom `networks:` block, and a `docker-compose.yml` that
doesn't exist at the correct stack-owned path. Do not proceed to slice 2
while either fails.

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

1. Author `stack.yaml` + `STACK_CONTRACT.md` + `docker-compose.yml` — see
   "Exact target content for slice 1" above for `stack.yaml`'s literal
   content, `docker-compose.yml`'s generation constraints, the two named
   reference files, and the mandatory validator checkpoint before moving on.
   The `STACK_CONTRACT.md`'s `## Implementation Files` section
   should list the exact new paths being created under
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
  deferred" above). `deployment_tier: apps` is already set; the remaining
  decision is whether minecraft-stack should move to the generic Tier 2
  `deploy-stack.yml`/`app_stack` playbook pattern (which brings
  `portainer_agent` with it), or stay on its own bespoke
  `deploy-minecraft-stack.yml` playbook with the `portainer_agent` role
  added explicitly. Do this only after `portainer-agent-contract.md` exists
  to make the tradeoff unambiguous.
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
