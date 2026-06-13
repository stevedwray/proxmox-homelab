# 06-app-stacks-03 — Migrate Pi-hole to new LXC stack

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/115

## Phase

Phase 06 — Application Stack Migration

## Prerequisites

- Task 06-01 complete — Pi-hole's current VMID, IP, config paths, and blocklist version documented
- Task 06-02 complete — `app_seg` (10.60.0.0/24) available
- Phase 03b complete — Harbor running; Pi-hole image mirrored to `10.57.3.10/homelab/apps/pihole:<tag>`
- Phase 05 complete — supply chain pipeline checks against Harbor images active
- **Rollback plan ready**: know how to revert DNS resolvers to the old Pi-hole IP

## Objective

Pi-hole is running in a new LXC (`pihole-stack`, VMID 160) at `10.60.0.10`, all DNS queries from internal clients resolve correctly, blocklists are loaded, the old Pi-hole container is destroyed, and the new IP is registered in NetBox.

## Scope

- Mirror Pi-hole image to Harbor before deploying (if not done in Phase 03b)
- Create `terraform/lxc/stacks/pihole-stack/stack.yaml`
- Create `terraform/lxc/ansible/playbooks/deploy-pihole-stack.yml`
- Export config from old Pi-hole, restore on new, verify, then destroy old
- Add `PIHOLE_WEB_PASSWORD` to `.env.template`

## Out of Scope

- Changing existing DNS resolver configurations on clients (point them at new IP after validation)
- Pi-hole upstream DNS provider configuration (preserve current settings from migration backup)

## Inputs

- Old Pi-hole (IP/VMID from task 06-01 discovery)
- `terraform/lxc/stacks/harbor-stack/` — reference for stack.yaml pattern
- `docs/plan/phase-06-app-stacks.md` — Service 1 section

## Expected Outputs

- `terraform/lxc/stacks/pihole-stack/stack.yaml` (new)
- `terraform/lxc/stacks/pihole-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-pihole-stack.yml` (new)
- `.env.template` updated with `PIHOLE_WEB_PASSWORD`
- LXC VMID 160 running at `10.60.0.10`
- Old Pi-hole container destroyed

## Constraints and Conventions

- Pi-hole is critical path for DNS. Deploy the new one **before** touching the old one. Only destroy old after the new is fully verified.
- Image must be sourced from Harbor: `10.57.3.10/homelab/apps/pihole:<pin>`
- `stack.yaml`: VMID 160, IP `10.60.0.10/24`, `gateway: 10.60.0.1`, `dns_server: 10.60.0.1`, `network.zone: app_seg`, `cores: 1`, `memory: 512`, `docker_storage_size: "5G"`
- The new Pi-hole must be able to forward DNS queries upstream (ensure `10.60.0.0/24` has internet egress via the SDN gateway)
- Test DNS resolution explicitly before updating any client resolver configs
- **LAN ingress**: Pi-hole is on `app_seg` (`10.60.0.10`), not `mgmt_seg`. Port 53 (DNS) must be reachable from all LAN clients (`192.168.1.0/24`). This requires inter-segment routing between `10.60.0.0/24` and `192.168.1.0/24` via the SDN gateway (`10.60.0.1`). Verify this routing is in place before switching any client resolver configs. Port 80 (admin UI) should also be LAN-accessible for management.

## Acceptance Criteria

- [ ] Pi-hole image present in Harbor at `10.57.3.10/homelab/apps/pihole:<tag>`
- [ ] LXC VMID 160 running at `10.60.0.10`
- [ ] `dig @10.60.0.10 harbor-stack` resolves correctly
- [ ] Blocklists loaded (Pi-hole admin UI shows active blocklists)
- [ ] At least one client DNS resolver updated to `10.60.0.10` and browsing works
- [ ] Old Pi-hole container snapshotted then destroyed
- [ ] NetBox updated: old IP retired, `10.60.0.10` registered
- [ ] Branch `feat/pihole-stack` merged to `baseline/teardown-validated`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Migrate Pi-hole DNS to a new LXC (VMID 160) at 10.60.0.10 in the app_seg zone.
Pi-hole is critical path — deploy new first, verify, then destroy old. Never destroy
the old instance until DNS is confirmed working on the new one.

