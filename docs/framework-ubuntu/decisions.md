# Ubuntu 26 Migration — Decisions

Companion to [`plan.md`](./plan.md). Each entry records the choice and the
reasoning, in the style already established in
[`docs/framework-integration/decisions.md`](../framework-integration/decisions.md)
(now historical — see
[`lessons-learned.md`](../framework-integration/lessons-learned.md)).

## Decision 1: Drop Proxmox/LXC/Terraform for `pve-framework`, rebuild bare-metal Ubuntu 26

Context: the recurring "probabilistic Vulkan crash" characterized at
length in `findings-plan.md` turned out to be the kernel OOM-killer
hitting `llm-gpu-stack`'s 8GB LXC memory ceiling — a ceiling that governs
none of the actual GPU/GTT memory the model and KV cache use (that's
`ttm.pages_limit`, a separate, host-kernel-level boundary). The LXC
memory ceiling was pure redundant risk: a second number to size correctly
with no corresponding benefit, because GPU/GTT allocation bypasses it
entirely.

Separately, the operator's stated purpose for this hardware is one
flexible GPU resource — LLM inference or ComfyUI generation, coding or
chat — not two permanently and independently partitioned services. Two
static LXC containers, each with its own guessed memory ceiling, is a
model for two things that coexist and both need guaranteed resources.
That isn't this box's actual use pattern.

Decision: rebuild `pve-framework` as bare-metal Ubuntu 26.04 LTS, no
hypervisor, Ansible-managed, no Terraform. The operator explicitly
confirmed migration effort is not a constraint here — the goal is the
most flexible, reliable path forward, not the cheapest diff from the
current state.

## Decision 2: Ubuntu 26.04 LTS as the target distro

Context: `docs/framework/proxmox-strix-halo-setup-notes.md` §5 already
established that ROCm/HIP and current-Mesa Vulkan are meaningfully easier
to get working on Ubuntu than Debian for this hardware (Strix Halo /
`gfx1151`) — this was learned running Ubuntu-based LXC guests on a
Debian-based Proxmox host, so the comparison is already Ubuntu-vs-Debian
at the userspace level, not confounded by the hypervisor question.

Decision: Ubuntu 26.04 LTS, matching the guest OS already validated
inside the current containers (`mesa-vulkan-drivers 26.0.3-1ubuntu1`
confirmed live). Also matches the operator's stated reasoning: most
stable, most-documented platform going forward.

## Decision 3: Models live on NAS via NFS, not re-downloaded per rebuild

Context: models are large (tens of GB each), already downloaded once via
`hf download` on the Garuda desktop and rsync'd to `pve-framework`
directly in the current setup. Re-downloading on every future rebuild
would be wasteful and slow.

Decision: rsync models to the NAS (operator, underway) as the durable
source of truth; the rebuilt host mounts an NFS export rather than
holding a local-only copy. Detailed in `plan.md` §4.

## Decision 4: Terraform removed for this node; Ansible retained and adapted

Context: Terraform's role here was provisioning LXC containers via the
Proxmox API — an abstraction that no longer exists once there's no
hypervisor. Ansible's role was configuring those containers after
provisioning — that job still exists, just against a bare host instead
of an LXC guest.

Decision: remove all `pve-framework`-scoped Terraform (environments,
per-node secrets, network/storage configs, `PRODUCTION_NODES` entry —
`plan.md` §6), keep and adapt the Ansible roles that configure the
actual applications (`llm_gpu_stack`, `comfyui_stack`, the
`ai-services-stack` Compose deployment — `plan.md` §5). The
LXC-provisioning and Portainer-fleet-management roles
(`lxc_base`, `lxc_tun_device`, `portainer_*`, `docker_socket_proxy`)
simply stop being invoked against this host; they're still used by
`pve`/`pve-test-vm` and aren't touched.

## Decision 5: No containerization mandate — Docker only where it already fit

Context: the operator's constraint was specifically "nothing running
inside LXC-style containers," not "everything must be Dockerized."
Checking the actual roles: `llm_gpu_stack` and `comfyui_stack` are both
already native (no Docker) systemd services inside their current LXC
containers — only `ai-services-stack` is Docker Compose based.

Decision: don't force Docker onto the two GPU roles just for
consistency. Move them to bare metal as native systemd services (their
current shape, minus the LXC-passthrough-check tasks that no longer
apply). Keep `ai-services-stack` as Docker Compose, since that's already
the right fit and changes nothing but the host. Revisit only if a
concrete reason to containerize the GPU services shows up (none has so
far) — see `plan.md` §3, §5.

## Decision 6: LLM service needs a real process-supervision fix, not just a host move

Context: while root-causing the crash, it emerged that the current LLM
service (LM Studio) isn't managed by systemd or any persistent unit at
all — it runs as a child of whatever SSH/ansible session started it
(visible directly in the OOM logs: `task_memcg=.../session-c71.scope`).
That's fragile independent of Proxmox: it won't survive a host reboot
without a manual re-run, and "which session started it" isn't tracked
anywhere.

