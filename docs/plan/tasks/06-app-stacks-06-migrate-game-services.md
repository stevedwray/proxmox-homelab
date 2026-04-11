# 06-app-stacks-06 — Migrate game services to new LXC

## Status

PENDING

## Phase

Phase 06 — Application Stack Migration

## Prerequisites

- Task 06-01 complete — game services' current VMID, IPs, world data paths, exposed ports documented
- Task 06-02 complete — `game_seg` (10.61.0.0/24) available
- Phase 03b complete — game server images mirrored to Harbor at `192.168.1.10/homelab/apps/`

## Objective

Game servers (Minecraft and others from discovery) are running in a new LXC (`game-stack`, VMID 163) at `10.61.0.10` in the `game_seg` zone, world data is migrated and verified, direct port access is working (firewall rules confirmed), and old containers are destroyed.

## Scope

- Create `terraform/lxc/stacks/game-stack/stack.yaml`
- Create `terraform/lxc/ansible/playbooks/deploy-game-stack.yml`
- Mirror game server images to Harbor if not done in Phase 03b
- Back up world data (Minecraft world files, etc.), restore to new LXC, verify
- Configure firewall rules for direct port access (not through Traefik)
- Destroy old containers after verification

## Out of Scope

- Game-specific configuration tuning (server.properties, plugins, etc.) — preserve from migration backup
- Traefik routing — game services use direct TCP/UDP port access, not HTTP proxying

## Inputs

- Old game services (IPs/VMIDs from task 06-01 discovery)
- World data paths (from discovery)
- Port mappings (from discovery — which ports are exposed)
- `docs/plan/phase-06-app-stacks.md` — Service 4 section

## Expected Outputs

- `terraform/lxc/stacks/game-stack/stack.yaml` (new)
- `terraform/lxc/stacks/game-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-game-stack.yml` (new)
- LXC VMID 163 at `10.61.0.10`
- Game servers accessible on their expected ports
- Old containers destroyed

## Constraints and Conventions

- `stack.yaml`: VMID 163, IP `10.61.0.10/24`, `gateway: 10.61.0.1`, `cores: 4`, `memory: 4096`, `docker_storage_size: "20G"`
- Game services need direct port exposure (not through Traefik) — port forwarding via Proxmox firewall
- All images via Harbor: `192.168.1.10/homelab/apps/<game-service>:<pin>`
- World data is critical — verify file integrity after migration before destroying old LXC (compare directory sizes, test loading in game client)
- Apply rate limiting and IP allow-list rules on Proxmox firewall for exposed game ports where practical

## Acceptance Criteria

- [ ] Game server images present in Harbor at `192.168.1.10/homelab/apps/`
- [ ] LXC VMID 163 running at `10.61.0.10`
- [ ] World data migrated and verified (size comparison, game client test connection)
- [ ] Game server ports accessible from outside via Proxmox port-forwarding rules
- [ ] Old game server containers snapshotted and destroyed
- [ ] NetBox updated; branch merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Migrate game services to a new LXC (VMID 163) at 10.61.0.10 in the game_seg zone.
Check task 06-01 discovery for the exact game services, world data paths, and port mappings.

STEP 1 — Mirror game server images to Harbor (if not done in Phase 03b):
  For each game server image from discovery:
    docker pull <image>:<version>
    docker tag <image>:<version> 192.168.1.10/homelab/apps/<game-service>:<version>
    source .env && echo "$HARBOR_ROBOT_PASSWORD" | \
      docker login 192.168.1.10 -u "$HARBOR_ROBOT_USER" --password-stdin
    docker push 192.168.1.10/homelab/apps/<game-service>:<version>

STEP 2 — Back up world data:
  ssh root@<old-game-ip> "tar czf /tmp/minecraft-world.tar.gz /data/world/ /data/server.properties"
  scp root@<old-game-ip>:/tmp/minecraft-world.tar.gz /tmp/
  # Verify archive is complete: du -sh /tmp/minecraft-world.tar.gz vs. original

STEP 3 — Snapshot old container:
  ssh root@<proxmox-host> "pct snapshot <old-vmid> pre-migration-$(date +%Y%m%d)"

STEP 4 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/game-stack

STEP 5 — Create stack files:
  - terraform/lxc/stacks/game-stack/stack.yaml
    (VMID 163, ip 10.61.0.10/24, gateway 10.61.0.1, cores 4, memory 4096, docker_storage_size 20G)
  - terraform/lxc/stacks/game-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 6 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-game-stack.yml:
  - Deploy docker-compose.yml at /opt/game-stack/ with game server services
  - Images from 192.168.1.10/homelab/apps/<game-service>:<pin>
  - Expose game ports directly (ports: section in compose — NOT Traefik labels)
  - Restore world data backup to /opt/game-stack/data/

STEP 7 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/game-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "10.61.0.10," terraform/lxc/ansible/playbooks/deploy-game-stack.yml

STEP 8 — Configure Proxmox firewall for game port forwarding:
  # In Proxmox web UI → <node> → Firewall → Add rules to forward game ports to 10.61.0.10:
  # E.g., TCP 25565 → 10.61.0.10:25565 for Minecraft
  # Apply appropriate rate limiting rules

STEP 9 — Verify:
  # Connect to game server from a game client to test world data was restored correctly
  # Check world is loading with expected chunks
  nc -z 10.61.0.10 25565   # (or appropriate port) — should connect

STEP 10 — Once verified, destroy old container:
  ssh root@<proxmox-host> "pct stop <old-vmid> && pct destroy <old-vmid>"

STEP 11 — Commit and merge:
  git add terraform/lxc/stacks/game-stack/ \
          terraform/lxc/ansible/playbooks/deploy-game-stack.yml
  git commit -m "feat(game-stack): migrate game services to new LXC stack (VMID 163, 10.61.0.10)"
  git checkout dev/pve-test && git merge feat/game-stack
  git push origin dev/pve-test

DONE WHEN: Game servers running, world data verified, port access confirmed, old containers destroyed.
```
