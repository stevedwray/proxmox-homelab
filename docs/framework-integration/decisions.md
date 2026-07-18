# Decisions — Framework Integration

Format follows `docs/dns-refactor/decisions.md`: context, decision, rationale.
Entries marked **(proposed)** are this plan's default — flag if you want a
different call before implementation starts; nothing here is executed yet.

## Decision 1: Treat `fe-pve` as a new, third Proxmox environment (proposed)

Context: the operator's framing ("develop against test, pivot to lab")
describes a *validation tier*, but Terraform/Terragrunt's unit of
environment is a Proxmox API endpoint. `fe-pve` is a distinct standalone
host (not clustered with `pve`, not nested inside it like `pve-test-vm`
is) — same relationship `pve-test-vm` has to `pve` today, just physically
separate instead of nested. It cannot literally "become" `pve` or
`pve-test-vm`; it needs its own environment identity in
`terraform/lxc/network/`, `terraform/lxc/storage/`, and
`terraform/lxc/environments/`.

Decision: introduce environment name `pve-framework`, following the existing
`pve` / `pve-test-vm` naming shape. Expected DNS name
`pve-framework.gibbsgreatly.xyz`.

Rationale: "test → lab" in the operator's request maps to *validation
rigor*, not to reusing an existing environment's identity — see Decision 2.
`pve-framework` keeps the existing `pve*` naming convention instead of introducing
an unrelated scheme (`fe-*`, `ai-*`) that the rest of the fleet doesn't use.

## Decision 2: "Test then lab" maps to validation tier, not environment identity (proposed)

Context: need to reconcile "initially develop against test, pivot to lab
quickly" with Decision 1's conclusion that `pve-framework` is always `pve-framework`.

Decision: `pve-framework` is validated the same way any Terraform/SDN change is
validated per `CLAUDE.md`'s Validation Tiers table — full teardown/rebuild
cycles on `pve-framework` itself while it's new and unstable (equivalent rigor to
`pve-test-vm`, just against `pve-framework`'s own state, since there's no separate
"test copy" of a physical box to rehearse against). Once a stack has
survived a full teardown cycle on `pve-framework` and its Ansible playbooks are
stable, it is promoted through the normal `work/* → stable → main` branch
model and becomes production-trusted on `pve-framework`, at that point being
treated with the same operational trust as `pve` ("lab"). There is no
separate rebuild event where the box changes environment identity —
"pivoting to lab" is a trust/promotion-gate event, not a re-provisioning
event.

Rationale: matches how every other stack in this repo is promoted
(`docs/workflow/branch-model.md`) rather than inventing a second promotion
model just for this box. Avoids the false idea that `pve-framework` needs to be
wiped and re-pointed at a different Terraform environment once it's
"production".

## Decision 3: Storage profile — keep LVM-thin, do not require ZFS (reaffirmed post-reinstall, 2026-07-18)

Context: `pve-test-vm`'s storage profiles (`platform-zfs`, `durable-zfs`)
assume a ZFS backend (`infrastructure-containers`). The original rationale
here (pre-reinstall) was avoiding a destructive repartition on a box that
already had real work on it — moot now that the box actually got wiped
and reinstalled, which would have been the natural point to switch if
ZFS were wanted.

Decision, reaffirmed rather than just carried over: still LVM-thin, not
ZFS, on the single 1.8TB NVMe (`terraform/lxc/storage/pve-framework.yaml`,
`platform-default`/`platform-zfs`/etc. profile names kept for `stack.yaml`
compatibility, all mapped to `local-lvm`).

Rationale: a genuinely new consideration surfaced on reconsideration, not
just the original "avoid a destructive repartition" logic — this box has
**unified memory** (Strix Halo APU), so GPU compute and host RAM draw from
the same physical pool. ZFS's ARC cache would compete directly with GPU
workloads for that pool, on a host where memory headroom is already
tightly and deliberately managed (see the GTT/`ttm.pages_limit` tuning and
the ComfyUI host-wide OOM incident in
`docs/framework/comfyui-image-video-gen-findings.md` §6c). On a normal
server ZFS's snapshot/checksum benefits usually outweigh the ARC cost;
here that cost is more real than usual, and there's no disk redundancy to
gain either way (single NVMe). Revisit only if snapshot/send-receive
features become a real requirement for this specific box.

**Forward-looking note (2026-07-18):** a second NVMe is planned for this
box, dedicated to model/artifact storage (LLM weights, ComfyUI
checkpoints, generated images/video) — separate from the boot/root drive.
When that lands, it's worth reconsidering ZFS *scoped to that drive only*
(a dataset with a capped ARC, isolated from the boot pool) rather than
applying this same host-wide answer to it by default — bulk model/media
storage benefits from checksumming more than the OS/container root does,
and an isolated ARC cap would contain the memory tradeoff instead of
letting it compete with GPU workloads host-wide. Not scoped or designed
yet; flagging so the reasoning doesn't have to be rediscovered.

