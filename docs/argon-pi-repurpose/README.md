# Argon Pi repurpose plan

Status: planned, no host changes made. Survey: 2026-10-25. Execute one host at a
time, beginning with `argon-01` (`192.168.1.22`), then `argon-02`
(`192.168.1.23`). The first host already runs a 6.18 kernel; the second needs
the more difficult 2023-kernel migration. Both are Raspberry Pi 4 systems
running Debian 13 arm64
from an SSD exposed as `/dev/sda` through an Argon USB bridge. Keep the
existing SSD boot path; no reimage and no backup are requested.

## Intended end state

- Debian 13, patched and bootable from the existing SSD, with the current
  hostname/IP, `ansible` SSH access, passwordless sudo, working network and
  Technitium resolvers (`192.168.20.15`, `192.168.20.17`).
- Argon case fan/button service and the Raspberry Pi boot/firmware components
  needed for SSD boot. Do not remove these as generic legacy packages.
- Docker Engine and Compose plugin from the existing official Docker Debian
  repository. No application containers, images, volumes, or Compose projects
  except a newly deployed Portainer Agent. No local Portainer Server.
- Each Pi registered as a distinct Docker Standalone *Agent* environment in
  the existing infrastructure Portainer. Use its pinned agent version, currently
  `2.39.8`, and expose TCP 9001 only to that server. Do not expose Docker's TCP
  API or mount `/` into the agent.
- Existing lab host monitoring: node_exporter with hardware sensors and
  step-ca TLS/basic auth; SMART and apt metrics; Graylog forwarding; Wazuh;
  unattended security updates; Greenbone credentialed scan account. Verify
  these components after cleanup. Retain the root CA and certificate renewal
  timer. Remove old application-specific monitors and agents that are not part
  of this set, including runZero discovery and AttackIQ agents.
- Independent observer (added 2026-10-25, [icinga-pi-observability](../icinga-pi-observability/README.md)): a native
  Icinga 2 HA pair across both Pis (argon-01 config master), SmokePing and, later, Icinga Web on argon-01. Native
  Debian packages and systemd, no Docker; it must keep working without pve, Traefik, Authentik or OpenBao.
- No Pi-hole DNS/DHCP, Nginx Proxy Manager, Deluge, registry, Minecraft,
  MariaDB, Elasticsearch, Crawl4AI, Neo4j, AttackIQ, or local Portainer state.
  The Pi-hole query history is disposable. Greenbone's occasional Pi-hole
  queries do not block retirement (operator decision, 2026-10-25).

The Pis are not listed in `terraform/PRODUCTION_NODES`; direct Pi cleanup is a
separate host task. Any mutation of Portainer, monitoring, firewall/router, or
other services on a listed production node follows the repo's production
credential approval flow. Do not use `pve-test-vm` for validation.

## Survey facts and execution risks

| Item | argon-01 | argon-02 |
|---|---|---|
| SSD / use | Lexar 512 GB / 127 GB used | SSSTC 128 GB / 30 GB used |
| Running kernel | `6.18.23-v8+` | `6.1.21-v8+` built in 2023 |
| Apt updates at survey | 25 | 56, including security packages |
| SMART | passed, 48 °C, no logged errors | passed, 56 °C, no logged errors |
| Main residue | ~59 GB `/srv/minecraft`; ~22 GB `/var/lib/elasticsearch`; MariaDB; two live Pi-hole containers sharing storage | ~3.9 GB `/srv/docker` including a 3.5 GB Pi-hole query DB; NPM, Deluge, registry; seven failed NAS CIFS mounts |
| Failed services | Wazuh agent | seven media mount units |

Both hosts have obsolete Portainer Server and Agent containers in restart
loops. Their logs report an API client version too old for Docker 29.8.
The local `pihole` containers still publish TCP/UDP 53, but their recent daily
query logs contain only localhost. `argon-02`'s last recorded non-local
queries came from Greenbone (`192.168.70.11`) on 2026-10-23. The repo's
[LAN DNS cutover](../lan-dns-technitium/README.md) records DHCP pointing to
Technitium; check live DHCP/RA and static-client exceptions immediately before
removing Pi-hole.

