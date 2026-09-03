# media-stack-v2 (planning workspace)

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
all -- plain operator instructions instead: `media-v2-02-scaffold`
(running `scaffold-stack.sh` directly) and
`media-v2-06-jellyfin-sso-plugin` (a UI-only procedure, no config-file
or API path). Every real step block is unconditionally meant for the
local model to run via `implement-step`, which writes its hand-back
into this file -- see the Status section below.

## Quick facts

| | |
|---|---|
| Zone | `media_seg`, VLAN 80, `192.168.80.0/24`, gateway `192.168.80.1` (new) |
| Stack | one combined `media-stack-v2` (Jellyfin + Immich, one LXC) -- candidate `192.168.80.10`, VMID `80010` |
| Storage | NFS, matching legacy media-stack's existing `/nas-media/` pattern -- not local `docker_storage_size` |
| Dedup | none needed -- Immich's built-in Duplicates Utility |
| Immich SSO | native OAuth (no plugin) |
| Jellyfin SSO | `jellyfin-plugin-authentik` (scottfridwin) |
| Auth wiring | **not** a drop-in -- `discover-authentik-edge.py` has a hardcoded per-`(stack, route)` whitelist (6 existing entries: Harbor/Grafana/Portainer/Technitium/OpenWebUI/OpenSearch), each with its own redirect-URI branch. Adding Jellyfin+Immich means editing that shared script carefully, not just writing an `edge.yaml`. |
| Legacy media-stack | stays running, untouched. Not destroyed, not scheduled for retirement by this plan. |
| NAS rule | resolved 2026-09-04: `192.168.1.3`, flat LAN (not a zone), tcp+udp/2049 -- was a placeholder before, now real values in media-v2-00 |
| IP/VMID free? | confirmed 2026-09-04 via read-only production API check against `pve`: `192.168.80.10`/`80010` not in use by any LXC or QEMU guest |
| GPU passthrough | still open -- legacy Jellyfin's (VMID 102) hardware transcoding status not yet checked (`pvesh get /nodes/pve/lxc/102/config`), deferred by operator 2026-09-04 |

## Step status

Updated by the local model's hand-back after each `implement-step` run
(see `.github/prompts/implement-step.prompt.md`) -- the actual edit made
and the actual gate results, not a summary from chat. Read this before
authoring or approving the next step.

- `media-v2-00-create-media-seg-zone`: not started
- `media-v2-01-stack-request`: not started
- `media-v2-02-scaffold` (operator step, not run via `implement-step`): not started
- `media-v2-03-edge-yaml`: not started
- `media-v2-04-extend-oidc-whitelist`: not started
- `media-v2-05-immich-oauth-config`: not started
- `media-v2-06-jellyfin-sso-plugin` (operator step, not run via `implement-step`): not started
- `media-v2-07-bring-across-existing-users`: not started