PREREQUISITE: Check task 06-01 discovery for the old Pi-hole's current IP and VMID.

STEP 1 — Mirror Pi-hole image to Harbor (if not already done):
  docker pull pihole/pihole:<version>   # use installed version from discovery
  docker tag pihole/pihole:<version> 10.57.3.10/homelab/apps/pihole:<version>
  source .env && echo "$HARBOR_ROBOT_PASSWORD" | \
    docker login 10.57.3.10 -u "$HARBOR_ROBOT_USER" --password-stdin
  docker push 10.57.3.10/homelab/apps/pihole:<version>

STEP 2 — Back up old Pi-hole config:
  ssh root@<old-pihole-ip> \
    "tar czf /tmp/pihole-backup.tar.gz /etc/pihole/ /etc/dnsmasq.d/"
  scp root@<old-pihole-ip>:/tmp/pihole-backup.tar.gz /tmp/pihole-backup.tar.gz

STEP 3 — Snapshot old Pi-hole container:
  ssh root@<proxmox-host> "pct snapshot <old-vmid> pre-migration-$(date +%Y%m%d)"

STEP 4 — Create branch:
  git checkout baseline/teardown-validated && git pull --ff-only origin baseline/teardown-validated
  git checkout -b feat/pihole-stack

STEP 5 — Create stack files:
  - terraform/lxc/stacks/pihole-stack/stack.yaml:
      hostname: pihole-stack
      ip_address: "10.60.0.10/24"
      gateway: "10.60.0.1"
      vmid: 160
      cores: 1, memory: 512, swap: 256, rootfs_size: 8
      rootfs_storage: infrastructure-containers
      docker_storage_size: "5G"
      ostemplate: standard debian-13 docker template
      tags: [pihole, dns, apps, docker]
      ansible_playbook: "deploy-pihole-stack"
      portainer_agent: true
  - terraform/lxc/stacks/pihole-stack/terragrunt.hcl (copy from harbor-stack)

STEP 6 — Add PIHOLE_WEB_PASSWORD to .env.template and .env.

STEP 7 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-pihole-stack.yml:
  Deploy Pi-hole via Docker Compose at /opt/pihole-stack/docker-compose.yml.
  Image: 10.57.3.10/homelab/apps/pihole:<version>
  The playbook should:
  - Deploy compose
  - Copy pihole-backup.tar.gz to the LXC and restore to /etc/pihole/ and /etc/dnsmasq.d/
  - Restart Pi-hole to pick up the restored config

STEP 8 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/pihole-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "10.60.0.10," \
    terraform/lxc/ansible/playbooks/deploy-pihole-stack.yml \
    --extra-vars "pihole_web_password=${PIHOLE_WEB_PASSWORD}"

STEP 9 — Verify new Pi-hole:
  dig @10.60.0.10 harbor-stack        # Should resolve
  dig @10.60.0.10 google.com          # Upstream DNS works
  curl -s http://10.60.0.10/admin/    # Pi-hole admin UI accessible
  # Check blocklist count in admin UI matches old Pi-hole

STEP 10 — Migrate one client DNS resolver to 10.60.0.10, test browsing.

STEP 11 — Once verified, update all clients to use 10.60.0.10. Then destroy old Pi-hole:
  ssh root@<proxmox-host> "pct stop <old-vmid> && pct destroy <old-vmid>"

STEP 12 — Update NetBox, commit, merge:
  git add terraform/lxc/stacks/pihole-stack/ \
          terraform/lxc/ansible/playbooks/deploy-pihole-stack.yml \
          .env.template
  git commit -m "feat(pihole): migrate Pi-hole DNS to new LXC stack (VMID 160, 10.60.0.10)"
  git checkout baseline/teardown-validated && git pull --ff-only origin baseline/teardown-validated
  git merge feat/pihole-stack
  git push origin baseline/teardown-validated

DONE WHEN: All clients using 10.60.0.10, blocklists loaded, old Pi-hole destroyed.
```
