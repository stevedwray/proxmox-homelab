# 13 — Tier 3 backlog

**When:** as time allows, after plans 01–12. These are scoped, not planned
step by step. Each needs its own workspace or plan when picked up, per
`docs/agent-design/README.md`. Effort is working time; "first step" is the
concrete thing to do first.

Items marked **(new)** were found while writing plans 01–12 on 2026-09-28.

## Security and exposure

| # | Item | Effort | Value | First step |
|---|---|---|---|---|
| 13.1 | Triage Harbor's Critical CVEs on the Greenbone and OpenSearch images (memory `project_harbor_vuln_remediation_status`, Round 3) | 1–2 h | Medium | Grafana "Harbor CVE inventory" → filter severity Critical, projects `dockerhub`/`greenbone` → list image:tag + CVE + fix-available |
| 13.2 | **(new)** LAN → zone trust model. MikroTik zones only deny *outbound*, so every LAN device reaches every zone service port directly. Plan 01 closed it for the arr apps only | 1 session (design) | Medium | New workspace `docs/lan-zone-trust/`: list every zone service port that has no login of its own (e.g. `curl` each LXC's published ports from the LAN), then decide default-deny LAN → zones plus explicit allows, vs per-service fixes |
| 13.3 | **(new)** Five hosts (`authentik`, `netbox`, `graylog`, `wazuh`, `opensearch` stacks) `docker login` to Harbor as **admin**. Give them a pull-only robot instead | 1–2 h | Medium | Create robot `pull-hosts` (project-level pull on `dockerhub`, `ghcr`, `lscr`, `library`), add `HARBOR_PULL_ROBOT_USER/PASSWORD` to `services/harbor`, switch the five `printf … docker login` tasks |
| 13.4 | Grafana TLS on the LXC itself (`docs/code-cleanup/sprint-plan.md` Deferred). Today TLS ends at Traefik, and Traefik → `192.168.20.12:3000` is plain HTTP on mgmt_seg | 1–2 h | Low | Issue a step-ca cert for `monitoring-stack` (same pattern as node_exporter's TLS), set `GF_SERVER_PROTOCOL=https`, change the edge backend URL to `https://` (note: Traefik can't skip backend verification, memory `reference_traefik_no_insecure_backend_tls`, so the step-ca root must be trusted by Traefik) |

## Reliability and operations

| # | Item | Effort | Value | First step |
|---|---|---|---|---|
| 13.5 | **(new)** Route Proxmox's own notifications (backup failures, etc.) to Discord too. Today `mail-to-root` via sendmail, delivery unverified | 30 min | Medium | pve and pve-tiny GUI → Datacenter → Notifications → add a Webhook target with the same Discord URL as plan 07, and a matcher for severity ≥ warning |
| 13.6 | **(new)** Delete PBS backup groups of guests that no longer exist (after plan 03 prunes the rest) | 30 min | Low-Med | `pvesm list pbs-iscsi --content backup` on pve, compared with `pct list`/`qm list`; delete per group in the PBS GUI, one explicit decision each |
| 13.7 | **(new)** Read-only Proxmox API token for pve-tiny (and pve-framework) so live checks cover every node. Today the prod wrapper for pve-tiny has only the deploy token | 20 min | Low-Med | On pve-tiny: `pveum user token add <ro-user> readonly --privsep 1` + `pveum acl modify / --tokens '<ro-user>!readonly' --roles PVEAuditor`; store as `PROXMOX_READONLY_TOKEN_ID/SECRET` in `hosts/pve-tiny` (+ manifest) |
| 13.8 | **(new)** Foreverworld's exporters (`minecraft-status :8081`, `minecraft-jvm :9404`) and gaming-stack-lab cAdvisor are dead since the move to Wings. Plan 07 excludes them from alerting. Restore under Wings or drop the jobs and the `foreverworld.json` dashboard | 1 h (restore) / 15 min (drop) | Low | Decide: is the Foreverworld dashboard still wanted? |
| 13.9 | **(new, if found in plan 08)** The edge publish path doesn't remove stale Traefik files or Technitium records when a stack's `edge.yaml` is deleted | 1–2 h | Low-Med | Only if plan 08 Part B needed manual deletion: make `render-edge-traefik.py`/the proxy deploy remove generated files with no manifest, and the Technitium push delete records it previously owned |
| 13.10 | OpenSearch shows yellow (single node, replica shards unassignable). Set replicas to 0 | 15 min | Low | `PUT _all/_settings {"index":{"number_of_replicas":0}}` plus an index template default, via `deploy-opensearch-stack.yml` so it persists |
| 13.11 | Remove stale Portainer endpoints 4 (`gaming-stack`) and 5 (`torrent-stack`) | 10 min | Low | Portainer UI → Environments → delete both (legacy CTs 103/100 are stopped) |
| 13.12 | Stale `NETBOX_SUPERUSER_API_TOKEN` (403 live; legacy fallback only) | 15 min | Low | Find remaining readers (`git grep NETBOX_SUPERUSER_API_TOKEN`); if none needs it, drop it from the manifest and OpenBao |
| 13.13 | Pterodactyl egg 19: `AC_AI_PLAYERBOT_ADD_CLASS_ACCOUNT_POOL_SIZE` default is 1 in the Panel, 4 in the repo (server 4 already runs 4) | 10 min | Low | Panel → Nests → egg 19 → re-import `docs/gaming-stack-lab/` egg JSON, or edit the variable default to 4 |
| 13.14 | `harbor_postconfigure` still tells the operator to store the new robot secret in SOPS files | 10 min | Low | Change that debug message to `openbao_write.py services/harbor HARBOR_ROBOT_USER HARBOR_ROBOT_PASSWORD` |
| 13.15 | Remaining non-resolver `LAB_IP_DNS` references (dns-refactor Phase 6 cleanup; list in `daemon-json-audit.md` on branch `task/dns-stack-daemon-json-audit`) | 1 h | Low | Work through that audit's "Remaining dns-stack references" list |

## PentAGI leftovers deliberately kept by plan 08

| # | Item | Effort | First step |
|---|---|---|---|
| 13.16 | Harbor project `pentagi` + `cve_allowlist_pentagi.txt` + its `harbor_postconfigure_cve_allowlists` entry | 20 min | Confirm nothing pulls from `harbor…/pentagi/` (`git grep '/pentagi/'`), then delete the project in Harbor and the allowlist entry + file |
| 13.17 | Greenbone's `pentagi` GVM bridge user (`GREENBONE_PENTAGI_PASSWORD`, required by `deploy-greenbone-stack.yml:109`) | 30 min | Make the bridge optional in the playbook, delete the GVM user, then drop the secret |

## Feature work (from the original list)

| # | Item | Effort | Value | First step |
|---|---|---|---|---|
| 13.18 | deep-research: route CVE-class queries to `cve-mcp` (live at `192.168.50.10:8000/mcp`) and repo questions to `docs-rag` | 2–3 h | Medium | `docs/deep-research/plan.md` Phase 5 item 4. Add an MCP tool to the searcher agent in `terraform/lxc/ansible/files/deep-research-agent/src/tools/`, CVE searchers only |
| 13.19 | deep-research: decoupled job model (runs survive a browser disconnect) | 1–2 sessions | Medium (only if long unattended runs are wanted) | Phase 5 item 2: a job table + `POST /jobs` → id; the browser polls. Don't patch `textual-serve` |
| 13.20 | environment-isolation: move technitium-stack's state to per-environment directories (re-verified not started 2026-09-28) | 1 session | Low-Med | `docs/environment-isolation/plan.md` Phase 2 (state relocation, zero-diff plan gate) |
| 13.21 | torrent-stack: confirm whether lidarr's music import ran (4 artists), and decide on destroying legacy CT 100 (stopped) | 30 min | Low | Lidarr → Library Import → check unmapped folders under `/music` |
| 13.22 | reporting-platform Phase 3, coding-stack Phase 9, CyberSecEval full-scale campaigns, ARK hairpin NAT, mcp-stack infra-control tier, Harbor Stage E, stack-lifecycle-refactor | — | — | **Park.** Write "Parked 2026-09-28, see docs/catch-up/13" in each workspace's status line when next touched |
