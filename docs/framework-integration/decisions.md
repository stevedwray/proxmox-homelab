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

## Decision 3: Storage profile — keep LVM-thin, do not require ZFS (proposed)

Context: `pve-test-vm`'s storage profiles (`platform-zfs`, `durable-zfs`)
assume a ZFS backend (`infrastructure-containers`). `fe-pve` has a single
1.8TB NVMe already fully committed to `pve-data` (LVM-thin) with no ZFS
pool. Building ZFS would mean repartitioning the NVMe — destructive, and
this box already has real work on it (the AI-OS bake-off results,
`/data/ai`, `/srv/ai-stack`).

Decision: add `terraform/lxc/storage/pve-framework.yaml` mirroring the legacy
`pve-test.yaml` shape — `platform-default`/`platform-zfs`/etc. profile
names kept for `stack.yaml` compatibility, but all mapped to `local-lvm`
(no ZFS backend defined). Matches the existing precedent: `pve-test.yaml`
already does exactly this for a host without ZFS.

Rationale: avoids a destructive repartition for no functional requirement
— LVM-thin is a supported profile target already, just under different
profile names on `pve-test-vm`. Revisit only if snapshot/send-receive
features become a real requirement for this box specifically.

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

## Decision 5: GPU-passthrough container topology — one exception LXC, not one-per-service (proposed)

Context: `docs/design/architecture.md` NFR-02 says "one service per LXC —
no co-location of unrelated services." `docs/framework/llamacpp-router-mode-deployment.md`
argues the opposite for GPU passthrough specifically: the expensive part
(`/dev/kfd` passthrough, AppArmor/cap-drop, ROCm/Vulkan driver install) is
a **container-level** cost, not a per-model or per-service one, and router
mode already lets one `llama-server` process serve many models.

Decision: one dedicated GPU-passthrough LXC (`llm-gpu-stack`, replacing
ad hoc 9000/9001) hosts `llama-server` in router mode plus the standalone
embedding-model process described in that doc. Every other AI-stack
component (OpenWebUI, n8n, SearXNG, Postgres, Redis, Qdrant/Chroma) gets
its own LXC, in `ai_seg`, following NFR-02 normally — none of them need
the GPU.

Rationale: treats GPU passthrough as a narrow, explicitly-declared
exception to NFR-02 (the resource being shared is the physical device, not
general "unrelated services"), rather than either abandoning NFR-02
site-wide or fighting the router-mode doc's already-validated reasoning
for co-locating models.

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
