# media-stack-v2 (planning workspace)

Status: **plan written, not yet built.** Replacement for legacy
`media-stack` (VMID 102, plain LAN, Jellyfin only via Portainer). New
architecture: two separate contract-driven stacks (`jellyfin-stack`,
`immich-stack`) in a new `media_seg` zone (VLAN 80), both behind Authentik
SSO, existing Jellyfin users/watch-history migrated across, legacy
`media-stack` decommissioned only after the new one is verified.

Supersedes `docs/immich-stack/` -- see that workspace's README for why.

Written with `.github/prompts/plan-change.prompt.md` per
`docs/agent-design/step-packet-schema.md`. See `plan.md` for the full
step-by-step plan, research, and decisions.

## Quick facts

| | |
|---|---|
| Zone | `media_seg`, VLAN 80, `192.168.80.0/24`, gateway `192.168.80.1` (new) |
| `immich-stack` | candidate `192.168.80.10`, VMID `80010` |
| `jellyfin-stack` | candidate `192.168.80.11`, VMID `80011` |
| Storage | NFS, matching legacy media-stack's existing `/nas-media/` pattern -- not local `docker_storage_size` |
| Dedup | none needed -- Immich's built-in Duplicates Utility |
| Immich SSO | native OAuth (no plugin) |
| Jellyfin SSO | `jellyfin-plugin-authentik` (scottfridwin) |
| Auth wiring | reuses this repo's existing `edge.yaml` + `reconcile-authentik-edge.py` pattern (already live for monitoring-stack/Grafana) -- not a manual click-through in the Authentik UI |
