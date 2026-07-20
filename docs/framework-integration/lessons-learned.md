# Framework Desktop — Proxmox/LXC Era: Lessons Learned

This consolidates the durable, still-useful findings from `pve-framework`'s
Proxmox VE + LXC + Terraform chapter, now superseded for the *hosting*
question by [`docs/framework-ubuntu/plan.md`](../framework-ubuntu/plan.md).
Full original detail remains in this workspace's `decisions.md`,
`current-state.md`, `plan.md`, `post-reinstall-plan.md`, and
`docs/framework/proxmox-strix-halo-setup-notes.md` — this document is a
curated summary for anyone deciding whether a Proxmox/LXC-shaped approach
fits a future box, not a replacement for those originals.

**What this document is not**: it does not cover model selection, server
choice, tool-calling behavior, sampling configuration, or client
integration — those findings are AI-stack-level, not hosting-level, and
remain live in
[`findings-plan.md`](./findings-plan.md) and
[`vscode-tool-calling-investigation-2026-07-19.md`](./vscode-tool-calling-investigation-2026-07-19.md).

## 1. The incident that ended this chapter: LXC memory ceilings vs. unified GPU memory

The proximate cause of the move to bare metal. Six OOM kills across ~32
hours all showed the same signature: `oom-kill:constraint=CONSTRAINT_MEMCG,
oom_memcg=/lxc/50010`, killing `llama-server` at 7.9–8.1GB anon-rss — right
against `llm-gpu-stack`'s configured `memory: 8192` (8GB) LXC ceiling. This
had been misdiagnosed overnight as a "probabilistic Vulkan driver crash"
because LM Studio's own application log only shows the symptom
(`Engine protocol predict request failed: fetch failed`), not the cause —
finding the actual cause required cross-referencing the host's kernel log
(`journalctl -k` on the Proxmox host itself, not the container), and
accounting for a timezone offset between the container's clock (UTC) and
the host's (NZST, UTC+12) that initially obscured the correlation.

The core lesson, already predicted (but not yet connected to a real
incident) in `docs/framework/proxmox-strix-halo-setup-notes.md` §6:

> A container's own `memory:` cgroup limit is unrelated to GPU/GTT
> allocation — GPU/GTT allocations bypass it entirely, managed by the host
> kernel, not the container... Host is squeezed because AI has claimed
> most of the ceiling → unpredictable — ordinary Linux OOM-killer, which
> can kill anything on the box.

In other words: on a unified-memory APU, an LXC's memory ceiling is a
**second, redundant memory boundary** layered on top of the one that
actually governs GPU/model memory (`ttm.pages_limit`, a host-kernel-level
setting). It doesn't protect GPU memory at all — model weights and KV
cache bypass it — it only gates the service's own host-RAM-side overhead
(request buffers, tokenizer state), and if that ceiling is sized wrong
(as `8192` was here — never tuned for a 30B model at long context), the
failure is silent from the application's point of view and looks exactly
like a driver bug.

**Takeaway for any future container-based deployment on unified-memory
hardware**: if a per-container memory ceiling is used at all, verify it
against the service's actual anon-rss under real load, not a guessed
round number — and know that raising it doesn't cost you GPU memory
headroom, since that's a separate pool entirely.

## 2. GPU passthrough into unprivileged LXC

From `proxmox-strix-halo-setup-notes.md` §2 and Decision 5/11
(`decisions.md`):

- Proxmox's GUI GPU-passthrough option does not add `/dev/kfd` — it must
  be added by hand (`device_passthrough` in the container config).
