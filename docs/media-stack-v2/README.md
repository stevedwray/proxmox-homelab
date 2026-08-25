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

**All 8 steps carry literal content or exact command sequences, not
just decisions to make** -- rewritten 2026-08-25 so the plan is actually
usable by a local model via `implement-step`, not just by a frontier
one. Only `media-v2-06` (Jellyfin's SSO plugin) stays a manual
procedure, because that plugin is genuinely UI-only with no config-file
or API path.

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
