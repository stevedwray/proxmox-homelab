# 04-core-services-02 — Deploy Headscale admin VPN

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/104

## Phase

Phase 04 — Core Shared Services

## Prerequisites

- Task 04-01 complete — Authentik running (Headscale itself has no hard dependency on Authentik, but deploy in order to stay in sync with the phase)
- Phase 02 complete — pve-test at 32 GB RAM
- Phase 03c complete — apt-cacher-ng at `192.168.1.35`
- `192.168.1.41` available (verify in NetBox before deploying)

## Objective

LXC `headscale-stack` (VMID 151) is running at `192.168.1.41`, the `headscale` systemd service is active, and the workstation can join the tailnet and reach `192.168.1.46` (Authentik) via `tailscale ping`.

## Scope

- Create `terraform/lxc/stacks/headscale-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `headscale-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-headscale.yml` (native binary, systemd, no Docker)
- Run `terragrunt apply` and the Ansible playbook
- Create a homelab namespace and a pre-auth key for the workstation

## Out of Scope

- Headscale ACL policies for application stacks (Phase 06)
- Exposing Headscale publicly through Traefik (task 04-04)

## Inputs

- `terraform/lxc/stacks/harbor-stack/terragrunt.hcl` — copy verbatim
- `docs/plan/phase-04-core-shared-services.md` — Service 2 section for config details

## Expected Outputs

- `terraform/lxc/stacks/headscale-stack/stack.yaml` (new)
- `terraform/lxc/stacks/headscale-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-headscale.yml` (new)
- LXC VMID 151 provisioned in pve-test
- Headscale running at `192.168.1.41:8080`

## Constraints and Conventions

- Headscale is a native binary install — no Docker needed in this LXC
- Stack YAML: `ostemplate` should be the standard Debian template; omit `docker_storage_size` since Docker is not used; `portainer_agent: false` (or omit)
- Pin the Headscale release version — do not use `latest` in download URLs
- `stack.yaml` values: VMID 151, IP `192.168.1.41/24`, `cores: 1`, `memory: 512`
- Branch convention: cut `feat/headscale-stack` from `dev/pve-test`
- **LAN ingress**: Headscale API and UI (port 8080) at `192.168.1.41` must be reachable from LAN clients for Tailscale node enrollment. External access (for remote Tailscale clients connecting from outside the LAN) is out-of-scope now but will later need a Traefik route or port-forward.

## Acceptance Criteria

- [ ] LXC VMID 151 running at `192.168.1.41`
- [ ] `systemctl status headscale` is `active (running)`
- [ ] `headscale namespaces list` shows `homelab` namespace
- [ ] Workstation can join with pre-auth key: `tailscale up --login-server http://192.168.1.41:8080 ...`
- [ ] `tailscale ping 192.168.1.46` succeeds from workstation
- [ ] Branch `feat/headscale-stack` merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy Headscale as a native systemd service inside a new LXC (VMID 151) at 192.168.1.41 on pve-test.

CONTEXT:
- Headscale is installed as a native binary (NOT Docker). The LXC template is the standard
  Debian 13 template (without the -docker variant).
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 2 section)
- VMID 151, IP 192.168.1.41, cores 1, memory 512 MB

STEP 1 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/headscale-stack

STEP 2 — Check IP availability:
  source .env
  curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.41" | jq .count
  # Must be 0

STEP 3 — Create stack files:
  - terraform/lxc/stacks/headscale-stack/stack.yaml
    (VMID 151, IP 192.168.1.41/24, cores 1, memory 512, NO docker_storage_size)
  - terraform/lxc/stacks/headscale-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 4 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-headscale.yml:
  - Fetch the latest stable Headscale binary from GitHub releases (pin the version)
  - Install to /usr/local/bin/headscale
  - Create /etc/headscale/config.yaml from a Jinja2 template with:
      server_url: http://192.168.1.41:8080
      listen_addr: 0.0.0.0:8080
      metrics_listen_addr: 0.0.0.0:9090
      db_type: sqlite3
      db_path: /var/lib/headscale/db.sqlite
  - Create systemd unit /etc/systemd/system/headscale.service
  - Run: systemctl daemon-reload && systemctl enable --now headscale

STEP 5 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/headscale-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "192.168.1.41," terraform/lxc/ansible/playbooks/deploy-headscale.yml

STEP 6 — Validate:
  ssh root@192.168.1.41 "systemctl status headscale"
  ssh root@192.168.1.41 "headscale namespaces list"

STEP 7 — Create namespace and pre-auth key:
  ssh root@192.168.1.41 "headscale namespaces create homelab"
  ssh root@192.168.1.41 "headscale preauthkeys create --namespace homelab --expiration 1h"
  # Join workstation: tailscale up --login-server http://192.168.1.41:8080 --authkey <key>

STEP 8 — Verify VPN connectivity:
  tailscale ping 192.168.1.46   # Should succeed if workstation joined

STEP 9 — Commit and merge:
  git add terraform/lxc/stacks/headscale-stack/ terraform/lxc/ansible/playbooks/deploy-headscale.yml
  git commit -m "feat(headscale): deploy Headscale admin VPN stack (VMID 151)"
  git checkout dev/pve-test && git merge feat/headscale-stack
  git push origin dev/pve-test

DONE WHEN: headscale service is active, workstation can join the tailnet, tailscale ping succeeds.
Task 04-03 (step-ca) is now unblocked.
```
