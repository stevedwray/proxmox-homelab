# 06-app-stacks-04 — Migrate arr stack to new LXC

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/116

## Phase

Phase 06 — Application Stack Migration

## Prerequisites

- Task 06-01 complete — arr stack's current VMID, IP, services, config paths, and NAS mount documented
- Task 06-02 complete — `app_seg` (10.60.0.0/24) available
- Task 04-04 complete — Traefik running; arr UIs will be accessible at `*.homelab.internal`
- Phase 03b complete — arr images mirrored to Harbor at `10.57.3.10/homelab/apps/`
- Phase 05 complete — harbor-image-policy CI check active

## Objective

Radarr, Sonarr, Prowlarr (and other arr services from discovery) are running in a new LXC (`arr-stack`, VMID 161) at `10.60.0.20`, the media library NFS mount is working, all UIs are accessible via Traefik at `*.homelab.internal` with Authentik gate, all images sourced from Harbor, and the old containers are destroyed.

## Scope

- Create `terraform/lxc/stacks/arr-stack/stack.yaml`
- Create `terraform/lxc/ansible/playbooks/deploy-arr-stack.yml`
- Mirror arr service images to Harbor if not already done
- Back up and restore service config directories
- Configure Traefik routing labels for each service
- Destroy old containers after verification

## Out of Scope

- Migrating download client history (config migration excludes torrent history — resume tracking is expected to be reset)
- gluetun VPN configuration (port mapping and VPN credentials are environment-specific — document but handle outside the session prompt)

## Inputs

- Old arr services (IPs/VMIDs from task 06-01 discovery)
- NAS NFS share path (from discovery)
- `docs/plan/phase-06-app-stacks.md` — Service 2 section
- `terraform/lxc/stacks/harbor-stack/` — reference pattern

## Expected Outputs

- `terraform/lxc/stacks/arr-stack/stack.yaml` (new)
- `terraform/lxc/stacks/arr-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-arr-stack.yml` (new)
- LXC VMID 161 at `10.60.0.20`; all arr services running
- Old containers destroyed

## Constraints and Conventions

- All images via Harbor proxy: `10.57.3.10/homelab/apps/<service>:<pin>`
- `stack.yaml`: VMID 161, IP `10.60.0.20/24`, `cores: 2`, `memory: 2048`, `docker_storage_size: "10G"`
- NAS NFS mount must be configured in `stack.yaml` or as a bind mount via Ansible
- Traefik labels must include `authentik@file` middleware — arr UIs are internal only
- Migrate one service at a time (radarr → sonarr → prowlarr), not all at once

## Acceptance Criteria

- [ ] Arr service images present in Harbor at `10.57.3.10/homelab/apps/`
- [ ] LXC VMID 161 running at `10.60.0.20`
- [ ] NFS media library mount accessible at `/media` inside the LXC
- [ ] Radarr, Sonarr, Prowlarr (and others from discovery) responding on their ports
- [ ] All arr services accessible at `<service>.homelab.internal` via Traefik
- [ ] Authentik SSO gate active on all arr service routes
- [ ] Download client configured and connected to arr services
- [ ] All images sourced from `10.57.3.10/...` (harbor-image-policy CI check passes)
- [ ] Old containers snapshotted and destroyed
- [ ] NetBox updated; branch merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Migrate the arr media management stack to a new LXC (VMID 161) at 10.60.0.20.
Read the task 06-01 discovery doc (docs/plan/phase-06-app-stacks.md) for the exact
services, config paths, and NAS mount from the old deployment.

STEP 1 — Mirror arr images to Harbor:
  For each arr service image discovered (radarr, sonarr, prowlarr, etc.):
    docker pull <image>:<version>
    docker tag <image>:<version> 10.57.3.10/homelab/apps/<service>:<version>
    source .env && echo "$HARBOR_ROBOT_PASSWORD" | \
      docker login 10.57.3.10 -u "$HARBOR_ROBOT_USER" --password-stdin
    docker push 10.57.3.10/homelab/apps/<service>:<version>

STEP 2 — Back up config from each old arr service (one at a time):
  For each service (radarr, sonarr, prowlarr, etc.):
    ssh root@<old-arr-ip> "tar czf /tmp/<svc>-config.tar.gz /config/<svc>/"
    scp root@<old-arr-ip>:/tmp/<svc>-config.tar.gz /tmp/

STEP 3 — Snapshot old containers:
  ssh root@<proxmox-host> "pct snapshot <old-vmid> pre-migration-$(date +%Y%m%d)"

STEP 4 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/arr-stack

STEP 5 — Create stack files:
  - terraform/lxc/stacks/arr-stack/stack.yaml:
      hostname: arr-stack, ip 10.60.0.20/24, gateway 10.60.0.1
      vmid: 161, cores: 2, memory: 2048, swap: 512
      docker_storage_size: 10G
      NAS mount configuration (extra_mount_path, extra_mount_storage)
      ansible_playbook: deploy-arr-stack
      portainer_agent: true
  - terraform/lxc/stacks/arr-stack/terragrunt.hcl (copy from harbor-stack)

STEP 6 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-arr-stack.yml:
  - Deploy docker-compose.yml at /opt/arr-stack/ with all arr services
  - All images via 10.57.3.10/homelab/apps/<service>:<pin>
  - Traefik labels on each service:
      traefik.enable: "true"
      traefik.http.routers.<svc>.rule: "Host(`<svc>.homelab.internal`)"
      traefik.http.routers.<svc>.middlewares: "authentik@file"
  - Restore config tarballs to /srv/docker/arr/<service>/
  
STEP 7 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/arr-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "10.60.0.20," terraform/lxc/ansible/playbooks/deploy-arr-stack.yml

STEP 8 — Validate each service, migrating one at a time:
  curl -s http://10.60.0.20:7878/api/v3/health   # Radarr (use API key from migrated config)
  curl -s http://10.60.0.20:8989/api/v3/health   # Sonarr
  # Check each service UI for existing library entries

STEP 9 — Verify Traefik routing:
  curl -sk https://radarr.homelab.internal   # Should go through Traefik → Authentik

STEP 10 — Once all services verified, destroy old containers:
  ssh root@<proxmox-host> "pct stop <old-vmid> && pct destroy <old-vmid>"

STEP 11 — Commit and merge:
  git add terraform/lxc/stacks/arr-stack/ \
          terraform/lxc/ansible/playbooks/deploy-arr-stack.yml
  git commit -m "feat(arr-stack): migrate arr media stack to new LXC (VMID 161, 10.60.0.20)"
  git checkout dev/pve-test && git merge feat/arr-stack
  git push origin dev/pve-test

DONE WHEN: All arr services running, media library accessible, Traefik routing with Authentik gate,
old containers destroyed, harbor-image-policy CI check passes.
```