- `device_passthrough` and related device-node-ownership fields are
  **root@pam-only** — no API token, regardless of RBAC role, can set
  them; they require a root SSH session running `pct set` directly (see
  `docs/reference/production-credentials.md` and the "Proxmox
  root@pam-only fields" reference).
- **One GPU-passthrough LXC per distinct GPU workload class, not one
  universal container** (Decision 5, revised with real evidence): running
  `llm-gpu-stack` and `comfyui-stack` in one shared GPU container was
  rejected after a real production incident — running both workloads at
  once produced a genuine **host-wide OOM that killed an unrelated
  container as collateral damage**. Two separate containers, each
  independently memory-bounded, contained that risk — at the cost of
  exactly the "guess two ceilings instead of one" problem that led to
  this migration (§1 above). This is the tension the bare-metal plan's
  Phase 5 (mutual-exclusion mechanism) has to resolve differently:
  without LXC's per-container containment, some other mechanism has to
  prevent the same host-wide OOM from recurring.
- **Unprivileged-container bind-mount ownership must match the host's
  subuid mapping** (Decision 11): container UID 0 maps to host UID
  100000 by default. Any `host_bind_mounts` target directory must be
  `chown 100000:100000` on the host side, or the container's remapped
  root silently has no write access despite looking like a normal
  `root:root 0755` directory from inside. Distinct from the related
  `vzdump` bug below — same root cause class (unprivileged UID
  remapping), opposite direction (writing *into* the container's mount
  vs. backing up *from* the host via `lxc-usernsexec`).
- **`vzdump` unprivileged-CT permission bug**: backing up an unprivileged
  LXC into a freshly-created `0700` directory fails via
  `lxc-usernsexec`; needs `0755`, matching Proxmox's own
  `/var/lib/vz/dump`. Confirmed as a latent Proxmox-task bug (hardcoded
  `mode: "0700"`), not specific to any particular storage backend.

None of this applies once GPU access is direct (bare-metal Ubuntu 26,
plain `/dev/dri`/`/dev/kfd` device files, no user-namespace remapping,
no passthrough plumbing) — recorded here so the reasoning isn't lost, not
because it needs to be re-solved.

## 3. Docker inside LXC

From `proxmox-strix-halo-setup-notes.md` §3: nesting Docker inside an
LXC container requires *both* the AppArmor-unconfined fix and the
cap-drop fix together — one without the other still fails. Moot once
Docker (where used at all — see `framework-ubuntu/decisions.md` Decision
5) runs directly on bare metal with no LXC layer beneath it.

## 4. Proxmox LXC vs. bare Ubuntu — the one performance data point

From `proxmox-strix-halo-setup-notes.md` §7 (small model, short-prompt
stress test, not re-validated at real scale): Vulkan throughput was
**~15-20% higher inside Proxmox's LXC** than on bare Ubuntu+Incus across
three independent runs, cause unconfirmed (plausibly a host kernel build
difference, `7.0.2-6-pve` vs `7.0.0-27-generic`, rather than the
container boundary itself). HIP was a dead heat either way, and
Docker-vs-native inside the LXC made no measurable difference for either
backend.

**Recorded honestly, not swept under the migration's motivation**: the
move to bare metal is justified by memory-model simplicity and
reliability (§1), not by this performance data — which, taken at face
value, points the other way for Vulkan specifically. Worth re-measuring
once the new host exists rather than assuming it resolves itself in
either direction.

## 5. Storage: LVM-thin over ZFS, and the single-NVMe split

Decision 3 (`decisions.md`): kept LVM-thin rather than adopting
`pve-test-vm`'s ZFS profiles, specifically because ZFS's ARC cache would
compete with GPU workloads for the same unified memory pool on a host
where memory headroom is already tightly managed — a cost that matters
more here than on a normal server. Also implemented: splitting
`/var/lib/vz` off the root filesystem so growable content (ISOs,
templates, backups, and a separate `/storage/models/*` bind-mount tree)
never shared space with the OS install. Surfaced, in passing, a latent
Proxmox-unrelated bug in a host-bootstrap playbook task that hardcoded
`mode: "0700"` on a `vzdump` dump-directory target (see §2).

This entire concern (ARC vs. unified GPU memory, thin-provisioning
headroom) is specific to running a ZFS-capable hypervisor storage layer
underneath GPU workloads — moot on a bare-metal install using whatever
filesystem the host OS puts on its own root/data disks directly.

## 6. Network: dedicated SDN VLAN zone (`ai_seg`)

Decision 4 (`decisions.md`, implemented and verified live): a new SDN
zone/VNet (`ai_seg`, VLAN 50) was created for this node's AI-stack
services rather than reusing an existing zone, onboarded through
`pvesh` with real `ping`+`tcpdump` verification against the physical
MikroTik/switch path. This is Proxmox SDN-specific mechanics; the
*network segmentation intent* (AI-stack services on their own VLAN,
still reachable from the shared platform's Traefik/Authentik/DNS) is not
Proxmox-specific and should be recreated at the switch/VLAN level for
the bare-metal host directly (a plain host NIC on the `ai_seg` VLAN,
no SDN zone object needed since there's no virtualization layer
managing it).

## 7. The production-credential wrapper generalization pattern

Decision 6 (`decisions.md`, implemented): when `pve-framework` needed
its own production-credential path, the fix was to generalize the
existing `with-secrets-prod` wrapper (`terraform/PRODUCTION_NODES` +
`scripts/with-secrets-prod-lib.sh`, parameterized by node) rather than
duplicate a second 150-line wrapper — avoiding the class of drift risk
already seen elsewhere in this repo when environment-selection logic
isn't uniform across stacks.

The mechanism itself (Terraform API tokens per Proxmox node) stops
applying once `pve-framework` isn't a Proxmox node — see
`framework-ubuntu/plan.md` §6 for the open follow-up decision on what
replaces it. The *principle* — generalize a shared gate instead of
copy-pasting a second one — is the durable part, independent of
Terraform, and should carry into whatever replaces the wrapper.

## 8. "Rebuild before onboarding, don't automate around ad hoc state"

Decision 7 (`decisions.md`, proposed and then followed): the original
Proxmox host had accumulated hand-tuned state (`ttm.pages_limit` set by
hand, guests built by hand) that wasn't reproducible from code. Rather
than writing Ansible to match that ad hoc state, the useful knowledge was
folded into Ansible roles and validated against a clean reinstall.

This is exactly the same discipline the Ubuntu 26 migration is now
applying a second time, one level up — see `framework-ubuntu/plan.md`
§9's rollback section: the current Proxmox install isn't touched until
the new bare-metal build has independently proven itself, and the useful
knowledge from this Proxmox chapter (this document, plus the carried-
forward technical requirements in `plan.md` §7) is the spec for the next
build, not something to be replicated as-is.

## 9. What's genuinely carried forward, not archived here

For completeness, since this document is specifically the *Proxmox/LXC*
lessons, not everything from the old workspace:

- Decisions 8, 9, 10, 12 in `decisions.md` (Authentik/OIDC integration
  approach per service, the ai-services-stack/n8n-stack dependency-based
  split, `llama-router`'s forced single-slot decode, VS Code
  Continue/Copilot BYOK client setup) are AI-stack or application-level,
  not Proxmox/LXC-specific, and remain fully applicable on bare metal.
  Not duplicated here — see `decisions.md` directly, or
  `findings-plan.md` for the parts that evolved further.
- `findings-plan.md`, `vscode-tool-calling-investigation-2026-07-19.md`,
  `docs/framework/model-quality-and-vuln-bench-2026-07-17.md`, and the
  application-level content of
  `docs/framework/comfyui-image-video-gen-findings.md` (model behavior,
  launch flags, upstream bug workarounds) are unaffected by this
  migration and remain the live reference.
- The unified-memory hardware findings in
  `proxmox-strix-halo-setup-notes.md` §6 and §8 (the `ttm.pages_limit`
  GTT-tuning mechanism, and the genuine Vulkan long-context ring-timeout
  bug at default batch sizes) are platform-independent kernel/driver
  findings, not Proxmox lessons — carried forward directly into
  `framework-ubuntu/plan.md` §7, not summarized again here.

## 10. Harbor as a registry cache — real mechanism found late, on the second check

Not a Proxmox/LXC-era finding (recorded here anyway since this is where
the operator flagged it) — a genuine mistake in this session's own
investigation, corrected before it caused real harm.

Setting up Docker on the new bare-metal host (`framework.gibbsgreatly.xyz`,
`docs/framework-ubuntu/`), the first check for "is this host wired into
the platform's shared caches the way everything else is" found
apt-cacher-ng in active use (`lxc_base` role) but concluded Harbor's
Docker registry-mirror capability was **unused anywhere in this repo** —
based on grepping for `enable_registry_mirror: true` (the flag gating
`docker_base` role's daemon-level `registry-mirrors` config) and finding
zero matches. That grep result was correct, but the conclusion drawn
from it was wrong: it answered "is the *daemon-mirror* mechanism used?"
not "is Harbor used at all?" — a real difference the operator caught by
being skeptical of a monitoring-stack-wide platform apparently never
touching its own registry.

**The actual mechanism**, found on a closer look: `deploy-monitoring-stack.yml`
pulls its VictoriaMetrics/Grafana/Python images through
`harbor.lab.gibbsgreatly.xyz/dockerhub/<original-image-path>:<tag>` —
explicit image-name prefixing through one of Harbor's proxy-cache
projects (`dockerhub`), not Docker's daemon-level `registry-mirrors`
feature at all. Confirmed live: `docker pull
harbor.lab.gibbsgreatly.xyz/dockerhub/library/hello-world` succeeds with
no authentication, TLS trusted automatically (routed through Traefik's
own Let's Encrypt cert, same as Harbor's web UI at the same hostname).

**Fixed for the new host**: ComfyUI's image reference in
`ansible/00-initial-setup/framework-desktop-comfyui.yml` changed from
`yanwk/comfyui-boot:rocm` to
`harbor.lab.gibbsgreatly.xyz/dockerhub/yanwk/comfyui-boot:rocm`,
redeployed, GPU access and HTTP health both reconfirmed working
afterward — same image, same content, now actually going through the
shared cache like everything else.

**Takeaway**: a clean grep result answering the literal question asked
("is X used?") isn't the same as verifying the actual behavior the
question was really about ("is this platform's shared caching being
used at all, by whatever mechanism"). When a repo has two different ways
to accomplish the same goal (daemon-level mirror vs. explicit path
prefix), checking only one and concluding "unused" for both is a real
gap — worth a second look specifically when the answer would otherwise
imply an established, multi-stack platform convention was never actually
followed anywhere.
