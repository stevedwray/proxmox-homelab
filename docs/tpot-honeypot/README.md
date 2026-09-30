# tpot-honeypot

T-Pot CE (Telekom Security's multi-honeypot platform) running on a
standalone Raspberry Pi 5 — **not** a Proxmox guest, so it sits outside
`terraform/lxc/` and the `pve*` production-node controls, but it's a real
part of this home lab's network and its findings are meant to feed the
same `docs/threat-vuln-platform/` pipeline as Wazuh and GVM.

## Status (2026-09-30): fully live — host managed, ingestion working end-to-end (223k+ events)

This workspace exists because the host had drifted into "unlabeled
device on the LAN" status (see `docs/dhcp-refactor/current-state.md`,
which found it only as a fingerprinted `raspberrypi` DHCP lease) and its
log-ingestion tooling was split across two personal repos
(`tpotce-analysis`, `security-analysis`) neither of which is wired into
this lab's actual OpenSearch/threat-vuln-platform stack. See `plan.md`
for the full access review, the completed phases, and what's left.

**Done, same day**: DHCP lease labeled, host brought under Ansible
management (`unattended-upgrades`, persistent `journald`, a dedicated
SSH key for the sync job — all host-layer only, per the "Management
boundary" section in `plan.md`; T-Pot's own `~/tpotce/` application is
never touched), OpenBao credential entry written, and a
`tpot_findings_ingest` role deployed live to `secpipe-stack`.

**Five real bugs found and fixed to get the first data flow working**
(full diagnostic trail in `plan.md`): a missing MikroTik route from
`ai_seg` to T-Pot's flat client LAN (same class as the Wazuh port-55000
issue found earlier in this rollout); an IP address collision between
T-Pot's own internal Docker bridge networks and most of this lab's VLAN
addressing (T-Pot's `192.168.48.0/20` per-honeypot bridge silently
swallowed replies meant for `ai_seg`'s `192.168.50.0/24` — fixed with a
single host-layer route on T-Pot, no Docker/compose changes); a
`scripts/provision.sh` allowlist gap that silently no-op'd the whole
role; a `secrets/manifest.json` profile-completeness gap that
materialized an empty private key with no error; and a hardcoded
Elasticsearch major-version check that rejected T-Pot's real (and
healthy) ES 9.3.5. **Confirmed end-to-end**: 223,172 events synced with
0 errors, 223,173 documents verified live in `opensearch-stack`'s
`tpot-events-*` index.

**Live health check performed 2026-09-30** (see `plan.md` §Current
state for full detail):
- All 29 T-Pot containers up, internal ES cluster `green`, steady
  ~223k events/day ingested continuously since 2026-08-31 — the
  honeypot itself is working and has been for weeks.
- Found and fixed live: `journald` had no persistent storage, so a
  reboot (the operator power-cycled the Pi earlier the same day after
  losing connectivity) left zero log trail to diagnose it. Fixed by
  creating `/var/log/journal` and restarting `systemd-journald` —
  future reboots now leave a real trail.
- Found, not yet actioned: `LS_WEB_USER` (per-sensor Logstash
  ingest credential) is unset — irrelevant while there's no sensor;
  `BEELZEBUB_LLM_HOST`/`GALAH_LLM_SERVER_URL` point at `ollama.local`,
  which doesn't resolve on this host's DNS — moot, since neither
  container is actually deployed (LLM honeypots are a T-Pot
  non-standard-edition add-on this instance never enabled).

## What this is

- **Host**: `raspberrypi` / `tpot.gibbsgreatly.xyz`, `192.168.1.28`,
  Raspberry Pi 5, Debian 13 (trixie), single-homed on the LAN
  (`192.168.1.0/24`) only — deliberately not internet-facing. It
  catches LAN scanning/lateral-movement noise, not real internet
  attackers.
- **Access**: SSH alias `tpot` (`~/.ssh/config`), port 64295, user
  `steve`, key-only auth, full passwordless sudo. Web UI is on
  `:64297` (LAN-exposed) — `:64294` is a separate vhost for Logstash
  sensor ingest, not the browser UI (corrected 2026-09-30, see
  `plan.md` Phase 6). Internal Elasticsearch (`:64298`) and Kibana
  (`:64296`) are bound to `127.0.0.1` only — reachable exclusively via
  SSH tunnel, which is exactly how both existing sync scripts
  (`tpotce-analysis/tpot_es_sync.py`,
  `security-analysis/src/pipelines/tpotce/sync.py`) already work.
- **Not currently referenced anywhere else in `proxmox-homelab`** except
  as a deferred line item in `docs/threat-vuln-platform/plan.md` (the
  `tpot-events` row of the `*-events` index-family table) and the
  DHCP-refactor docs' unlabeled-lease finding.

See `plan.md` for the full write-up: how T-Pot itself works, everything
currently known about access to it, the gaps found, and the phased plan
to bring it under the same documentation/secrets/ingestion discipline as
every other lab component.
