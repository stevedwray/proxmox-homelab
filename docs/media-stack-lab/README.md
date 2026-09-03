# media-stack-lab (planning workspace)

Status: **plan written, not yet built.** One combined stack -- Jellyfin +
Immich together in a single new LXC -- standing up **alongside** legacy
`media-stack`, not replacing it destructively. Existing Jellyfin
users/watch-history get brought across so the new stack is a real
alternative, but legacy stays running; retiring it is a separate,
future, operator-initiated decision this plan does not assume or
schedule.

Supersedes `docs/immich-stack/` -- see that workspace's README for why.

Written with `.github/prompts/plan-change.prompt.md` per
`docs/agent-design/step-packet-schema.md`. See `plan.md` for the full
step-by-step plan, research, and decisions.

**Every step block carries literal content or exact command sequences,
not just decisions to make** -- rewritten 2026-08-25 so the plan is
actually usable by a local model via `implement-step`, not just by a
frontier one. Two things in the plan are genuinely not step blocks at
all -- plain operator instructions instead: `media-lab-02-scaffold`
(running `scaffold-stack.sh` directly) and
`media-lab-06-jellyfin-sso-plugin` (a UI-only procedure, no config-file
or API path). Every real step block is unconditionally meant for the
local model to run via `implement-step`, which writes its hand-back
into this file -- see the Status section below.

## Quick facts

| | |
|---|---|
| Zone | `media_seg`, VLAN 80, `192.168.80.0/24`, gateway `192.168.80.1` (new) |
| Stack | one combined `media-stack-lab` (Jellyfin + Immich, one LXC) -- candidate `192.168.80.10`, VMID `80010` |
| Storage | NFS, matching legacy media-stack's existing `/nas-media/` pattern -- not local `docker_storage_size` |
| Dedup | none needed -- Immich's built-in Duplicates Utility |
| Immich SSO | native OAuth (no plugin) |
| Jellyfin SSO | `jellyfin-plugin-authentik` (scottfridwin) |
| Auth wiring | **not** a drop-in -- `discover-authentik-edge.py` has a hardcoded per-`(stack, route)` whitelist (6 existing entries: Harbor/Grafana/Portainer/Technitium/OpenWebUI/OpenSearch), each with its own redirect-URI branch. Adding Jellyfin+Immich means editing that shared script carefully, not just writing an `edge.yaml`. |
| Legacy media-stack | stays running, untouched. Not destroyed, not scheduled for retirement by this plan. |
| NAS rule | resolved 2026-09-04: `192.168.1.3`, flat LAN (not a zone), tcp+udp/2049 -- was a placeholder before, now real values in media-lab-00 |
| IP/VMID free? | confirmed 2026-09-04 via read-only production API check against `pve`: `192.168.80.10`/`80010` not in use by any LXC or QEMU guest |
| GPU passthrough | still open -- legacy Jellyfin's (VMID 102) hardware transcoding status not yet checked (`pvesh get /nodes/pve/lxc/102/config`), deferred by operator 2026-09-04 |

## Step status

Updated by the local model's hand-back after each `implement-step` run
(see `.github/prompts/implement-step.prompt.md`) -- the actual edit made
and the actual gate results, not a summary from chat. Read this before
authoring or approving the next step.

