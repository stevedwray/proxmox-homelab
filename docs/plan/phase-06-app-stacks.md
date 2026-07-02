# Phase 06 — Application Stack Migration

## Goal

Replan the application-migration phase so it matches the platform that now exists: Harbor is the only image source, the stack-owned edge model is already validated, and browser-facing services use Traefik plus Authentik under `*.lab.gibbsgreatly.xyz` where appropriate.

This phase still follows the platform foundation, but the target is no longer a provisional ingress model. The planning documents now assume the current stack-owned edge path and the current branch workflow from `AGENTS.md`.

## Prerequisites

- Validated stack-owned edge foundation is present and reachable:
  - CoreDNS at `192.168.20.13`
  - Authentik at `192.168.20.10`
  - step-ca at `192.168.20.11`
  - Traefik at `192.168.30.10`
  - Monitoring at `192.168.20.12`
- Phase 05 supply-chain pipeline active: Harbor scanning, SBOM generation, signing, and Harbor-only image policy are in place
- Harbor at `192.168.40.10` operational with projects and scanning configured
- NetBox updated with current IP allocations
- Current branch workflow from `AGENTS.md` applies: start from the current
  active development HEAD, use a short-lived `feat/`/`task/` branch, validate,
  then merge to `baseline/teardown-validated`

## Current state of application workloads

Before beginning migration, document where each application currently lives:

```bash
# On the host Proxmox, or on pve-test:
pct list    # LXC containers
qm list     # QEMU VMs
```

Expected workloads to migrate (update this list from actual discovery):

| Service | Current host | Current IP | Notes |
|---|---|---|---|
| arr stack (Radarr, Sonarr, Prowlarr, etc.) | discovery required | discovery required | Media-management apps; browser routes move to Traefik on `*.lab.gibbsgreatly.xyz` |
| Jellyfin | discovery required | discovery required | High memory; GPU passthrough if applicable; external hostname under `*.lab.gibbsgreatly.xyz` |
| Pi-hole (DNS resolver) | discovery required | discovery required | Keep on persistent IP; resolver role only; not authoritative for `lab.gibbsgreatly.xyz` |
| Game services (Minecraft etc.) | discovery required | discovery required | Direct TCP/UDP access; no browser ingress |

Fill this table in from `pct list`/`qm list` output before proceeding.

If discovery still finds a legacy Nginx Proxy Manager instance, record it as a retired cleanup item only. Do not treat NPM as a live Phase 06 dependency.

---

## Segmentation target

Per the validated stack-owned edge model, application stacks belong in an application
segment rather than `mgmt_seg`. Browser-facing apps use Traefik and Authentik;
non-browser services keep direct IP/port access.

Define the app and game segments in Proxmox SDN:

| Zone | Subnet | Purpose |
|---|---|---|
| `app_seg` | `10.60.0.0/24` | Pi-hole, arr stack, Jellyfin |
| `game_seg` | `10.61.0.0/24` | Game servers |

Adjust subnets if they conflict with the current SDN layer — check
`terraform/lxc/network/` for the active zone definitions before creating new zones.

### Create app_seg zone (if not already defined)

Follow the pattern from `terraform/lxc/network/` (used for the existing SDN zones). If Proxmox SDN zones are Terraform-managed, add `app_seg` and `game_seg` there. If managed via Proxmox UI, create them manually and document the spec.

---

## Migration approach

For each application, the migration follows this sequence:

1. **Snapshot** the existing container/VM (do not destroy until the new deployment is verified)
2. **Create a new LXC stack** using the repo pattern
3. **Migrate application data** (config, libraries, game worlds) to the new LXC
4. **Verify** the new deployment matches the old one in behaviour
5. **Update DNS** (Pi-hole) to point to the new IP
6. **Destroy** the old container/VM

Do **not** do a big-bang migration of all services at once. Migrate one service at a time.

---

## Service 1 — Pi-hole (Ad-blocking DNS resolver)

Pi-hole is a critical application for ad-blocking and recursive DNS resolution. **Important:** Internal authoritative DNS for `lab.gibbsgreatly.xyz` is provided by CoreDNS (deployed in Phase 04b) — Pi-hole is **not** responsible for that authority. Pi-hole serves as an ad-blocking resolver for client queries.

Migrate Pi-hole **last in the day**, with a rollback plan ready (revert Pi-hole IP in CoreDNS zone if needed).

### Role clarification