**Implemented 2026-07-18: single-NVMe split so growable data never shares
space with root.** Operator raised a real concern separate from the ZFS
question — even staying on LVM-thin, `/var/lib/vz` (Proxmox's default
`local` dir storage, holding ISOs/templates/backups) was sharing the
*root* filesystem (`pve-root`), meaning growable content competed with
the OS for space. Fixed live, safely, because `pve-data` was confirmed at
0.00% usage (fresh install, nothing staged yet — this window closes the
moment anything real is stored). Referenced `pve`'s own live
`storage.cfg` as the naming/pattern precedent (`dir: storage-iso`,
`storage-template`, `storage-backup` on a dedicated pool, separate from
its root dataset) and adapted it to LVM:

- `pve-root` (96G) and `pve-swap` (8G) — untouched.
- Destroyed the empty `pve-data` thin pool; recreated a new plain ext4 LV
  `storage` (1000G) mounted at `/storage`, registered as three Proxmox
  `dir` storages matching `pve`'s naming — `storage-iso`, `storage-template`,
  `storage-backup` — plus plain (non-Proxmox-storage) bind-mount
  directories `/storage/models/{llm,comfyui}` (kept separate — llama.cpp
  wants a flat `.gguf` directory, ComfyUI wants its own structured
  checkpoints/vae/loras tree) and `/storage/artifacts` for generated
  output.
- Recreated the thin pool for container rootfs at the **same name**
  (`data`, now 700G instead of 1.71TB) — `local-lvm`'s existing
  `storage.cfg` entry needed zero changes, it just started working again
  once a pool with that name existed. Deliberately sized smaller than
  `storage` (700G vs 1TB) because it's thin-provisioned (overcommit
  headroom scales with realistic aggregate usage, not nominal per-container
  caps) while `storage` is a hard cap with no overcommit — the genuinely
  open-ended growth (models, generated media) needed the larger real
  allocation.
