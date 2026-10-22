# omada-controller (planning workspace)

Status: **Phase B deployed on `pve`; switch UI confirmation pending.** The
operator accepted the first-install check-mode limitation and approved the
deploy. The operator deferred the NAS copy and asked to continue with the
verified local `.cfg` and PBS snapshot. Weekly Auto Backup is not yet enabled;
switch details remain outstanding for Phase C. No controller major-version
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
| Controller | Omada **5.15.24.19**, Docker image pinned to `mbentley/omada-controller:5.15.24.19`, `network_mode: host`, healthy |
| Compose | `/srv/docker/omada/docker-compose.yaml`, project `omada`, volumes `omada_omada-data` (219 MB) + `omada_omada-logs`. Now Ansible-managed by `deploy-omada-controller.yml` |
| Database | MongoDB bundled in the controller image (127.0.0.1:27217); the controller is one service |
| Other | Portainer agent on :9001; 38 wired clients, 0 wireless |
| Logs | Controller syslog already reaches Graylog (`rewrite-omada-source` pipeline rule) |
| Backups | Daily `pve` vzdump job (11:00 → `pbs-iscsi`) includes CT 114. On-demand pre-adoption PBS snapshot `pbs-iscsi:backup/ct/114/2026-10-22T19:26:13Z` completed 2026-10-23 08:26 NZDT. Controller export exists at `~/Downloads/omada_backup_5.15.24.19_2026-10-22_19-27-43.cfg` (111,042 bytes, mode `0600`, SHA-256 `7c061442a8c4ae731addaec47bc63e48b24191379cc030dbd82c49cebfa453ab`). NAS copy unconfirmed; weekly Auto Backup not yet enabled |
| Missing | Exporter sidecars and scrape jobs, secrets entry, switch target list; node_exporter is installed but not yet added to monitoring scrape config |
| DNS | `omada.gibbsgreatly.xyz` → `192.168.1.4` (MikroTik static; that is management-stack, not .252 — unverified what answers there) |
| Scans | Already in GVM `EXTRA_HOSTS`; no Wazuh agent |

## Decisions made

- **Adopt in place, keep Docker, pin the version** (operator, 2026-10-23).
  Native `.deb` rejected: TP-Link ships no apt repo (manual download only),
  Debian 13 is not in its supported-OS list, so it would add manual patching
  without adding automatic updates.
- Stays on the flat LAN at `192.168.1.252` — the switches' management
  interfaces are on the default VLAN, so no re-adoption / inform-URL change.
- Monitoring: `omada_exporter` (controller API) + `snmp-exporter` (switch
  ports) + Graylog (already live).
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
- Steps 01-03 landed: stack dir + pinned playbook exist; not yet deployed.
  Both files passed local syntax and YAML checks. A read-only comparison of
  live and proposed Compose settings found no
  environment, volume, host networking, container name, or restart-policy
  difference. The exact `5.15.24.19` image is not cached locally, so the first
  deploy would pull it. The `latest` image currently has ID
  `sha256:ed9111379c2cc50ed3473b1d99c74dfabfed04ffda7a3f3161767e39a325d0b0`.
- Follow-ups: NAS copy, weekly Auto Backup, and each switch's
  model/firmware/management IP before Phase C.
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
  minutes. Switch Connected state still needs operator UI confirmation.
- Phase C preparation: `deploy-omada-monitoring.yml` exists locally and passed
  syntax check. It has not run. The `services/omada` OpenBao fields, switch
  target list, and monitoring scrape configuration are not yet in place.