| Service | Role | Deployed in |
|---|---|---|
| **CoreDNS** | Authority for `lab.gibbsgreatly.xyz`; forwards non-lab queries upstream | Phase 04b, `192.168.20.13` |
| **Pi-hole** | Ad-blocking recursive resolver; optional secondary resolver for clients | Phase 06, `10.60.0.10` |

Pi-hole can be the client's default resolver (for ad-blocking), while CoreDNS remains the authority for internal service naming.

### Stack file

Create `terraform/lxc/stacks/pihole-stack/stack.yaml`:

```yaml
# Pi-hole ad-blocking DNS resolver — app_seg zone
hostname: pihole-stack
ip_address: "10.60.0.10/24"   # app_seg
gateway: "10.60.0.1"
dns_server: "10.60.0.1"
network:
vmid: 160
cores: 1
memory: 512
swap: 256
rootfs_size: 8
rootfs_storage: infrastructure-containers
docker_storage_size: "5G"
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - pihole
  - dns-resolver
  - apps
  - docker

ansible_playbook: "deploy-pihole-stack"
portainer_agent: true
```

### Image: source from Harbor

Mirror the Pi-hole image to Harbor before deploying:

```bash
# Pull and retag for Harbor:
docker pull pihole/pihole:<version>
docker tag pihole/pihole:<version> 192.168.40.10/homelab/apps/pihole:<version>
docker push 192.168.40.10/homelab/apps/pihole:<version>
```

Or use the Harbor replication policy to pull from Docker Hub on a schedule.

### Secrets required

```bash
PIHOLE_WEB_PASSWORD=    # Pi-hole admin UI password
```

### Data migration

Export Pi-hole configuration from the old instance before deploying the new one:

```bash
# On the old Pi-hole container:
tar czf /tmp/pihole-backup.tar.gz /etc/pihole/ /etc/dnsmasq.d/
```

Copy to the workstation, then restore on the new LXC via the playbook.

### Validation

After deployment and before destroying the old instance:
- Verify DNS resolution works for a known hostname: `dig @10.60.0.10 harbor-stack`
- Verify ad-blocking blocklists are loaded in the Pi-hole admin UI
- Change one client's DNS resolver to `10.60.0.10` and test browsing

---

## Service 2 — arr stack (Radarr, Sonarr, Prowlarr, etc.)

### Stack file

Create `terraform/lxc/stacks/arr-stack/stack.yaml`:

```yaml
# arr media management stack — internal-apps zone
hostname: arr-stack
ip_address: "10.60.0.20/24"
gateway: "10.60.0.1"
dns_server: "10.60.0.1"
network:
  zone: app_seg
vmid: 161
cores: 2
memory: 2048
swap: 512
rootfs_size: 8
rootfs_storage: infrastructure-containers
docker_storage_size: "10G"
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - arr
  - media
  - apps
  - docker

# Media library is on NAS/shared storage, not in this LXC:
extra_mount_path: "/media"
extra_mount_size: "0G"          # bind mount to NAS, not a Proxmox volume
extra_mount_storage: "nas-nfs"  # adjust to actual storage name

ansible_playbook: "deploy-arr-stack"
portainer_agent: true
```

### Services in the arr compose stack

Exact services depend on what currently exists. Typical set:
- `radarr` — movies
- `sonarr` — TV shows
- `prowlarr` — indexer management
- `readarr` — books (if used)
- `lidarr` — music (if used)
- `gluetun` — VPN container (if using a VPN for downloads)
- `qbittorrent` (or alternative) — download client

All images must be mirrored to Harbor before deployment.

### Data migration

```bash
# On the old arr container:
tar czf /tmp/arr-config-backup.tar.gz \
  /config/radarr/ \
  /config/sonarr/ \
  /config/prowlarr/
```

Restore config directories to `/srv/docker/arr/` on the new LXC before starting services.

### Traefik ingress

The arr stack UIs should be accessible internally only (not exposed externally). Add Traefik labels to each compose service:

```yaml
labels:
  traefik.enable: "true"
  traefik.http.routers.radarr.rule: "Host(`radarr.lab.gibbsgreatly.xyz`)"
  traefik.http.routers.radarr.middlewares: "authentik@file"  # Authentik SSO gate
```

Do **not** expose these services directly to the internet.

---

## Service 3 — Jellyfin

Jellyfin has special requirements: it may need hardware transcoding (iGPU/GPU passthrough) and requires more storage access patterns than other services.

### Stack file

