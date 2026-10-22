# omada-controller (planning workspace)

Status: **Phases B, C and D deployed on `pve`: controller upgraded 5.15.24.19 -> 6.3.0.45; switches Connected; omada_exporter + node_exporter scraped (up).** The
operator accepted the first-install check-mode limitation and approved the
deploy. The operator deferred the NAS copy and asked to continue with the
verified local `.cfg` and PBS snapshot. Weekly Auto Backup is not yet enabled;
the controller still reports an available update. No controller major-version
upgrade has been made.
Plan: [plan.md](plan.md). Branch:
`work/omada-controller-adoption`.

Goal: bring the existing Omada controller (manages two TP-Link switches) under
lab control — IaC-managed, version-pinned, backed up, and visible in
Grafana/Graylog — **without re-platforming it**.

## Current state (discovered read-only, 2026-10-23)

| Item | Finding |
|---|---|
| Guest | Unprivileged LXC, VMID 114 `omada-controller` on `pve`; 4 cores / 8 GB / 20 GB (2.6 GB used); `onboot`; vmbr0, `192.168.1.252/24` (flat LAN — the switches' management VLAN) |
| OS | Debian 13 |
| Controller | Omada **6.3.0.45** (upgraded 2026-10-23; was 5.15.24.19), Docker image pinned to `mbentley/omada-controller:6.3.0.45`, `network_mode: host`, healthy |
| Compose | `/srv/docker/omada/docker-compose.yaml`, project `omada`, volumes `omada_omada-data` (219 MB) + `omada_omada-logs`. Now Ansible-managed by `deploy-omada-controller.yml` |
| Database | MongoDB bundled in the controller image (127.0.0.1:27217); the controller is one service |
| Other | Portainer agent on :9001; 38 wired clients, 0 wireless |
| Logs | Controller syslog already reaches Graylog (`rewrite-omada-source` pipeline rule) |
| Backups | Daily `pve` vzdump job (11:00 → `pbs-iscsi`) includes CT 114. On-demand pre-adoption PBS snapshot `pbs-iscsi:backup/ct/114/2026-10-22T19:26:13Z` completed 2026-10-23 08:26 NZDT. Controller export exists at `~/Downloads/omada_backup_5.15.24.19_2026-10-22_19-27-43.cfg` (111,042 bytes, mode `0600`, SHA-256 `7c061442a8c4ae731addaec47bc63e48b24191379cc030dbd82c49cebfa453ab`). NAS copy unconfirmed; weekly Auto Backup not yet enabled |
| Missing in production | Exporter sidecars, scrape jobs, and secrets entry; node_exporter is installed but not yet scraped. Switch targets and scrape jobs are prepared locally, pending deployment |
| DNS / front door | `omada.gibbsgreatly.xyz` → `192.168.1.4` (MikroTik static). That is the legacy management-stack running Nginx Proxy Manager (proxy host 32): TLS-terminates with a Let's Encrypt wildcard `*.gibbsgreatly.xyz` (NPM `npm-3`, expires 2026-12-08) and proxies HTTPS to `192.168.1.252:8043` (backend self-signed cert not verified). Working, not stale; hand-built, not in IaC |
| Scans | Already in GVM `EXTRA_HOSTS`; Wazuh agent enrolled 2026-10-23 (see hand-backs) |

## Switches (operator-reported, 2026-10-23)

| Model | Management IP | Firmware | Omada Devices status |
|---|---|---|---|
| ES206X-M2 | `192.168.1.253` | `1.0.1 Build 20251128 Rel.41332` | Connected |
| ES210GMP | `192.168.1.254` | `1.0.8 Build 20260718 Rel.11174` | Connected |

## Decisions made

- **Adopt in place, keep Docker, pin the version** (operator, 2026-10-23).
  Native `.deb` rejected: TP-Link ships no apt repo (manual download only),
  Debian 13 is not in its supported-OS list, so it would add manual patching
  without adding automatic updates.
- Stays on the flat LAN at `192.168.1.252` — the switches' management
  interfaces are on the default VLAN, so no re-adoption / inform-URL change.
- Monitoring: `omada_exporter` (controller API) + Graylog (already live).
  SNMP was dropped 2026-10-23: the controller reports Easy Managed switches
  do not support SNMP.
- For this run, proceed from Phase A with the verified PBS snapshot and local
  `.cfg` export; NAS copy is deferred by the operator (2026-10-23). Weekly
  Auto Backup remains a follow-up and is not being treated as enabled.

## Findings that shape the plan

- The controller is on 5.15.24.19. TP-Link lists **6.3.0.45** as the fixed
  Linux and Windows build for CVE-2026-81531. Its 2026-10 advisories for
  CVE-2026-107795 and CVE-2026-102298 name Windows specifically. On
  2026-10-23 Docker Hub listed stable `mbentley/omada-controller:6.3.0.45`.
  Re-verify the exact tag, release notes, affected platforms, upgrade path,
  and switch firmware compatibility before Phase D.
- `omada_exporter` 0.12.0's README does not state Omada 6.x compatibility.
  Phase C therefore tests it on 5.15 first, establishing a working baseline
  before any 6.x upgrade.

## Hand-backs

- Phase A: root SSH to CT 114 worked with the existing lab key, so no key was
  installed. `pve` reported CT 114 running and `pbs-iscsi` active. The
  on-demand snapshot finished successfully and appears in `pvesm list`.
- Runtime preflight: controller image ID
  `sha256:ed9111379c2cc50ed3473b1d99c74dfabfed04ffda7a3f3161767e39a325d0b0`,
  host networking, and mounts
  `omada_omada-data:/opt/tplink/EAPController/data` and
  `omada_omada-logs:/opt/tplink/EAPController/logs`.
- Steps 01-03 landed: stack dir + pinned playbook exist and are deployed.
  Both files passed local syntax and YAML checks. A read-only comparison of
  live and proposed Compose settings found no
  environment, volume, host networking, container name, or restart-policy
  difference. The exact `5.15.24.19` image is not cached locally, so the first
  deploy would pull it. The `latest` image currently has ID
  `sha256:ed9111379c2cc50ed3473b1d99c74dfabfed04ffda7a3f3161767e39a325d0b0`.
- Follow-ups: NAS copy and weekly Auto Backup. Both switches were confirmed
  Connected in the Omada UI on 2026-10-23.
- Phase B check mode (2026-10-23): the first run stopped at a version-guard
  expression that returned a string; the guard was corrected to a boolean and
  passed on rerun. The rerun reported expected prospective DNS, CA,
  node_exporter package, rsyslog package/config, and apt changes, but stopped
  inside `lxc_base` because check mode does not install the missing packages
  before trying to start their services. A read-only audit confirmed both
  `prometheus-node-exporter` and `rsyslog` are absent, Docker is active, and
  `omada_omada-data` exists. No production change was made by check mode.
  The operator explicitly accepted this first-install limitation and approved
  the Phase B deploy.
- Phase B deploy (2026-10-23): `scripts/provision.sh --stack omada-controller`
  on `pve` passed (57 tasks OK, 30 changed, no failures). `lxc_base` installed
  node_exporter, TLS configuration, and rsyslog; the CA refresh restarted
  Docker. Compose pulled and started the pinned 5.15.24.19 image. Post-deploy
  checks: HTTP 200 on `:8043`, Docker health `healthy`, both original named
  volumes still mounted, Docker/node_exporter/rsyslog active, resolver still
  `192.168.1.1`, and two Graylog `source:omada` messages in the last 15
  minutes. The operator subsequently confirmed both switches Connected.
- Phase C preparation: `deploy-omada-monitoring.yml`, the operator-supplied
  switch target list, and the monitoring scrape jobs exist locally. Both
  affected playbooks passed syntax check; neither has run for Phase C. The
  `services/omada` OpenBao fields remain a prerequisite. The monitoring
  stack has not been redeployed with these jobs.
- Phase C sidecar (2026-10-23): `omada_exporter` 0.12.0 crash-looped on the 5.15
  controller (`slice bounds out of range [1:0]` in `getCid`; upstream fixed in
  v0.13.1, "fix getCid on new omada", 2024-08-05). The 0.12.0 pin came from a
  truncated GHCR tag list; bumped to 0.13.1 and redeployed. Also `omada_exporter`
  0.13.1 is the newest release; Omada 6.x compatibility is still unverified.
- Phase C deployed (2026-10-23): `omada_exporter` 0.13.1 running on CT 114
  (`:9202`, site `homelab`, 134 `omada_*` series: device CPU/mem/uptime/PoE,
  per-port link/speed/rx/tx/power, client counts). monitoring-stack redeployed
  (143 tasks, smoke test passed); VictoriaMetrics shows `up{stack="omada-controller"}`
  = 1 for jobs `node_exporter` (:9100) and `omada_exporter` (:9202). No MikroTik
  rule change was needed. SNMP dropped (Easy Managed switches do not support it).
  `services/omada` in OpenBao is at version 1. Remaining: dashboard + alerts
  (against the real metric names), weekly Auto Backup, NAS copy, Phase D upgrade.
- Phase D deployed (2026-10-23): fresh PBS snapshot + `.cfg` export taken first.
  Controller stopped; `mongodb-upgrade-3.6-to-8` container (via Harbor
  `dockerhub/` path) stepped MongoDB 3.6 -> 4.0 -> 4.2 -> 4.4 -> 5.0 -> 6.0 ->
  7.0 -> 8.0 and reported success (pre-upgrade backup `mongodb-preupgrade.tar`
  left in the data volume). Then `deploy-omada-controller.yml` with the one-time
  `-e omada_allow_major_upgrade=true` (run from repo root needs
  `ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg` for the roles path)
  recreated the controller on `6.3.0.45`: 50 tasks OK, healthy after 2 retries.
  Verified: HTTP 200, UI version 6.3.0.45, `tcp/29817` listening, site `homelab`
  shows 2 switches 0 disconnected, `omada_exporter` still returns 134 series,
  VictoriaMetrics `up` = 1 for both jobs. v6 popup "Port Access Required"
  (tcp/29817) needs no action (host networking, same LAN).
- Cleanup left: delete `mongodb-preupgrade.tar` from the data volume and the
  D0 PBS snapshot after a few days of stable running / nightly backups on 6.3;
  weekly Auto Backup confirmation; Grafana dashboard + alerts; controller
  compose image still pulls from Docker Hub, not Harbor (policy follow-up).
- Dashboard (2026-10-23): `Omada Network` Grafana dashboard
  (`terraform/lxc/stacks/monitoring-stack/dashboards/omada.json`, uid
  `omada-network`, 27 panels, all queries tested against live VictoriaMetrics)
  deployed via `provision.sh --stack monitoring-stack` (141 tasks OK, smoke test
  passed). No alerting exists in monitoring-stack, so alerts are not done —
  needs a decision on Grafana alert rules vs vmalert and a notification channel.
- Wazuh agent (2026-10-23): `wazuh_agent` role added to `deploy-omada-controller.yml`
  (group `lan` — the zone name GVM uses for the flat LAN; docker monitoring on,
  accepted root-equivalent docker.sock access for `wazuh` on this unprivileged
  single-workload CT; FIM on the two compose files only, not `exporter.env`).
  Deployed tag-scoped: `ANSIBLE_TAGS=wazuh_agent_rollout ./with-secrets-prod
  scripts/provision.sh --stack omada-controller` (21 tasks OK). Verified on the
  CT: agent active, connected to 192.168.40.15:1514, `docker-listener` started,
  FIM watching both compose files, `wazuh` in `docker` group. No firewall change
  needed (manager :1514/:1515 already reachable from the flat LAN). Benign
  repeating `syscheckd` errors for `/etc/vconsole.conf` and the dangling
  `wtmpdb-rotate.timer` symlink (Debian 13 base image paths in Wazuh's default
  watch list).
- DNS/TLS investigation (2026-10-23, read-only): the `omada.gibbsgreatly.xyz` name
  is served by NPM on management-stack (`192.168.1.4`, which docs/plan call
  "decomm / split"), not by the lab's Traefik. Nothing was changed. Retiring
  management-stack would take the front door with it; the controller itself
  keeps its self-signed cert on :8043 and devices use the IP directly, so
  switch management is unaffected either way.