- `media-lab-00-create-media-seg-zone`: **done 2026-09-04.** Edited
  `terraform/lxc/network/pve.yaml`: added the `media_seg` SDN zone
  (attachments block), its member/container listing entry, and 4 policy
  rules (edge_seg->media_seg web UIs, media_seg->mgmt_seg Authentik,
  media_seg->192.168.1.3 tcp+udp/2049 NAS). No existing zone/rule
  touched -- insertions only. YAML parses cleanly.
  Gate note: the plan's literal gate command
  (`terragrunt --working-dir terraform/lxc/stacks run --all plan`)
  doesn't work as a real check in this repo -- it sweeps in
  pve-test-only scaffold stacks (net-*/test-*) that fail with
  "Failed to select workspace: EOF", unrelated to this change. Used
  this repo's actual documented pattern instead (see
  `docs/productionize-refactor/runbooks/`):
  `./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/gaming-stack-lab -no-color`
  (adjacent zone, closest analog). Ran it once with the edit and once
  stashed out (A/B) -- both produced the byte-identical
  `Plan: 6 to add, 0 to change, 0 to destroy`, a pre-existing
  state/workspace quirk in this stack's terragrunt setup, confirmed
  unrelated to this edit. Net result: zero incremental diff from
  `media_seg`'s addition. Separately worth noting: VLAN-type SDN zones
  aren't actually Terraform-managed in this repo yet
  (`terraform/lxc/network/NETWORK_CONTRACT.md` documents this as a known
  gap -- applied via `ansible/00-initial-setup/proxmox-sdn-setup.yml`
  instead), so the zone/VLAN creation itself was never going to appear
  as a Terraform-plannable resource regardless of gate wording.
  Not yet applied to production -- `terragrunt apply` and the real SDN
  zone creation are still ahead, out of scope for this plan-only step.
- `media-lab-01-stack-request`: **done 2026-09-04.** Created
  `terraform/lxc/stacks/media-stack-lab/stack-request.yaml`. Two real
  gaps found and fixed while authoring it (documented in the file's own
  header comment):
  - `playbook_content` was entirely missing from the plan's step block --
    `terraform/lxc/scaffold-stack.py` requires it unconditionally
    (`request["playbook_content"]`, no default). Without it,
    `media-lab-02-scaffold` would have failed immediately. Authored one
    modeled on `stack-request.example.yaml`'s minecraft-stack exemplar
    (lxc_base + docker_base roles, write compose, validate, up -d,
    wait_for) plus `deploy-netbox-stack.yml`'s secrets-`.env` pattern.
    Syntax-checked clean (`ansible-playbook --syntax-check`).
  - Jellyfin tag placeholder resolved to the real current stable
    (`10.11.11ubu2604-ls47`, confirmed via Docker Hub 2026-09-04), not
    left as a placeholder.
  - Renamed `DB_PASSWORD` -> `MEDIA_STACK_LAB_DB_PASSWORD` throughout
    (compose requirements + playbook's `.env` templating task) to match
    this repo's per-stack secret-naming convention and avoid a
    flat-environment collision risk. Not yet added to
    `terraform/secrets.common.enc.yaml` -- flagged in `contract_facts`,
    needed before any real deploy, out of scope for this step.
  All 4 gates pass: file exists, parses, NFS paths present, no hardcoded
  password.
- `media-lab-02-scaffold` (operator step, not run via `implement-step`):
  **done 2026-09-04, done by hand -- no `opencode`/local model, per
  explicit operator direction.** Wrote all 5 files directly:
  `stack.yaml`, `docker-compose.yml`, `STACK_CONTRACT.md`,
  `terragrunt.hcl`, `terraform/lxc/ansible/playbooks/deploy-media-stack-lab.yml`.
  Ran the same real validators the script would have --
  `validate-compose.sh --stack media-stack-lab` and
  `ansible-playbook --syntax-check` both pass; the `## Provides`/
  `## Dependencies` contract-section check passes (verified manually).
  `validate-stack-metadata.sh` passes but doesn't actually cover this
  stack -- its `ACTIVE_STACKS` list is fixed and has no way to check an
  arbitrary stack; flagging as a real repo-tooling gap, not something
  this step introduced. See `plan.md`'s hand-back on this step for the
  full detail.
- `media-lab-03-edge-yaml`: not started
- `media-lab-04-extend-oidc-whitelist`: not started
- `media-lab-05-immich-oauth-config`: not started
- `media-lab-06-jellyfin-sso-plugin` (operator step, not run via `implement-step`): not started
- `media-lab-07-bring-across-existing-users`: not started
