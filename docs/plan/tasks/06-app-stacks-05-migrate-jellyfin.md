# 06-app-stacks-05 — Migrate Jellyfin to new LXC

> Historical task packet.
> This document reflects the earlier Phase 06 migration planning workflow and
> retired branch model.
> Keep it as migration-planning history only. For current workflow and
> environment rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/117

## Phase

Phase 06 — Application Stack Migration

## Prerequisites

- Task 06-01 complete — Jellyfin's current VMID, IP, media library path, GPU passthrough config documented
- Task 06-02 complete — `app_seg` (10.60.0.0/24) available
- Task 04-04 complete — Traefik running with step-ca ACME for external TLS
- Phase 03b complete — Jellyfin image mirrored to Harbor at `10.57.3.10/homelab/apps/jellyfin:<tag>`

## Objective

Jellyfin is running in a new LXC (`jellyfin-stack`, VMID 162) at `10.60.0.21`, the media library NFS mount is accessible, hardware transcoding is working (if applicable), Jellyfin is accessible externally at `jellyfin.lab.gibbsgreatly.xyz` via Traefik, and the old container is destroyed.

## Scope

- Create `terraform/lxc/stacks/jellyfin-stack/stack.yaml`
- Create `terraform/lxc/ansible/playbooks/deploy-jellyfin-stack.yml`
- Configure GPU passthrough via LXC config patch if needed (SSH to Proxmox host or Terraform `null_resource`)
- Configure Traefik ingress with external TLS cert from step-ca (or Let's Encrypt)
- Migrate Jellyfin config/metadata, verify library, then destroy old container

## Out of Scope

- Full re-scan of the media library (Jellyfin re-scans on startup — takes time but is automated)
- transcoding profile configuration (preserved from migrated config)

## Inputs

- Old Jellyfin (IP/VMID from task 06-01 discovery)
- NAS NFS media library path (from discovery)
- GPU device path if hardware transcoding was in use (from discovery)
- `docs/plan/phase-06-app-stacks.md` — Service 3 section

## Expected Outputs

- `terraform/lxc/stacks/jellyfin-stack/stack.yaml` (new)
- `terraform/lxc/stacks/jellyfin-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-jellyfin-stack.yml` (new)
- LXC VMID 162 at `10.60.0.21`
- Jellyfin accessible at `jellyfin.gibbsgreatly.xyz`
- Old container destroyed

## Constraints and Conventions

- Image via Harbor: `10.57.3.10/homelab/apps/jellyfin:<pin>`
- `stack.yaml`: VMID 162, IP `10.60.0.21/24`, `gateway: 10.60.0.1`, `dns_server: 10.60.0.1`, `network.zone: app_seg`, `cores: 4`, `memory: 4096`, `docker_storage_size: "10G"`
- GPU passthrough (LXC config additions) cannot be set via the standard Terraform LXC resource — use SSH via a Terraform `null_resource` or add it after `terragrunt apply` via Ansible
- GPU passthrough lines for Proxmox LXC conf: `lxc.cgroup2.devices.allow: c 226:* rwm` and `lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir`
- Traefik route: `jellyfin.gibbsgreatly.xyz` on the `websecure` entrypoint; Jellyfin has its own auth — Authentik middleware optional

## Acceptance Criteria

- [ ] Jellyfin image present in Harbor at `10.57.3.10/homelab/apps/jellyfin:<pin>`
- [ ] LXC VMID 162 running at `10.60.0.21`
- [ ] NFS media library mount accessible inside LXC at `/media`
- [ ] Jellyfin admin UI accessible at `http://10.60.0.21:8096`
- [ ] Hardware transcoding working (if applicable — verify via Jellyfin → Dashboard → Devices)
- [ ] `https://jellyfin.lab.gibbsgreatly.xyz` accessible via Traefik with valid TLS cert
- [ ] Old Jellyfin container snapshotted and destroyed
- [ ] NetBox updated; branch merged to `baseline/teardown-validated`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Migrate Jellyfin to a new LXC (VMID 162) at 10.60.0.21.
Jellyfin may require GPU passthrough for hardware transcoding — check task 06-01 discovery.

STEP 1 — Mirror Jellyfin image to Harbor (if not already done):
  docker pull jellyfin/jellyfin:<version>
  docker tag jellyfin/jellyfin:<version> 10.57.3.10/homelab/apps/jellyfin:<version>
  source .env && echo "$HARBOR_ROBOT_PASSWORD" | \
    docker login 10.57.3.10 -u "$HARBOR_ROBOT_USER" --password-stdin
  docker push 10.57.3.10/homelab/apps/jellyfin:<version>

STEP 2 — Back up Jellyfin config from old instance:
  ssh root@<old-jellyfin-ip> \
    "tar czf /tmp/jellyfin-config.tar.gz /config/jellyfin/ --exclude-caches"
  scp root@<old-jellyfin-ip>:/tmp/jellyfin-config.tar.gz /tmp/
  # Note: This excludes the media cache (~transcoding cache) for speed.
  # The metadata DB is included and re-used.

STEP 3 — Snapshot old container:
  ssh root@<proxmox-host> "pct snapshot <old-vmid> pre-migration-$(date +%Y%m%d)"

STEP 4 — Create branch:
  git checkout baseline/teardown-validated && git pull --ff-only origin baseline/teardown-validated
  git checkout -b feat/jellyfin-stack

STEP 5 — Create stack files:
  - terraform/lxc/stacks/jellyfin-stack/stack.yaml (VMID 162, 10.60.0.21/24, cores 4, memory 4096)
  - terraform/lxc/stacks/jellyfin-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 6 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-jellyfin-stack.yml:
  - Deploy docker-compose.yml at /opt/jellyfin-stack/ with Jellyfin service
  - Image: 10.57.3.10/homelab/apps/jellyfin:<pin>
  - Mount /media (NAS NFS) and /opt/jellyfin-stack/config:/config
  - Traefik labels:
      traefik.enable: "true"
      traefik.http.routers.jellyfin.rule: "Host(`jellyfin.lab.gibbsgreatly.xyz`)"
      traefik.http.routers.jellyfin.entrypoints: "websecure"
      traefik.http.routers.jellyfin.tls.certresolver: "step-ca"
  - Restore jellyfin-config.tar.gz to /opt/jellyfin-stack/config/

STEP 7 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/jellyfin-stack && terragrunt apply

  # If GPU passthrough needed (check discovery):
  # Add to LXC config on Proxmox host after terragrunt apply:
  ssh root@<proxmox-host> "cat >> /etc/pve/lxc/162.conf << 'EOF'
lxc.cgroup2.devices.allow: c 226:* rwm
lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir
EOF
pct restart 162"

  ansible-playbook -i "10.60.0.21," \
    terraform/lxc/ansible/playbooks/deploy-jellyfin-stack.yml

STEP 8 — Validate:
  curl -s http://10.60.0.21:8096/health   # Jellyfin health endpoint
  # Access Jellyfin admin at http://10.60.0.21:8096
  # Verify media library is being scanned

  # If GPU passthrough: check Jellyfin dashboard → Devices shows GPU
  # Test hardware transcoding: start video playback and check transcoding mode in dashboard

STEP 9 — Verify external access:
  curl -sk https://jellyfin.lab.gibbsgreatly.xyz   # Via Traefik

STEP 10 — Once verified, destroy old container:
  ssh root@<proxmox-host> "pct stop <old-vmid> && pct destroy <old-vmid>"

STEP 11 — Commit and merge:
  git add terraform/lxc/stacks/jellyfin-stack/ \
          terraform/lxc/ansible/playbooks/deploy-jellyfin-stack.yml
  git commit -m "feat(jellyfin): migrate Jellyfin to new LXC stack (VMID 162, 10.60.0.21)"
  git checkout baseline/teardown-validated && git pull --ff-only origin baseline/teardown-validated
  git merge feat/jellyfin-stack
  git push origin baseline/teardown-validated

DONE WHEN: Jellyfin accessible internally and at jellyfin.gibbsgreatly.xyz, hardware transcoding
confirmed, media library loaded, old container destroyed.
```