Create `terraform/lxc/stacks/jellyfin-stack/stack.yaml`:

```yaml
# Jellyfin media server — internal-apps zone
hostname: jellyfin-stack
ip_address: "10.60.0.21/24"
gateway: "10.60.0.1"
dns_server: "10.60.0.1"
network:
  zone: app_seg
vmid: 162
cores: 4
memory: 4096
swap: 1024
rootfs_size: 8
rootfs_storage: infrastructure-containers
docker_storage_size: "10G"
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - jellyfin
  - media
  - apps
  - docker

extra_mount_path: "/media"
extra_mount_size: "0G"
extra_mount_storage: "nas-nfs"

ansible_playbook: "deploy-jellyfin-stack"
portainer_agent: true
```

### GPU passthrough (if applicable)

If using iGPU for hardware transcoding, the LXC needs device passthrough. This requires changes to the LXC config on the Proxmox node:

```bash
# In /etc/pve/lxc/<vmid>.conf on the Proxmox host:
lxc.cgroup2.devices.allow: c 226:* rwm   # DRM devices
lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir
```

This cannot currently be set via Terraform/Proxmox API for LXCs — it requires SSH to the Proxmox node and manual edit, or a `null_resource` in Terraform (see the `keyctl` pattern used in `netbox-stack`).

### Traefik ingress (selective external exposure)

Jellyfin is one of the few services that may be exposed externally. Add with rate limiting and Authentik if exposing:

```yaml
labels:
  traefik.enable: "true"
  traefik.http.routers.jellyfin.rule: "Host(`jellyfin.lab.gibbsgreatly.xyz`)"
  traefik.http.routers.jellyfin.entrypoints: "websecure"
  traefik.http.routers.jellyfin.tls.certresolver: "step-ca"
  # Jellyfin has its own auth — Authentik middleware optional here
```

---

## Service 4 — Game services (Minecraft etc.)

### Stack file

Create `terraform/lxc/stacks/game-stack/stack.yaml`:

```yaml
# Game server stack — game-services zone
hostname: game-stack
ip_address: "10.61.0.10/24"
gateway: "10.61.0.1"
dns_server: "10.61.0.1"
network:
  zone: game_seg
vmid: 163
cores: 4
memory: 4096
swap: 1024
rootfs_size: 8
rootfs_storage: infrastructure-containers
docker_storage_size: "20G"
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"
tags:
  - game
  - minecraft
  - apps
  - docker

ansible_playbook: "deploy-game-stack"
portainer_agent: true
```

Game servers typically need direct external access (not through Traefik). Expose ports directly on the LXC IP via Proxmox firewall rules, with rate limiting and IP allow-lists where possible.

---

## Trivy rootfs scheduled scans

### Why rootfs scans are needed

Harbor Trivy scans container images — it reads the OCI image layers. It **does not** scan the base OS of the LXC containers themselves. Packages installed by Ansible directly on the LXC (e.g., `curl`, `git`, `unzip`, Docker engine) are invisible to Harbor because they live in the host filesystem, not in an OCI image.

A `trivy rootfs /` scan against the live LXC filesystem catches these OS-level vulnerabilities.

### Schedule: CI cronjob or systemd timer

Two options:

**Option A — GitHub Actions scheduled workflow (recommended)**

Add a new workflow `.github/workflows/rootfs-scan.yml`:

```yaml
name: Trivy rootfs scan

on:
  schedule:
    - cron: "0 3 * * 1"   # Every Monday at 03:00 UTC
  workflow_dispatch:

jobs:
  rootfs-scan:
    name: Scan LXC rootfs — ${{ matrix.host }}
    runs-on: [self-hosted, pve-test, build]
    strategy:
      matrix:
        host:
          - "192.168.40.11"     # apt-cacher-ng
          - "192.168.20.10"     # Authentik
          - "192.168.20.11"     # step-ca
          - "192.168.30.10"     # Traefik
          - "192.168.20.12"     # Monitoring
          # Add Phase 06 app stacks as they are deployed
    steps:
      - uses: actions/checkout@v4

      - name: Run Trivy rootfs scan via SSH
        run: |
          ssh -o StrictHostKeyChecking=accept-new root@${{ matrix.host }} \
            "trivy rootfs --severity HIGH,CRITICAL --format sarif --output /tmp/trivy-rootfs.sarif / && \
             cat /tmp/trivy-rootfs.sarif" > trivy-rootfs-${{ matrix.host }}.sarif
        # Trivy must be installed on each LXC — see below

      - name: Upload rootfs SARIF
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: trivy-rootfs-${{ matrix.host }}.sarif
```

