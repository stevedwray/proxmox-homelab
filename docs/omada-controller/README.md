# omada-controller (planning workspace)

Status: **planned, nothing applied.** Plan: [plan.md](plan.md). Branch:
`work/omada-controller-adoption`.

Goal: bring the existing Omada controller (manages two TP-Link switches) under
lab control — IaC-managed, version-pinned, backed up, and visible in
Grafana/Graylog — **without re-platforming it**.

## Current state (discovered read-only, 2026-10-23)

| Item | Finding |
|---|---|
| Guest | Unprivileged LXC, VMID 114 `omada-controller` on `pve`; 4 cores / 8 GB / 20 GB (2.6 GB used); `onboot`; vmbr0, `192.168.1.252/24` (flat LAN — the switches' management VLAN) |
| OS | Debian 13 |
| Controller | Omada **5.15.24.19**, Docker image `mbentley/omada-controller:latest` (6 months old), `network_mode: host`, healthy |
| Compose | `/srv/docker/omada/docker-compose.yaml`, project `omada`, volumes `omada_omada-data` (219 MB) + `omada_omada-logs`. Hand-written, untracked |
| Database | MongoDB bundled in the controller image (127.0.0.1:27217); the controller is one service |
| Other | Portainer agent on :9001; 38 wired clients, 0 wireless |
| Logs | Controller syslog already reaches Graylog (`rewrite-omada-source` pipeline rule) |
| Backups | Daily `pve` vzdump job (11:00 → `pbs-iscsi`) includes CT 114. No controller auto-backup configured |
| Missing | node_exporter, any metrics, stack dir / inventory / playbook, secrets entry, version pin |
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

## Findings that shape the plan

- The controller is on 5.15.24.19. TP-Link's 2026 advisories (CVE-2026-81531,
  -107795, -102298) list **6.3.0.45** as the fixed software-controller build;
  Docker Hub currently has `6.3.x` only as `beta-*`. Newest stable image tag:
  `6.2.14.11`. Version pages conflict across revisions — re-verify before
  acting. Upgrade is Phase D.
- `omada_exporter` 0.12.0's README does not state Omada 6.x compatibility.
  Phase C therefore deploys it on 5.15 first (known-good) so any 6.x breakage
  is visible and attributable to the upgrade.

## Hand-backs

_(none yet)_