Decision: use this migration as the point to fix that properly — a real
systemd unit supervising the LLM service on the new host, not a rerun of
the current ad hoc pattern. `plan.md` §5 leaves open whether that unit
runs LM Studio (the empirically validated winner per `findings-plan.md`)
or a native `llama-server` build (the role's original approach, now that
both known failure modes — memcg ceiling, Vulkan batch/ubatch sizing —
are understood and avoidable); either way, it must be a supervised
service, not a session-scoped process.

## Decision 7: Documentation split — lessons-learned vs. carried-forward reference

Context: `docs/framework-integration/` and `docs/framework/` hold ~10
documents accumulated across the Proxmox/LXC chapter. Not all of it is
actually *about* Proxmox — model selection, tool-calling harness results,
sampling configuration, and VS Code client integration are AI-stack-level
findings that remain fully valid regardless of host platform.

Decision: split rather than blanket-archive.
- Genuinely Proxmox/LXC/Terraform-specific material (GPU-passthrough
  container topology, unprivileged bind-mount ownership, the
  credential-wrapper generalization pattern, SDN/VLAN networking for
  this node, the host-wide-OOM incident that drove the
  one-container-per-workload-class decision) moves into
  `docs/framework-integration/lessons-learned.md` as a single
  consolidated historical record.
- AI-stack-level findings (`findings-plan.md`,
  `vscode-tool-calling-investigation-2026-07-19.md`,
  `docs/framework/model-quality-and-vuln-bench-2026-07-17.md`,
  `docs/framework/comfyui-image-video-gen-findings.md`'s application-level
  content) stay in place and are referenced directly from `plan.md`,
  not duplicated.
- `docs/framework-integration/README.md` is updated to mark that
  workspace historical for the *hosting* question while pointing at
  which documents inside it remain live for the *AI-stack* question.
- The uncommitted, already-superseded `findings-plan-revised.md`
  (explicitly rejected by the operator earlier in favor of
  `findings-plan.md` as canonical) is deleted rather than carried
  forward or archived — it was never committed and never became the
  reference.

## Decision 8: `ai-services-stack` moves with the host, as a Docker container

Context: open question in `plan.md` §8 — OpenWebUI/SearXNG isn't
GPU-bound, so it wasn't a hard dependency of this migration either way.

Decision: it moves along with `pve-framework`, as a Docker container on
the new bare-metal host — same Compose shape it already has today
(Decision 9 in the old `decisions.md`), just a different host underneath.
No longer an open question.

## Decision 9: Secrets and the credential wrapper are repurposed, not retired

Context: `with-secrets-prod-framework` currently bundles two jobs: (1)
decrypt/merge `terraform/secrets.pve-framework.enc.yaml` (today: a
Terraform API token and LXC root password — both Proxmox-API-specific,
and both genuinely disappear once there's no Proxmox API for this node),
and (2) gate mutating commands (`terragrunt apply`, `pct`/`qm` mutations)
behind `TASK_APPROVAL`. Losing job (1)'s current content doesn't mean the
underlying need goes away — Ansible will be directly managing real
service secrets on this host (Authentik OIDC client secrets, DNS API
tokens, LLM API keys), and job (2)'s principle (gate mutations against a
real host behind explicit approval) matters *more* once Ansible is the
primary tool touching a live host, not less.

Decision, three parts:

1. **`terraform/secrets.pve-framework.enc.yaml` is repurposed, not
   deleted.** Same filename, same SOPS/age mechanism, same "merge with
   common secrets on top" pattern (`docs/reference/secrets-management.md`)
   — nothing about that mechanism was ever Proxmox-specific, it's
   encrypted YAML keyed by hostname. Content shifts from Proxmox-API
   identity secrets to this host's own service secrets.
2. **Authentik/DNS integration needs no new mechanism.** OIDC client
   secrets for services like OpenWebUI already live in
   `terraform/secrets.common.enc.yaml` (old `decisions.md` Decision 8 —
   Grafana/Portainer/Harbor already work this way), and Ansible already
   decrypts that file today. Pointing Ansible at a bare host instead of
   an LXC guest changes nothing here.
3. **The wrapper is repurposed, not deleted.** Same shape — decrypt
   secrets, classify commands, `TASK_APPROVAL` gate, chat-based preflight
   approval — but `classify_command()` needs new read-only categories
   for an Ansible-managed host instead of a Terraform/Proxmox-API target
   (`ansible-playbook --check`, `systemctl status`, `docker compose
   config`/`logs`), otherwise every routine operation becomes
   "ambiguous → mutating" now that Ansible is the primary tool rather
   than a secondary one behind Terraform. Mutating still covers actual
   playbook applies, `systemctl restart`/`stop`, `docker compose
   up`/`down`, and anything writing a secret into place.

`CLAUDE.md`'s Production Nodes section needs a matching update:
`pve-framework` keeps the same access discipline, just redefined as "this
host gets the same approval-gated treatment as any other production box"
rather than "has a Proxmox API token."

**Deferred to `plan.md` §8 Phase 7/8**, not implemented now — there's no
bare-metal host yet to validate the new classifier categories against,
and the current wrapper is still needed for the existing Proxmox
install until the migration actually happens.

## Open (not yet decided)

- The GPU-workload mutual-exclusion mechanism for LLM vs. ComfyUI
  (`plan.md` §8 Phase 5) — `dual-workload-gateway-design.md` is the
  starting point, not yet built.