The installed `raspberrypi-kernel` package is `1:1.20230405-1` on both and
has **no apt candidate newer than itself** in current sources. `argon-01`'s
running 6.18 kernel was installed by another path; `argon-02` still runs the
2023 kernel. The configured Raspberry Pi `trixie` repo does offer
`linux-image-rpi-v8` (`6.18.50` at survey) and `raspi-firmware`. A read-only
`apt-get -s install linux-image-rpi-v8 raspi-firmware` on `argon-02` proposed
five new packages, one upgrade, and no removals. This is the **candidate**
maintained kernel path, not yet a proven SSD-boot migration. A plain
`apt full-upgrade` will not replace the orphaned 2023 kernel package.
Resolve boot-file ownership, `/boot` versus `/boot/firmware` layout, package
maintainer-script effects, and recovery access before the first kernel or
EEPROM change. Raspberry Pi advises routine APT updates over `rpi-update`;
do not use `rpi-update` as a shortcut. See
[Raspberry Pi OS update guidance](https://www.raspberrypi.com/documentation/computers/os.html)
and [USB/EEPROM boot guidance](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).

## Preparation in the development branch

1. Add `argon-01` and `argon-02` to a dedicated bare-metal Ansible group with
   `ansible_user: ansible`. Reuse their existing `hw_hosts` entries rather than
   inventing new host identities. Build a **Pi-specific** cleanup/bootstrap
   playbook, split into separately tagged `inspect`, `retire`, `base`, `agent`,
   and `verify` phases. Run `ansible-playbook --syntax-check` on every affected
   playbook. Do not call `deploy-portainer-agent.yml`: it applies `lxc_base`
   and requires a service unit baked into the LXC template.
2. Make the cleanup declarative and allowlist-based. Enumerate named Compose
   projects and containers before stopping them; define the exact paths to
   remove in host variables. Assert the hostname and root/boot disk identity
   before each destructive task. Never glob `/opt`, `/srv`, `/home`, `/etc`,
   `/var/lib`, `/boot`, or `/var/lib/docker` while Docker is running.
3. Provide a bare-metal Portainer Agent Compose file and systemd unit under
   `/opt/portainer-agent`, using the Harbor mirror of the *same pinned version*
   as `deploy-portainer-stack.yml`. If Harbor is unavailable, resolve a
   reviewed official-image fallback before execution. Reuse the repo's
   `portainer_api` role for registration only after checking its credentials
   and its behavior against existing endpoint names. Do not install a second
   Portainer Server on either Pi.
4. Review the source IP of the infrastructure Portainer and the network path
   to each Pi. The regular agent requires server-to-Pi TCP 9001. Restrict that
   published port at the router and/or Docker's `DOCKER-USER` chain, testing
   IPv4 and IPv6; Docker-published ports can bypass ufw rules. Do not assume
   `INPUT` rules alone protect it. The agent has Docker socket access and is a
   high-trust service. Check whether the server uses `AGENT_SECRET` and pass it
   via OpenBao if so. See [Portainer Agent](https://docs.portainer.io/admin/environments/add/docker/agent)
   and [Docker's Debian/firewall guidance](https://docs.docker.com/engine/install/debian/).
5. Compare the existing monitoring inventory with the desired state. Both
   hosts are already in `ansible/inventory/inventory.yml` and
   `terraform/lxc/stacks/monitoring-stack/hwmon-hosts.yml`; their TLS
   node_exporter and hardware sensor setup was deployed on 2026-10-17.
   Reuse `hw-monitoring-node-exporter.yml` and the existing Graylog/Wazuh
   roles, fixing `argon-01`'s Wazuh failure. Check SMART, apt and certificate
   renewal timers. Keep the `gvm-scan` account and authorized key while
   credentialed Greenbone scans remain configured.

## Per-host execution sequence

Run the following on **one host at a time**. Collect transient command output
under ignored `docs/argon-pi-repurpose/artifacts/`; update this file with
durable results and delete stale artifacts at closeout. No backup or image
capture is part of this plan. Deletion of old workload data is intentional and
irreversible; a failed SSD boot may require hands-on recovery.

### 1. Preflight and reachability gate

- Confirm host identity and expected `/dev/sda` model/size with `hostname`,
  `lsblk`, `findmnt / /boot`, `blkid`, `df -h`, and `smartctl -a /dev/sda`.
  Check SMART errors and temperature again; investigate new errors before
  any large apt transaction.
- Record `uname -a`, `/boot/config.txt` boot-critical lines, boot partition
  files and ownership (`dpkg -S`), active kernel modules, EEPROM boot order,
  `apt-cache policy` for the kernel/firmware packages, `apt-mark showhold`,
  all apt sources, and `apt-get -s full-upgrade`. Resolve the 2023 kernel
  path for `argon-02` before scheduling a reboot.
- Confirm `ansible` SSH/sudo, a known host key, link/IP/default route, both
  Technitium resolvers, time sync, Argon fan service, and a reachable
  out-of-band power/console recovery method. Have an operator available for
  a failed SSD boot. Do not change EEPROM boot order as part of routine
  cleanup.
- Confirm live router DHCP DNS option and IPv6 RA DNS, plus any static DNS
  inventory. Greenbone queries can be ignored. Ensure neither Pi is a
  configured resolver before stopping Pi-hole.
- Capture container names, Compose labels, mounts, restart policies, listener
  ports, custom systemd units, scheduled jobs, apt manual packages, and
  directory sizes. Review the manifest against the allowlist in this plan.

### 2. Retire application services and data

- Stop and disable each legacy Compose/systemd owner first. Retire Pi-hole
  (both instances on `argon-01`), old Portainer Servers/Agents, NPM, Deluge,
  registry, Crawl4AI, Neo4j, and Kibana. Since **all** existing containers,
  images, volumes and networks are disposable, stop Docker and containerd,
  verify they are inactive, remove `/var/lib/docker` and
  `/var/lib/containerd`, then restart the installed Docker Engine with empty
  storage. This also clears stale Portainer agent pairing state. Do not run
  this reset while either daemon is running. Keep the Docker packages and
  `/var/run/docker.sock`.
- Remove associated data only after `findmnt` shows the target is a local
  filesystem and `systemctl`/`docker inspect` show no owner. On `argon-01`,
  candidates include `/srv/minecraft`, `/var/lib/elasticsearch`,
  `/srv/elasticsearch`, old Minecraft trees in `/opt`, and retired
  `/srv/docker/volumes` entries. On `argon-02`, candidates include retired
  `/srv/docker/volumes`, `/opt/docker/npm`, Minecraft trees and old NPM data.
  Remove corresponding user workspace data only after listing its exact
  contents; preserve the `ansible` account, SSH keys, and automation files.
- Remove application-specific systemd units (`authserver`, `worldserver` on
  `argon-01`), stale mounts and credentials for the seven NAS CIFS mounts on
  `argon-02`, application cron jobs, and unused apt packages such as MariaDB,
  CIFS/NFS clients, and old application agents, **after** a simulated apt
  removal shows it will not remove boot, network, SSH, Docker, fan, or
  monitoring dependencies. Remove obsolete Wazuh Docker integration only if
  Wazuh is retained and the integration is no longer needed.
- Review the remaining `apt-mark showmanual` list against a small host
  profile: boot/network/SSH, Argon fan, Docker, monitoring/security, and
  admin tools. Consider purging unused mail, desktop, discovery, modem,
  storage-client and development packages (for example Exim, Avahi,
  ModemManager and graphical/audio libraries) only after checking reverse
  dependencies and live service requirements. Run `apt-get -s purge` and
  `apt-get -s autoremove --purge` before acting; these simulations are gates,
  not instructions to accept every proposed removal.
- Disable and remove the `runZero` discovery and AttackIQ agents and their
  data. Check their central inventories for stale host registrations during
  closeout. Do not delete the Graylog, Wazuh, node_exporter, SMART, step-ca,
  or Greenbone configurations as historical workload residue.
- Recheck listening ports. DNS 53, HTTP 80/81/443/8080, local MariaDB 3306,
  and old Portainer ports should be gone. SSH 22, monitoring 9100, and the
  local syslog relay (10514) should remain; TCP 9001 appears in phase 4.

### 3. Patch Debian and prove SSD boot

- Refresh apt indexes; review simulated `full-upgrade` removals; apply the
  approved Debian, Raspberry Pi and Docker package updates. Keep the Docker
  repository consistent with Debian 13 arm64. `rpi-eeprom` currently has
  only residual configuration (`deinstall ok config-files`), so inspect the
  actual EEPROM bootloader/config before deciding whether to reinstall the
  package or update the EEPROM. Neither action follows automatically from
  a package update count.
- Treat kernel/firmware as a separate change. Start with the configured
  Raspberry Pi `trixie` repo's `linux-image-rpi-v8` and `raspi-firmware`
  candidate. Re-run the apt simulation after `apt update`, inspect downloaded
  package file lists and maintainer scripts, and prove where the booted Pi
  reads its kernel, initramfs and firmware; the current systems mount the
  FAT partition at `/boot`, not `/boot/firmware`. Check how the new package
  handles that layout before installing it. Verify that `argononed` supports
  the selected kernel and that USB storage modules are available for boot.
  Do not remove `raspberrypi-kernel`, overwrite `/boot/kernel8.img`, run
  `rpi-update`, or flash EEPROM based solely on an apt upgrade count. If a
  maintainable packaged kernel path cannot be proven, finish user-space
  updates and record kernel modernization as a blocked follow-up; do not
  claim the host is fully updated.
- Reboot **one** Pi. Verify SSH return, same host key/IP, root and `/boot`
  mounted from the SSD, expected kernel, Docker, Argon fan, DNS resolution,
  time sync, no failed boot-critical units, and no new SMART/USB errors.
  Stop before touching the second Pi if this gate fails.

### 4. Join the lab management plane

- Ensure Docker and Compose work, daemon logging reaches the local rsyslog
  TCP 10514 listener, and only the reviewed daemon settings are present.
  Freshly deploy the matching Portainer Agent; do not reuse the crash-looping
  agent's writable layer. Confirm `https://<pi-ip>:9001/ping` returns 204
  from an allowed source, and is unreachable from a disallowed source.
- Under the **production approval flow** for the infrastructure Portainer,
  register/update endpoint `argon-01` or `argon-02` with URL
  `tcp://<pi-ip>:9001`. Verify it is online and can list containers/images;
  confirm only the new agent container remains. Do not allow an endpoint name
  collision to silently repoint a different host.
- Reapply/verify node_exporter TLS, the hardware dashboard labels, SMART and
  apt collectors, Graylog rsyslog forwarding, Wazuh, unattended upgrades and
  certificate renewal. The existing `hw_hosts` and `hwmon-hosts.yml` entries
  should remain. Production changes to `monitoring-stack`, Graylog, Wazuh,
  router rules, or Portainer follow their own approval/preflight gates.

### 5. Acceptance and closeout

- `docker ps -a` lists only the healthy Portainer Agent; `docker system df`
  shows no old Pi-hole/application data. `ss -lntup` contains only intended
  listeners. `systemctl --failed` is empty or has a documented noncritical
  exception. Check one more reboot for agent and monitoring persistence.
- Portainer shows both endpoint names online and distinct. Grafana's hardware
  dashboard shows fresh CPU temperature and undervoltage status for both;
  SMART and apt metrics are fresh; Graylog receives a benign proof message;
  Wazuh reports both agents active; Greenbone credentialed scan works.
- Query both Technitium servers from each Pi; confirm neither Pi answers
  TCP/UDP 53. Confirm live router DHCP/RA still advertises only Technitium.
- Check `df -h`, SMART temperature/error counters, apt upgrades/holds,
  journal errors, Argon fan behavior, and SSH after at least one scheduled
  update/monitoring cycle. Update inventory and DNS migration docs to mark
  the Pis as repurposed Docker hosts. Remove stale `artifacts/` contents.

## Stop and recovery rules

- If DNS or a remaining consumer still depends on a Pi, pause Pi-hole
  retirement and identify that client. Do not change router DNS as an
  incidental cleanup action.
- If a simulated apt operation would remove SSH, NetworkManager, boot files,
  Argon control, Docker, or host monitoring, revise the package list first.
- If a Pi fails to return after reboot, stop the second host. Use the agreed
  console/power recovery path and the recorded boot/package state. With no
  backup, deleted workload data cannot be restored by this plan.
- If Portainer/monitoring registration fails, keep SSH, Docker and the agent
  working locally, then resolve central connectivity under the appropriate
  production approval; do not remove further management access.

## Execution log

### 2026-10-25 — argon-01 stage 1: preflight passed

- Confirmed hostname/IP `argon-01` / `192.168.1.22`, root `/dev/sda2`, boot
  `/dev/sda1`, both on the expected local SSD, a Lexar 512 GB device. SMART
  overall health remains `PASSED`; root is ext4 and boot is vfat.
- SSH as `ansible`, passwordless sudo, IPv4 default route, Technitium
  resolvers, Argon fan service, Docker/containerd, node_exporter, rsyslog and
  smartmontools are active. Wazuh was already failed. No apt holds reported.
- `rpi-eeprom-update` is absent. This confirms that an EEPROM operation is
  out of scope for the first cleanup/reboot pass.
- `apt-get -s full-upgrade` proposes ordinary Debian/Raspberry Pi/Docker
  package upgrades and no package removals in its shown plan. The Pi runs
  `6.18.23-v8+`; kernel/boot-file ownership remains a separate later gate.
- Exact historical data targets were enumerated on their local filesystems:
  Docker/containerd state, MariaDB/Elasticsearch state, legacy `/srv` and
  `/opt` workload trees, the runZero and AttackIQ installations, and the
  `ansible` user's historical workload directories. The account and `.ssh`
  directory are retained.

### 2026-10-25 — argon-01 stage 2a: workload data retired

- Stopped and disabled the legacy Minecraft/world server and runZero units,
  stopped Docker/containerd, then removed their local state. Removed the
  explicitly inventoried Pi-hole, Portainer, Elasticsearch, MariaDB,
  Minecraft, Crawl4AI, AttackIQ, runZero and historical user-workload paths.
  Docker/containerd were restarted with empty local state.
- Docker now lists no containers. Root filesystem use fell from 127 GB (29%)
  to 16 GB (4%). Old DNS, HTTP/HTTPS, Portainer and database listeners are
  gone; MariaDB still owns loopback 3306 until its package purge.
- Simulated removal of MariaDB, Exim, Avahi, CIFS/NFS clients, ModemManager,
  `rpi-update` and their dependent application libraries. It proposes no
  boot, SSH, NetworkManager, Docker, Argon fan or monitoring-package removal.
  `apt autoremove` is deliberately deferred until the kernel package path is
  resolved because it currently proposes initramfs components.

### 2026-10-25 — argon-01 stage 2b: legacy packages purged

- Purged the reviewed legacy package set: MariaDB client/server and plugins,
  Exim/mail utilities, Avahi, CIFS/NFS clients, ModemManager and `rpi-update`.
  Its simulation showed 26 removals and no protected host-management or boot
  package removals; the completed purge freed a further 210 MB.
- The associated services are inactive and port 3306 is gone. `rpi-update` is
  now unavailable, preventing it from being used later as an unsupported
  kernel-update shortcut. Automatic cleanup remains deferred pending the
  kernel/boot package decision.

### 2026-10-25 — argon-01 stage 3a: kernel package gate deferred

- Refreshed package indexes. `full-upgrade` now proposes 25 user-space/Docker
  updates and no removals.
- Inspected the actual `linux-image-rpi-v8` dependency package and
  `raspi-firmware` post-install script. The image would install versioned
  `/boot/vmlinuz-*`; the firmware script refuses a bare-metal install unless
  `/boot/firmware` is a mount point, then copies firmware there. `argon-01`
  instead has the active FAT boot partition mounted at `/boot` and no
  `/boot/firmware` directory. Installing that package set without a reviewed
  migration would risk writing firmware to the wrong layout.
- Deferred only the kernel/firmware package migration. It will need an
  explicit, tested migration from the legacy `/boot/kernel8.img` layout. The
  existing `6.18.23-v8+` kernel is retained for this execution pass; no EEPROM
  operation is attempted. Proceeding with the safe full user-space upgrade.

### 2026-10-25 — argon-01 stage 3b: user-space update applied

- Applied all 25 reviewed updates. Docker Engine is now `29.9.2` and Compose
  is `v5.6.1`; `apt list --upgradable` is empty. No kernel image or boot
  firmware package was installed.
- Ready for the one-host reboot gate. The expected post-reboot kernel is still
  `6.18.23-v8+`; deviation from that or a failed SSD return stops execution on
  the second Pi.

### 2026-10-25 — argon-01 stage 3c: SSD reboot gate passed

- Rebooted argon-01. After two expected SSH timeouts during restart, it
  returned with the same hostname/IP and expected `6.18.23-v8+` kernel.
  Root remains `/dev/sda2` ext4 and boot remains `/dev/sda1` vfat.
- Docker/containerd are active with an empty container inventory; Argon fan,
  node_exporter, rsyslog and SMART services are active; no upgrades remain;
  SSD SMART overall health remains `PASSED`. Retired application listeners
  remain absent.
- `openipmi.service` and the pre-existing Wazuh agent are failed. OpenIPMI is
  unused on this Pi and will be purged. Wazuh is retained for lab monitoring;
  its failure is the next diagnostic/fix gate.

### 2026-10-25 — argon-01 stage 3d: local monitoring diagnosis

- Purged unused OpenIPMI. The only remaining failed local unit is Wazuh.
  Its retained configuration contains the literal placeholder `MANAGER_IP`,
  so the agent has never had a valid manager endpoint and cannot start. It
  needs a secrets-backed Wazuh-agent enrolment/reconfiguration, with central
  manager access, before this host can meet the monitoring acceptance gate.
- Existing node_exporter, SMART, rsyslog and certificate-renewal components
  remain intact. The legacy Docker daemon configuration also remains and has
  old registry addresses, router DNS and json-file logging. It will be
  replaced during the fresh Portainer Agent deployment rather than carried
  into the final state.
- Harbor and Portainer names resolve to `192.168.30.10`; the direct Portainer
  API at `192.168.20.20:9000` reports version `2.39.8`. Central registration
  and firewall policy remain pending the required production approval flow.

### 2026-10-25 — argon-02 stage 1: preflight passed

- Confirmed hostname/IP `argon-02` / `192.168.1.23`, root `/dev/sda2`, boot
  `/dev/sda1`, both on the expected local 128 GB SSSTC SSD. SMART overall
  health remains `PASSED`; root is ext4 and boot is vfat.
- SSH/sudo, network route, Technitium resolvers, Argon fan, Docker/containerd,
  node_exporter, rsyslog, SMART and Wazuh are active. The Pi runs
  `6.1.21-v8+`. Its kernel follows the same legacy `/boot` layout and is not
  modified in this user-space cleanup pass.
- The approved workload scope includes Pi-hole, NPM, Portainer, registry,
  Deluge, Crawl4AI, Neo4j, Elasticsearch, Minecraft, AttackIQ, old NAS CIFS
  configuration/mount points and historical `ansible` user workload data.

### 2026-10-25 — argon-02 stage 2a: workload data retired

- Stopped Docker/containerd and removed the approved local Docker state,
  retired Compose/project data, database/search data, application trees and
  historical user workload files. Docker/containerd were restarted empty.
  Root use fell from 30 GB (27%) to 12 GB (10%); Docker has no containers.
- Removed the seven obsolete `192.168.1.8` CIFS entries from `/etc/fstab` and
  their empty mount-point tree. The old generated mount units remain marked
  failed until `systemctl daemon-reload` and `reset-failed`, which is the next
  cleanup action. Legacy DNS, web, proxy, database and Portainer listeners
  are absent.

### 2026-10-25 — argon-02 stage 2b: legacy packages purged

- Reloaded systemd and cleared the seven retired CIFS mount failures. Purged
  the reviewed legacy mail, CIFS/NFS, discovery, modem, IPMI, `rpi-update` and
  residual MariaDB packages. No failed units remain and `dpkg --audit` is
  clean.
- 53 ordinary package updates remain. As on argon-01, automatic removal is
  deferred because it includes boot-adjacent initramfs components while this
  Pi still uses the legacy `/boot` kernel layout.

### 2026-10-25 — argon-02 stage 3a: safe update gate passed

- Refreshed apt indexes and reviewed the final `full-upgrade` simulation:
  53 upgrades, zero new packages, zero removals. It does not install a kernel
  image or `raspi-firmware`; the legacy `6.1.21-v8+` boot migration remains
  deferred for a dedicated, tested change.

### 2026-10-25 — argon-02 stage 3b: user-space update applied

- Applied all 53 reviewed upgrades. Docker Engine is now `29.9.2`, Compose is
  `v5.6.1`, `dpkg --audit` is clean, no package upgrades remain, and no units
  are failed. No kernel image or boot firmware package was installed.
- Ready for the one-host reboot gate. The expected kernel after return is
  still `6.1.21-v8+`; a failed SSD return or unexpected boot state stops
  further execution.

### 2026-10-25 — argon-02 stage 3c: reboot recovery in progress

- Reboot was requested after the user-space upgrade. SSH first refused
  connections, then the Pi ceased answering ICMP and the workstation reported
  `No route to host`. No post-reboot mutation has been attempted. Continue
  network/SSH recovery checks; if it does not return, use the available local
  console/power path and stop central-management work for this host.

### 2026-10-25 — argon-02 stage 3d: SSD reboot gate passed

- The temporary network loss resolved without intervention. argon-02 returned
  over SSH with the expected `6.1.21-v8+` kernel, root `/dev/sda2` ext4 and
  boot `/dev/sda1` vfat.
- Argon fan, Docker/containerd, node_exporter, rsyslog, SMART and Wazuh are
  active; Docker has no containers; no upgrades or failed units remain; SMART
  overall health remains `PASSED`. The central management-plane work can now
  proceed after its production approval.

### 2026-10-25 — production stage: Wazuh re-enrolment

- With the approved production credentials, re-enrolled `argon-01` through
  the repository Wazuh-agent role. Its configuration now targets
  `192.168.40.15:1514`; the service is active and its agent state is
  `connected`.
- The corresponding `argon-02` role execution was initiated, but its first
  verification still shows the obsolete `192.168.1.119` manager and a
  `pending` state. Do not count it as complete; capture the playbook result
  and correct this host before closing the production stage.

### 2026-10-25 — production stage: Wazuh and Portainer complete

- Retried `argon-02` Wazuh enrolment with the production role. Both Pis now
  target `192.168.40.15:1514`, have active Wazuh services, and report
  `status='connected'`.
- Replaced each Pi's legacy Docker daemon configuration with the lab syslog
  configuration, deployed `harbor.lab.gibbsgreatly.xyz/dockerhub/portainer/agent:2.39.8`
  under `/opt/portainer-agent`, and verified local HTTPS `/ping` returns 204.
- Registered the new regular-agent endpoints in production Portainer:
  `argon-01` ID 16 and `argon-02` ID 17. The initial registration command
  was rejected because the standalone playbook lacked `ANSIBLE_ROLES_PATH`;
  the corrected command completed without failures.
- Added persistent `DOCKER-USER` firewall policy on both Pis: only
  `192.168.20.20` may reach TCP 9001; all other IPv4 sources are dropped.
  The policy is reapplied by `portainer-agent-firewall.service` after Docker.

### 2026-10-25 — boot-layout investigation

- Both systems use a conventional two-partition SSD scheme: the FAT partition
  is `/dev/sda1`, currently mounted at `/boot`, and the root filesystem is
  `/dev/sda2`. Raspberry Pi firmware files, `config.txt`, `cmdline.txt`,
  `kernel8.img`, DTBs and overlays all reside on that FAT partition.
- The maintained `raspi-firmware` package requires the *same* FAT partition
  to be mounted at `/boot/firmware`; it does not require repartitioning or
  different boot media. The safe migration is to unmount `/boot`, create the
  root-filesystem directory `/boot/firmware`, change only the `/etc/fstab`
  mount target, remount `/dev/sda1` there, validate all required files, then
  install the maintained kernel/firmware packages and reboot one Pi at a time.
- This is still a boot-critical change and needs a separate execution gate.
  `argon-02` also has an intentional `over_voltage=6` and `arm_freq=2000` in
  `config.txt`; retain and explicitly validate that setting during the first
  migration rather than silently normalizing it.

### 2026-10-25 — boot-layout migration approved

- Operator approved the in-place migration of both Pis to the maintained
  `/boot/firmware` layout. Execute one Pi at a time: first `argon-01`, then
  `argon-02` after a successful SSD reboot and service verification.
- No repartition, reimage, boot-order change or EEPROM flash is authorized.
  The exact existing `/dev/sda1` FAT partition remains the boot partition;
  only its Linux mount target changes.

### 2026-10-25 — argon-01 boot-layout and kernel migration passed

- Moved the existing `/dev/sda1` FAT mount from `/boot` to `/boot/firmware`.
  Confirmed `config.txt`, `cmdline.txt` and `kernel8.img` remained present on
  that same mounted partition.
- Installed `linux-image-rpi-v8` and `raspi-firmware` version `6.18.50` /
  `20260915`. The generated `/boot/firmware/kernel8.img` and versioned root
  kernel image are present and `dpkg --audit` is clean.
- Reboot verification passed: argon-01 is running `6.18.50+rpt-rpi-v8`, with
  `/dev/sda1` mounted at `/boot/firmware`. Docker, the Portainer Agent and
  its firewall service, Wazuh, and node_exporter are all active; the agent
  `/ping` endpoint returns HTTP 204, SMART reports `PASSED`, and no failed or
  upgradable packages remain. It is safe to begin the same one-host migration
  on argon-02.

### 2026-10-25 — argon-02 boot-layout and kernel migration passed

- Moved the existing `/dev/sda1` FAT mount from `/boot` to `/boot/firmware`
  without altering partitions, boot order, EEPROM, or the on-partition Pi
  configuration. `config.txt`, `cmdline.txt`, and the active firmware kernel
  image were validated before reboot.
- Installed the maintained `linux-image-rpi-v8` and `raspi-firmware` packages
  at `6.18.50` / `20260915`. The package transaction and its initramfs trigger
  completed cleanly before reboot.
- Reboot verification passed: argon-02 is running `6.18.50+rpt-rpi-v8`, with
  `/dev/sda1` mounted at `/boot/firmware`. Its intentional `over_voltage=6`
  and `arm_freq=2000` settings remain present. Docker, Portainer Agent and
  firewall service, Wazuh, node_exporter, and Argon fan service are active;
  Portainer Agent `/ping` returns HTTP 204, SMART is `PASSED`, and there are
  no failed, unpacked, or upgradable packages.

### 2026-10-25 — boot-layout remediation complete

- Both SSD-booted Pis now use Debian's maintained Raspberry Pi firmware
  layout: `/dev/sda1` is mounted at `/boot/firmware`, and both boot the
  supported `6.18.50+rpt-rpi-v8` kernel. The migration preserved the existing
  FAT partition and has passed an independent reboot and service-health gate
  on each host.

### 2026-10-25 — final Debian package cleanup complete

- Reviewed `apt-get -s autoremove` independently on each Pi before applying
  it. The removal sets contained only orphaned dependencies of the retired
  workload software: 61 packages on argon-01 and 30 on argon-02. Neither set
  included `linux-image-rpi-v8`, its active `6.18.50` image, or
  `raspi-firmware`.
- Applied the reviewed removals and cleared the apt package caches. Both hosts
  now report zero upgradable packages, zero packages eligible for autoremove,
  and a clean `dpkg` state.
- Docker, Portainer Agent and firewall, Wazuh, node_exporter (including SMART
  and apt textfile collectors), rsyslog Graylog forwarding, and the Argon fan
  service remained active on both hosts after the cleanup.