> Trivy can emit SARIF directly if called with `--format sarif`. Replace the JSON example above with `--format sarif --output /tmp/trivy-rootfs.sarif` and adjust the upload step accordingly.

**Option B — systemd timer on each LXC**

For LXCs that should self-report without CI involvement, install a systemd timer:

```ini
# /etc/systemd/system/trivy-rootfs.service
[Unit]
Description=Trivy rootfs vulnerability scan

[Service]
Type=oneshot
ExecStart=/usr/local/bin/trivy rootfs --severity HIGH,CRITICAL \
  --format json \
  --output /var/log/trivy-rootfs-$(date +%%Y%%m%%d).json /
```

```ini
# /etc/systemd/system/trivy-rootfs.timer
[Unit]
Description=Weekly Trivy rootfs scan

[Timer]
OnCalendar=Mon 03:00
Persistent=true

[Install]
WantedBy=timers.target
```

Add the service and timer files via the base LXC Ansible role.

### Install Trivy on each LXC

Add to the base LXC Ansible role (`terraform/lxc/ansible/roles/lxc_base/tasks/main.yml`):

```yaml
- name: Install Trivy
  ansible.builtin.shell: |
    curl -sSfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | \
      sh -s -- -b /usr/local/bin v<TRIVY_VERSION>
  args:
    creates: /usr/local/bin/trivy
```

Pin to the same Trivy version used in the CI image scan job (Phase 05 Part A).

### Update the rootfs scan host matrix

Each time a new LXC is deployed in Phase 06, add its IP to the `matrix.host` list in `rootfs-scan.yml`.

---

## Backup strategy

Before migrating **any** service, ensure Proxmox Backup Server (PBS, Phase 07) is configured and taking scheduled backups. If PBS is not yet deployed, take manual LXC snapshots:

```bash
# On Proxmox node before migration:
pct snapshot <old-vmid> pre-migration-$(date +%Y%m%d)
```

---

## NetBox updates after each migration

After each service is migrated and the old container destroyed, update NetBox:
- Retire the old IP address
- Update the VM record to the new VMID and IP
- Update service port records
- Update the "platform" tag if the underlying OS changed

---

## Commit strategy

Follow the repository branch model in `AGENTS.md`:

1. Start each slice from `baseline/teardown-validated`.
2. Work on a short-lived `feat/` or `task/` branch.
3. Validate on that branch before promoting.
4. Merge to `baseline/teardown-validated` only after the slice is validated and the old instance is retired.

---

## Acceptance criteria

### Pi-hole
- [ ] Pi-hole LXC running at new IP
- [ ] DNS resolution for all homelab hostnames working via new Pi-hole
- [ ] Blocklists loaded and ad-blocking functional
- [ ] All clients resolving via the new Pi-hole IP
- [ ] Old Pi-hole container destroyed

### arr stack
- [ ] Radarr, Sonarr, Prowlarr (and others as applicable) running on new LXC
- [ ] Media library accessible at `/media` mount
- [ ] Download client connected and processing
- [ ] UIs accessible via Traefik at `*.lab.gibbsgreatly.xyz` with Authentik gate
- [ ] All images sourced from `192.168.40.10/homelab/apps/`
- [ ] Old containers destroyed

### Jellyfin
- [ ] Jellyfin running on new LXC with media library accessible
- [ ] Hardware transcoding functional (if applicable)
- [ ] Accessible externally via Traefik at `jellyfin.lab.gibbsgreatly.xyz`
- [ ] TLS cert issued by step-ca (or Let's Encrypt)
- [ ] Old container destroyed

### Game stack
- [ ] Minecraft (and other game servers) running
- [ ] World data migrated and verified
- [ ] Port access working (firewall rules confirmed)
- [ ] Old container destroyed

### Overall
- [ ] All application stacks registered in NetBox with updated IPs and services
- [ ] No services pulling images from Docker Hub at runtime
- [ ] All new stacks appear in Grafana dashboards (container metrics visible)
- [ ] `dmesg | grep -i oom` on pve-test shows no OOM events after full migration
- [ ] Trivy rootfs scan workflow running (`rootfs-scan.yml`); no CRITICAL findings on any LXC
- [ ] All Phase 06 LXC IPs added to the rootfs scan matrix