- `llm-gpu-stack`/`comfyui-stack` `stack.yaml`s updated to match: `rootfs_size`
  shrunk from 140G/250G down to 30G each (model weights no longer live
  inside the container's own rootfs), and `host_bind_mounts` added
  pointing at the new `/storage/models/*` and `/storage/artifacts` paths.
  `terraform/lxc/storage/pve-framework.yaml`'s `template_profiles` now
  point at `storage-template` instead of `local`.
- `local` (`/var/lib/vz` on `pve-root`) left registered in `storage.cfg`
  but no longer used for anything new — not removed, to avoid disturbing
  any Proxmox-internal assumption that expects a `local` storage to exist.

**Addendum: a real bug the restructure surfaced, not caused by it.**
Staging the custom Debian Docker template
(`ansible/00-initial-setup/build-debian-13-template.yml`) against the new
`storage-template` volume failed with `tar: ...tmp: Cannot open:
Permission denied` during the `vzdump`-based packaging step. Root cause:
that playbook's own "Ensure dump directory exists" task hardcoded
`mode: "0700"` on the target directory. `vzdump` backs up unprivileged
containers by wrapping `tar` in `lxc-usernsexec` (remapping container-uid
0 to host-uid 100000), and that remapped process has no access to a 0700
directory it doesn't (as its real, remapped identity) own. Isolated via a
direct `vzdump --storage <registered-id>` test (succeeded — Proxmox
treats a proper registered storage as trusted, bypassing this task
entirely) versus `--dumpdir <raw-path>` against any freshly-created 0700
directory, on *any* filesystem, including plain `ext4` root paths
unrelated to this restructure (failed identically) — confirming the bug
was this one task's hardcoded mode, not anything about `/storage`, ext4,
or LVM-thin specifically. Fixed to `0755`, matching Proxmox's own
`/var/lib/vz/dump`. Never surfaced on `pve`/`pve-test-vm` before now,
most plausibly because their target directories had already been touched
by something else before this task's assertion ever ran against them;
`pve-framework`'s fresh install made this the first genuinely first-touch
exercise of that exact path — a latent bug, not something this
restructure introduced.

## Decision 4: New dedicated SDN VLAN zone (`ai_seg`), not reuse of existing zones (implemented and verified live, 2026-07-17)

Context: `fe-pve` is flat-LAN today. To reach it through Traefik/Authentik/
step-ca/Technitium the way every other stack does, it needs to join the
SDN VLAN model (`docs/reference/sdn-segment-routing.md`). Two shapes are
possible: (a) trunk `fe-pve`'s NIC into the *same* VLANs `pve`/`pve-test-vm`
already use (`mgmt_seg`/`edge_seg`/`infra_seg`) and place AI containers in
whichever zone fits, or (b) give it one or more brand-new zones.

Decision: new zone(s), not reuse. Specifically `ai_seg` (new VLAN ID,
e.g. `50`, subnet `192.168.50.0/24`, gateway `192.168.50.1`) as the primary
zone for AI/LLM app containers, following the exact "adding a new segment"
pattern already documented in `docs/reference/sdn-segment-routing.md`.

Rationale:
- `docs/design/network.md` already reserves this shape: *"Future zones
  (Phase 06+): `app_seg`, `game_seg`"* — a dedicated app-tier zone for
  exactly this kind of workload was already anticipated, just not built
  yet. `ai_seg` is that zone, named for what's actually landing in it.
- NFR-03 ("default-deny east-west") and the whole zone model exist
  specifically so a new, less-trusted class of workload (a box just
  finished running ad hoc, privileged, unmanaged containers) doesn't get
  blanket access to `mgmt_seg` (Authentik, step-ca) or `infra_seg` (Harbor,
  NetBox) just by being on the same L2 segment as them.
- The MikroTik is the L3 gateway for every zone regardless of which
  physical Proxmox node the VLAN is trunked from — `pve-test-vm` proves
  this already works for a second node sharing the MikroTik's VLAN trunk.
  A new zone on a new node is the same mechanism, just a new VLAN ID
  instead of reusing 10/20/30/40.
- Keeps `fe-pve`'s eventual blast radius identical in shape to every other
  zone: Traefik (`edge_seg`) gets an explicit new cross-zone policy to
  reach `ai_seg`, `ai_seg` gets an explicit policy to reach `mgmt_seg` for
  Authentik forward-auth and step-ca ACME — nothing implicit.

Consequence that required operator action (out-of-band, per
`sdn-segment-routing.md`'s existing prerequisite for any new segment):
the MikroTik and the physical switch port `fe-pve` is connected to both
needed to carry the new VLAN tag as an 802.1Q trunk. **Done and verified
live 2026-07-17** — see `plan.md` Phase 1 step 1 for the full sequence,
including three distinct bugs found and fixed along the way (a RouterOS
safe-mode rollback, a missing `ether1` tag on the bridge-VLAN entry since
`fe-pve`'s traffic arrives via a different physical trunk port than
originally assumed, and a missing router input-firewall rule). Confirmed
with a live `ping 192.168.50.1` from `fe-pve` itself, verified via packet
capture (not just "ping succeeded") that ARP, ICMP, and the router's own
reply path all genuinely work. `ai_seg`'s values (VLAN 50, subnet, gateway)
are now confirmed-live facts, not a proposal.

## Decision 5: GPU-passthrough container topology — one exception LXC per workload class, not universal sharing (revised 2026-07-17 with real evidence)

Context: `docs/design/architecture.md` NFR-02 says "one service per LXC —
no co-location of unrelated services." `docs/framework/llamacpp-router-mode-deployment.md`
argues the opposite for GPU passthrough specifically: the expensive part
(`/dev/kfd` passthrough, AppArmor/cap-drop, ROCm/Vulkan driver install) is
a **container-level** cost, not a per-model or per-service one, and router
mode already lets one `llama-server` process serve many models.

Original decision (as first proposed): one single dedicated GPU-passthrough
LXC for everything GPU-bound on this box.

**Revised, based on what the operator actually built and validated**
(`docs/framework/comfyui-image-video-gen-findings.md`): ComfyUI was
deployed in its **own separate** GPU-passthrough container (9002,
`comfyui-gpu`), deliberately kept apart from the `llama.cpp` container
(9001) — not merged into one universal GPU container as the original
wording of this decision implied. The findings doc's own stated reasoning:
ComfyUI's dependency stack (PyTorch/ROCm, a large and version-sensitive
custom-node ecosystem) is heavier and more fragile than `llama.cpp`'s
minimal GGUF/HIP footprint, and its jobs saturate the GPU for long,
uninterrupted stretches — different operational risk profile from
`llm-gpu-stack`'s router-mode model-switching.

This was validated as the right call, not just a convenience: running
both workloads at once produced a genuine **host-wide OOM** that killed
an unrelated container as collateral damage (§6c of the findings doc) —
directly illustrating why these two GPU-bound workload classes need
independent memory/lifecycle containment, not shared residency.
`docs/framework/dual-workload-gateway-design.md` (design only, not yet
built) is the follow-on plan for managing exactly this: both containers
stay running, but a host-level gateway ensures only one *service* is
actually resident/active at a time, stopping the loser on every switch.

Revised decision: **one GPU-passthrough LXC per distinct GPU workload
class**, not one universal container and not one-per-service either.
`llm-gpu-stack` (LLM inference, router mode, multiple models) and
`comfyui-stack` (image/video diffusion) are two separate GPU-passthrough
containers. A third GPU-bound workload class would get its own container
only if it has a similarly distinct dependency/blast-radius profile from
the existing two — the bar is "materially different failure mode or
dependency stack," not merely "a different application." Every non-GPU
AI-stack component (OpenWebUI, n8n, SearXNG, Postgres, Redis,
Qdrant/Chroma) still gets its own LXC per NFR-02 normally — none of them
need the GPU, and none of this changes that.

Rationale: still treats GPU passthrough as a narrow, explicitly-declared
exception to NFR-02 (the resource being shared is the physical device),
but the "how many exception containers" question is now answered by
evidence (a real production incident) rather than the original
container-cost-amortization argument alone. Sharing GPU passthrough setup
cost across services is still the right instinct where the workloads are
genuinely similar (multiple LLM models in one router-mode process); it
stops being the right instinct once the workloads have different enough
dependency stacks and memory behavior that shared residency creates real
failure-containment risk.

## Decision 6: Generalize the production-credential wrapper instead of duplicating it (implemented 2026-07-17)

Context: `./with-secrets-prod` hard-enforced `TF_VAR_proxmox_node=pve` and
loaded `terraform/secrets.pve.enc.yaml` only (`CLAUDE.md`, Production
Credential Controls). As written it could not target `pve-framework` at
all. The operator confirmed this needs to be a real, independent
production path for `pve-framework` (its own Terraform token, its own
secrets), and flagged that secrets/environment handling has been a
recurring source of problems generally (see
[[feedback_env_isolation_rules]], [[project_environment_isolation_status]]
— the 2026-07-06 incident and the `technitium-stack` per-environment gap
both trace back to environment-selection logic that wasn't uniform across
stacks/tools). Copy-pasting a second 150-line wrapper for `pve-framework`
would reproduce that same class of risk — any future fix to the approval
gate or command classifier would need to land in two places and could
silently drift.

Decision: generalize instead of duplicate. Implemented:

- **`terraform/PRODUCTION_NODES`** — new file, one production-trust node
  name per line (currently `pve`, `pve-framework`). This is now the single
  place that declares which nodes are production; adding a node here is
  what makes both wrappers below treat it as production.
- **`scripts/with-secrets-prod-lib.sh`** — new shared engine holding all
  the logic previously duplicated-by-design inside `with-secrets-prod`
  (command classifier, `TASK_APPROVAL` gate, SOPS secrets merge, the
  `LAB_DOMAIN` contamination guard). It's parameterized by a
  `PVE_PROD_NODE` env var, not a hardcoded node name, and refuses to run
  at all for any node not listed in `terraform/PRODUCTION_NODES` — a typo
  can no longer silently invent an ungated "production" path.
- **`with-secrets-prod`** — rewritten as a 3-line entrypoint:
  `PVE_PROD_NODE=pve`, then exec the shared lib. Behavior for existing
  `pve` callers is unchanged (same file paths, same messages, same
  approval mechanics) — verified by running the read-only/no-secrets-file
  path before and after the refactor.
- **`with-secrets-prod-framework`** — new, matching entrypoint for
  `PVE_PROD_NODE=pve-framework`. Fails cleanly today with "production
  secrets file not found at `terraform/secrets.pve-framework.enc.yaml`" —
  expected, since Phase 0 hasn't issued this node a Terraform token yet.
- **`./with-secrets`'s safety rail** — generalized from a literal
  `"pve"` string comparison to `is_production_node()`, which reads
  `terraform/PRODUCTION_NODES` (falling back to blocking just `"pve"` if
  that file is ever missing, so the fail-safe direction is always
  "block", never "allow"). Both the production-node refusal and the
  `LAB_DOMAIN` contamination guard now cover `pve-framework` the same way
  they already covered `pve`. Verified: `PVE_ENV=pve` and
  `PVE_ENV=pve-framework` are both refused without `ALLOW_PVE=true`;
  `pve-test-vm` is unaffected.
- **`.env.pve-framework`** — new non-secret overlay (mirrors `.env.pve`'s
  shape). Node identity (`PROXMOX_HOST`, `TF_VAR_proxmox_node`,
  `TF_WORKSPACE`) is filled in now; `ai_seg`'s gateway/subnet vars are
  present but commented out until Decision 4's out-of-band MikroTik trunk
  work actually happens (plan.md Phase 1). `LAB_DOMAIN` is set to the
  shared `lab.gibbsgreatly.xyz`, matching Decision 2 — this node reuses
  `pve`'s existing Authentik/step-ca/Harbor/NetBox/Traefik rather than
  getting its own, so it shares `pve`'s domain rather than a separate one.

Not yet created: `terraform/secrets.pve-framework.enc.yaml`. There is
nothing real to put in it — the Terraform API token this file needs to
carry doesn't exist until Phase 0's
`ansible/01-base-system/terraform-token-management.yml` run against
`pve-framework` creates it. Creating an empty encrypted placeholder now
would be worse than not having the file: `with-secrets-prod-lib.sh`
already fails loudly and specifically when it's missing, which is the
correct state until Phase 0 happens.

Known rough edge carried forward, not fixed here: `.env.pve` and its
siblings are tracked in git despite the repo's blanket `.env.*`
`.gitignore` rule (the rule was added after those files were already
tracked; `.gitignore` doesn't retroactively untrack anything). The new
`.env.pve-framework` matches that same shape and will need `git add -f`
the first time it's committed, for the same reason. This is exactly the
kind of small, easy-to-miss inconsistency the operator flagged — worth a
follow-up pass across the whole `.env*`/secrets surface at some point,
separate from this workspace's scope.

Rationale for generalizing rather than deciding this per-node forever:
the next new production node (there will likely be one, given this
pattern) should cost one line in `terraform/PRODUCTION_NODES`, one new
`.env.<node>`/`secrets.<node>.enc.yaml` pair, and one thin wrapper file —
not a fork of the approval/classification logic. This is the concrete
fix for the operator's "secrets and environment handling has been a bit
of a problem overall" concern, scoped to what this integration actually
needs rather than a full audit of every `.env*` file in the repo.

### Addendum (2026-07-17, same day): secrets *content* restructuring

Once the wrapper mechanism above existed, the operator raised the deeper
problem it was built to eventually fix: `terraform/secrets.enc.yaml`
(base) and the per-environment files were carrying near-complete
duplicate copies of ~60 keys, not just the genuine per-node deltas. Aside
from the Proxmox token family, the operator's position was that nothing
else should differ between environments.

Verified by decrypting all three files and diffing key-by-key (values
compared programmatically, never printed): of ~60 keys, **48 were
byte-for-byte identical** across all three files already — pure
copy-paste duplication. Only a handful genuinely differed, and of those,
most looked like accidental drift (a stale copy left behind after one
environment's credential was rotated) rather than intentional design.

Executed:

- **`terraform/secrets.enc.yaml` → `terraform/secrets.common.enc.yaml`**
  (renamed, operator's choice) — now holds every secret shared across all
  environments (60 keys after the changes below), including
  `HARBOR_ADMIN_PASSWORD` and `PORTAINER_OAUTH_CLIENT_SECRET` (the
  operator judged these shouldn't differ either, correcting this doc's
  first-draft classification of them as per-node — see the live-state
  caveat below), plus three keys unified onto `pve`'s value after being
  identified as drift rather than intentional (`HARBOR_DOCKERHUB_USERNAME`,
  `HARBOR_DOCKERHUB_PASSWORD`, `MIKROTIK_READONLY_PASSWORD`/`_USER`).
- **`terraform/secrets.pve.enc.yaml`** and **`secrets.pve-test-vm.enc.yaml`**
  trimmed to 4 real deltas each: `PROXMOX_READONLY_TOKEN_ID`,
  `PROXMOX_READONLY_TOKEN_SECRET`, `TF_VAR_pm_api_token_secret` (the
  Proxmox token family), and `TF_VAR_lxc_password` (kept per-node by
  explicit operator choice — not flagged as drift).
- Consolidated the legacy `PVE_READONLY_TOKEN_*` naming onto the
  preferred `PROXMOX_READONLY_TOKEN_*` name (operator's call). This
  incidentally fixed a latent bug: `pve-test-vm`'s old effective merge for
  `PROXMOX_READONLY_TOKEN_ID/SECRET` was silently pulling `pve`'s own
  token through from the base file (since `pve-test-vm`'s file only had
  the legacy name), not `pve-test-vm`'s own — anything reading the
  "preferred" name against `pve-test-vm` would have silently used the
  wrong node's token.
- Removed `SOPS_TMP_TEST3` (dead test artifact) and two base-only copies
  of `TF_VAR_pm_api_token_secret`/`PORTAINER_OAUTH_CLIENT_SECRET` that
  were dead weight (never the real answer for any live environment).
- Verified via a before/after diff of the *merged effective* secrets per
  environment (old base+delta vs. new common+delta) that nothing changed
  unexpectedly — every diff matched one of the changes above, nothing
  else moved.
- Updated ~20 functional scripts, CI (`validate.yml` now decrypt-checks
  every `secrets*.enc.yaml`, not just the base file), `.pre-commit-config.yaml`,
  and the canonical docs (`docs/reference/secrets-management.md` rewritten,
  `CLAUDE.md`, `terraform/README.md`, `terraform/SECRETS_PVE_TEMPLATE.md`,
  both `STACK_CONTRACT.md` files, `docs/workflow/environments.md`,
  `docs/design/architecture.md`/`bootstrap.md`,
  `docs/reference/proxmox-terraform-user.md`, `router/README.md`) to
  match. Left historical/plan-archive docs (`docs/plan/tasks/*`,
  `docs/productionize-refactor/*`, `docs/threat-model/model.yaml`, etc.)
  untouched deliberately — they're point-in-time records, not live
  references.

**Live-state caveat, not yet resolved:** unifying `HARBOR_ADMIN_PASSWORD`
and `PORTAINER_OAUTH_CLIENT_SECRET` only changed the *file*. Each
environment's already-running Harbor/Authentik instance stores its own
copy of these internally at provisioning time, so `pve-test-vm`'s live
Harbor admin account and Portainer OAuth application still need a
separate reconciliation pass (reset the password; update the OAuth
client secret) to actually match the new common value — a file edit alone
doesn't retroactively change already-provisioned service state. Not done
as part of this pass; flagged for a follow-up task.

## Decision 7: Rebuild the Proxmox host before onboarding it, don't automate around current ad hoc state (proposed)

Context: `fe-pve`'s current state (apt repos fixed by hand, guests
9000/9001 built by hand, grub `ttm.pages_limit` set by hand) is not
reproducible from code (NFR-01/NFR-08). The operator already said this box
"is ultimately going to be rebuilt for productionising."

Decision: fold the useful *knowledge* from the manual bring-up
(`docs/framework/proxmox-strix-halo-setup-notes.md`) into Ansible roles,
then validate those roles against a clean reinstall — not against the
current hand-tuned state. `ttm.pages_limit`/apt-repo-fix become part of
the host-bootstrap role (parallel to `ansible/00-initial-setup`);
9000/9001 are retired once `llm-gpu-stack` replaces them, not carried
forward.

Rationale: matches how every other node in this repo is trusted — state
lives in Git, not in a box's memory. The manual work already done isn't
wasted; it's the spec for the Ansible role, exactly like the setup-notes
doc already reads (each numbered gotcha maps directly to a role fix).

## Decision 8: Authentik integration approach for AI-stack services (proposed, per-service)

Context: operator asked directly (2026-07-17) how Authentik should
integrate with the new AI-stack services (OpenWebUI, n8n, and others to
come), looking forward rather than just sequencing Phase 2's checklist.
Two mechanisms are available in this platform: Traefik forward-auth
(available, but not actually used by anything currently deployed) and
native OIDC via Authentik (the platform's actual precedent — Grafana,
Portainer, and Harbor all already integrate this way, with matching
`<APP>_OAUTH_*`/`<APP>_OIDC_*` secrets already in
`terraform/secrets.common.enc.yaml`). A third data point: Technitium also
uses native OIDC (`docs/dns-refactor/decisions.md`), but the operator
reports it's "a little clunky" and appears to be serving its direct-TLS
sidecar via a step-ca cert rather than going through Traefik —
operator-flagged as a real issue, explicitly deferred ("a problem for
another day"), not addressed by this decision.

Decision: default to native OIDC per service, matching the established
(not hypothetical) platform pattern — but treat each integration as
something to validate end-to-end (redirect URIs, cert trust chain,
group-claim mapping) before trusting it, specifically because Technitium's
own native-OIDC integration already shows this isn't automatically
painless on this platform. Fall back to Traefik forward-auth only where
native support is missing or clearly worse. Per service, as currently
understood:

- **OpenWebUI**: native OIDC — mature, well-documented support, commonly
  paired with Authentik specifically in the wider community. Follow the
  same shape as Grafana/Portainer.
- **n8n**: unconfirmed. Self-hosted/community n8n's native OIDC/SSO
  support has historically been an Enterprise-tier-only feature in some
  versions — don't assume either way; check n8n's current self-hosted
  docs when this stack is actually built (Phase 3). Traefik forward-auth
  is the fallback if native support isn't available or isn't good enough
  in the self-hosted edition.
- **SearXNG**: no native auth/user-account concept exists at all — this
  isn't a choice between forward-auth and OIDC, it's forward-auth or no
  gating (stay `ai_seg`-internal, no Traefik route) if any access control
  is wanted.
- **`llama-server` (the LLM API endpoint)**: does not go through Authentik
  at all, regardless of the above — it's a machine-to-machine API, not a
  browser login flow, so OIDC is the wrong tool. Uses `llama-server`'s
  own native `--api-key`/`--api-key-file` auth instead (confirmed
  supported — clients send `Authorization: Bearer <key>`). Whether it
  also gets a Traefik route (with the key enforced) or stays
  `ai_seg`-internal-only is still open — see plan.md's carried-forward
  open questions.

Rationale: "default to native OIDC" isn't a preference invented here — it's
already how every currently-deployed OAuth-capable service in this repo
works, so following it for the AI stack is consistency, not a new pattern
to prove out. The validation caveat exists specifically because the one
existing native-OIDC integration outside the original Phase 04 core
services (Technitium) already surfaced real friction — ignoring that
signal and assuming "native OIDC just works" for every new app would be
the wrong lesson to take from it.

## Decision 9: Ancillary AI-stack services split into three stacks by real dependency shape (2026-07-18)

Context: with `llm-gpu-stack`/`comfyui-stack` live, the remaining
project-brief scope (OpenWebUI, SearXNG, n8n, Postgres, Redis, Qdrant/
Chroma — already validated working together in the original bake-off
harness) needs to land as real Terraform/Ansible stacks. First instinct
was one-container-per-service, matching a (wrong) assumption about this
repo's convention; checking `monitoring-stack` (a real, existing stack)
showed it actually bundles four distinct Docker services — VictoriaMetrics,
Grafana, a Harbor-findings-exporter, cAdvisor — in one container via one
compose file. The real convention is "one container per cohesive stack,"
not "one container per service."

Decision: three stacks, split by actual dependency shape rather than by
topic grouping:

- **`ai-services-stack`**: OpenWebUI + SearXNG. Neither needs an external
  database — OpenWebUI ships its own embedded vector store/SQLite by
  default (basic RAG works before any dedicated vector-DB stack exists),
  SearXNG is stateless. SearXNG is reached over Docker's internal compose
  network only (`http://searxng:8080`), never published externally —
  matches the bake-off's own proven pattern (Postgres/Redis/Qdrant
  weren't host-published either; only what a human actually needs to
  reach was). OpenWebUI gets native OIDC per Decision 8, a real Traefik
  route (`openwebui.lab.gibbsgreatly.xyz`), `ai_seg` network.
- **`n8n-stack`**: n8n + Postgres + Redis — kept separate because n8n is
  the one service in this set with a genuine external-database
  dependency (Postgres backing it, matching the bake-off's own config);
  bundling it into `ai-services-stack` would tie an unrelated service's
  restart/failure lifecycle to n8n's DB.
- **`rag-stack`** (deferred, not yet scoped): Qdrant and/or Chroma, if/when
  OpenWebUI's embedded default vector store isn't enough. Not a
  prerequisite for `ai-services-stack` to be useful.

Rationale: matches the real, verified repo convention (`monitoring-stack`)
rather than an assumed one; splits along genuine dependency lines (does
this service need an external DB or not) rather than superficial topic
similarity ("AI stuff" vs "automation stuff"); keeps failure/restart
isolation where it actually matters (n8n's DB dependency doesn't couple
to OpenWebUI/SearXNG's lifecycle) without over-fragmenting into unnecessary
single-service containers where nothing actually needs the isolation.

## Decision 10: `llama-router` forced to single-slot decode (`--parallel 1`) (implemented and verified, 2026-07-18)

Context: Qwen2.5-Coder-32B-Instruct-Q4_K_M intermittently degenerated into
endless repeated-token garbage output (`??????...`), first noticed via
OpenWebUI on a Prolog quicksort prompt, later confirmed recurring live.
Root-caused by reproducing it directly: firing simultaneous requests at
`llm-gpu-stack` (mirroring OpenWebUI's real per-message pattern — main
chat completion + background title-generation + tag-generation, all
hitting the same loaded model at once) reliably corrupted output, while
the exact same prompts sent one at a time — via the raw API, bypassing
OpenWebUI and the chat template entirely — always worked. `llama-server`
defaults to 4 parallel decode slots; concurrent multi-slot decode is
corrupting shared GPU state on this HIP/ROCm (`gfx1151`) build.

Decision: added `llm_gpu_stack_parallel_slots: 1` (role default) and
`--parallel {{ llm_gpu_stack_parallel_slots }}` to the `llama-router`
systemd unit (`terraform/lxc/ansible/roles/llm_gpu_stack/`). Forces
single-slot serialized request handling — concurrent requests queue
instead of decoding in parallel.

Rationale: this is a single-user homelab; nothing needs true concurrent
serving, and losing a little latency on background title/tag generation
is a trivial cost against silently corrupted chat responses. Verified
fixed by re-running the exact concurrent-request reproduction after
deploy — all three (main-chat, title-gen, tag-gen) returned correct,
coherent output. Applies globally to whichever model the router currently
has loaded (`--models-max 1`), not just Qwen — DeepSeek/Llama were never
directly confirmed vulnerable to the same race, but the fix covers them
regardless.

Not fixed by this: a separate, second Qwen-only bug where responses come
back as valid but semantically wrong content (e.g. a background
title-generation task's JSON appearing as the main chat message, or a
hallucinated fake tool-call JSON blob in `content` when a real `tools`
schema is present but Qwen's GGUF template/parser doesn't structure it
into `tool_calls` correctly). Direct reproduction attempts (concurrent
and sequential, streaming and non-streaming, `/completion` and `/v1/chat/
completions`) could not reproduce the title/tag cross-talk at all —
current best guess is an OpenWebUI-side task/websocket routing bug, not
`llm-gpu-stack`. The tool-calling failure *was* reproduced directly
(confirmed Qwen-specific — Llama-3.3-70B-Instruct handles the identical
`tools`-schema request correctly, returning a proper `tool_calls` array)
and adding `--jinja` to the launch flags did not fix it. Both left open;
practical workaround is to prefer Llama-3.3-70B-Instruct for agentic/
tool-calling use (e.g. VSCode/MCP) until Qwen's template issue is
actually root-caused.

**Follow-up, 2026-07-19 — Qwen3.6 in Continue, root-caused and fixed:**
A similar-looking symptom recurred with the newly-added Qwen3.6-35B-A3B
(via Continue in VSCode, not OpenWebUI): agent tool-use attempts failed
repeatedly, and one reasoning trace appeared to reference unrelated
content from a completely different, much earlier API test — initially
suspected as genuine cross-session context contamination in
`llama-server`, a serious concern if true (raised and investigated
thoroughly given the implications). Ruled out via a systematic
plant-a-marker-then-probe test across all four resident models
(including cross-model swaps forced by `--models-max 1`) — zero
contamination reproduced anywhere. The actual cause, confirmed directly
from `llama-router`'s own request logs on `llm-gpu-stack`: the failing
request hit `truncated = 1` at `n_tokens = 8191` — it simply ran out of
the shared `--ctx-size 8192` budget mid-reasoning. Qwen3.6's reasoning
length is non-deterministic (the identical prompt replayed cleanly at
2785 completion tokens in one run, but ran to 6351+ tokens before being
cut off in the original incident) — verbose reasoning models can
legitimately think far longer than a simple instruct model on the same
prompt, and 8192 wasn't enough headroom. Fixed by raising
`llm_gpu_stack_ctx_size` to 32768 (GTT capacity analysis showed ample
room — see the memory constraint model referenced in
`post-reinstall-plan.md`). The "unrelated content in a reasoning trace"
observation that triggered the contamination investigation was most
likely the model's own tangential chain-of-thought rambling, not leaked
session data — no evidence of actual contamination was found anywhere
in this investigation, logs included.

## Decision 11: Unprivileged-container bind-mount ownership must match the host's default subuid mapping (gotcha, fixed 2026-07-18)

Context: staging new model weights directly into `llm-gpu-stack` (writing
into `/data/models`, the `host_bind_mounts` target for `/storage/models/
llm`) failed with `Permission denied` even as root inside the container,
even though the directory looked like a normal `root:root 0755` from
inside. `llm-gpu-stack` is `unprivileged: true` with no custom `idmap`
configured anywhere in its `stack.yaml` (only `device_passthrough` has
explicit uid/gid, and that's device-node ownership, unrelated to the
container's user-namespace mapping) — so Proxmox's standard default
applies: container UID 0 (root) maps to host UID 100000. The host-side
`/storage/models/llm` directory was owned by real host `root` (uid 0)
after the Decision 3 storage restructure, so the container's remapped
root wasn't actually the owner and silently fell into "other" (no write
bit under `0755`).

Fix: `chown -R 100000:100000 /storage/models/llm` run as real root
directly on the `pve-framework` host (not inside the container). Confirmed
working — subsequent `wget` from inside the container succeeded.

Rationale / distinct from the earlier `vzdump` unprivileged-permission bug
(same decisions doc, storage-restructure section): that one was a
host-side directory being accessed *from the host* via `lxc-usernsexec`
during backup; this one is a host-side bind-mounted directory being
written *from inside* the unprivileged container itself. Same underlying
cause class (unprivileged LXC UID remapping), different direction and
different fix shape — worth keeping both documented separately since the
symptom and fix look different enough that pattern-matching on one alone
wouldn't surface the other.

Follow-up not yet done: this same class of bug likely applies to any other
`host_bind_mounts` target for an unprivileged container (e.g.
`comfyui-stack`'s `/storage/models/comfyui` — not confirmed broken, since
its models were already staged and working by the time this was
diagnosed, but not confirmed correctly owned either). Worth either
auditing all current `host_bind_mounts` host-side directories for correct
`100000:100000` ownership, or better, codifying the `chown` as part of the
Terraform/Ansible flow that creates these bind mounts so it's never a
manual step again.
