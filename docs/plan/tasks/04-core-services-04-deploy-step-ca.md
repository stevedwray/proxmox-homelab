# 04-core-services-04 — Deploy step-ca internal certificate authority

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/125

## Phase

Phase 04 — Core Shared Services

## Prerequisites

- Task 04-03 complete — Traefik running at `10.57.2.10`, `step-ca` resolver block present in `traefik.yml`
- Phase 02 complete — pve-test at 32 GB
- `10.57.1.11` available (ping-verify before deploying; also check NetBox)
- `STEP_CA_PASSWORD` and `STEP_CA_PROVISIONER_PASSWORD` set to real values in `terraform/secrets.enc.yaml`

## Network placement

| Field | Value |
|---|---|
| SDN zone | `mgmt_seg` |
| Proxmox VNet | `tvmgmt` (VLAN 20, `10.57.1.0/24`, gw `10.57.1.1` on MikroTik) |
| Container IP | `10.57.1.11` |
| IP selection | Second allocatable host in `mgmt_seg` after Authentik (`10.57.1.10`). Verified available with ping and NetBox check before deploying. |
| Cross-zone routing | Traefik (`10.57.2.10`) reaches step-ca ACME directory at `https://10.57.1.11/acme/acme/directory`. MikroTik routes between VLAN 30 (edge_seg) and VLAN 20 (mgmt_seg). step-ca httpChallenge callback reaches Traefik at `10.57.2.10:80` via MikroTik VLAN routing. No inbound from LAN required — step-ca is internal-only. |
| Firewall intent | Inbound: port 443 from `edge_seg` (Traefik) and managed hosts that need CA services. Outbound: ports 80/443 to Harbor (`10.57.3.10`) and apt-cacher (`10.57.3.11`) via MikroTik routing to infra_seg. No public exposure. |

## Objective

LXC `step-ca` (VMID 152) is running at `10.57.1.11` in `mgmt_seg` and serving an ACME directory. The root CA cert is saved to `certs/homelab-root.crt` in the repository. The homelab root CA is trusted by the Traefik container and the Proxmox host. The `step-ca` resolver in Traefik can reach the ACME directory and is confirmed working. The base LXC Ansible role is updated to distribute the root CA cert to all future containers.

This task does not change any existing browser-facing routes. Let's Encrypt remains the resolver for all routes configured in task 04-03. The step-ca resolver becomes available for opt-in use by internal management routes.

Internal naming and trust policy for this task:

- Internal shared-platform identities should use `*.lab.gibbsgreatly.xyz`.
- Certificates for `*.lab.gibbsgreatly.xyz` are issued/trusted via step-ca on managed hosts.
- Browser/operator ingress remains on `*.gibbsgreatly.xyz`.

## Scope

- Create `terraform/lxc/stacks/step-ca-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `step-ca-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-step-ca.yml`:
  - Install step-ca binary and step CLI (pinned version)
  - Bootstrap CA with `step ca init`
  - Install and start systemd service
  - Export root CA cert to repository at `certs/homelab-root.crt`
- Create `terraform/lxc/ansible/playbooks/trust-homelab-ca.yml` — reusable playbook for distributing the root cert to a target host
- Distribute root CA to Traefik container (VMID 153) and Proxmox host (192.168.1.40)
- Update base LXC Ansible role to include root CA trust task
- Verify Traefik `step-ca` resolver can reach the ACME directory

## Out of Scope

- Migrating any existing route from `letsencrypt` to `step-ca` resolver
- SSH certificate provisioning
- mTLS between services — future phase
- Distributing the root CA to browsers or end-user devices — this must never happen

## Inputs

- `docs/plan/phase-04-core-shared-services.md` — Service 3 section
- Traefik LXC for resolver verification: VMID 153, IP `10.57.2.10`
- Proxmox host for CA trust: `192.168.1.40`

## Expected Outputs

- `terraform/lxc/stacks/step-ca-stack/stack.yaml` (new)
- `terraform/lxc/stacks/step-ca-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-step-ca.yml` (new)
- `terraform/lxc/ansible/playbooks/trust-homelab-ca.yml` (new)
- `certs/homelab-root.crt` (new — committed to repository, safe to commit as it is a public cert)
- Base LXC Ansible role updated with CA trust task
- LXC VMID 152 provisioned; step-ca running at `10.57.1.11`

## Constraints and Conventions

- `stack.yaml` values: VMID 152, IP `10.57.1.11/24`, gateway `10.57.1.1`, `network: zone: mgmt_seg`, `cores: 1`, `memory: 512`, no `docker_storage_size` (step-ca runs as a systemd service, not in Docker)
- step-ca binary installed from Smallstep GitHub releases — pin version, do not use package manager builds
- `step ca init` must use `--provisioner acme` — this is what Traefik's ACME client expects
- CA private key is protected by `STEP_CA_PASSWORD` — this password must be in `.env` and never hardcoded
- `certs/homelab-root.crt` is safe to commit — it is a public certificate, not a private key
- The root CA must **only** be distributed to managed service targets. It must never be pushed to end-user devices, browsers, or any host outside the managed service layer. Add a comment to `trust-homelab-ca.yml` making this explicit
- `trust-homelab-ca.yml` must be idempotent — safe to run multiple times on the same host
- After CA trust distribution to the Traefik container, verify the resolver from inside the container — do not assume it works from the Proxmox host

## Acceptance Criteria

- [ ] LXC VMID 152 running at `10.57.1.11` in zone `mgmt_seg`
- [ ] `step ca health --ca-url https://10.57.1.11` returns OK
- [ ] ACME directory reachable: `curl -sk https://10.57.1.11/acme/acme/directory` returns JSON
- [ ] `certs/homelab-root.crt` committed to repository
- [ ] Homelab root CA trusted on Traefik container: `pct exec 153 -- update-ca-certificates` runs without error
- [ ] Homelab root CA trusted on Proxmox host `192.168.1.40`
- [ ] Traefik `step-ca` resolver can reach ACME directory from inside the container:
  `pct exec 153 -- curl -s --cacert /usr/local/share/ca-certificates/homelab-root.crt https://10.57.1.11/acme/acme/directory | jq .` returns valid JSON
- [ ] At least one internal shared-platform identity under `*.lab.gibbsgreatly.xyz` can be validated via step-ca trust on a managed host
- [ ] Base LXC Ansible role includes CA trust task
- [ ] No existing Let's Encrypt route has been changed or reassigned
- [ ] Branch `feat/step-ca` merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy step-ca as an internal certificate authority at 10.57.1.11 (VMID 152) in mgmt_seg.
Activate the step-ca resolver already pre-configured in Traefik (VMID 153 at 10.57.2.10).

CONTEXT:
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 3 section)
- VMID 152, IP 10.57.1.11/24, gateway 10.57.1.1, network zone mgmt_seg — no docker_storage_size (systemd service, not Docker)
- step-ca does NOT run in Docker — install as a systemd service
- Traefik resolver block is already present in traefik.yml at 10.57.2.10 — no Traefik config changes needed
- The root CA cert must be saved to certs/homelab-root.crt in the repository root
- certs/homelab-root.crt is a public cert — safe to commit
- CA trust must be distributed to VMID 153 (Traefik) and 192.168.1.40 (Proxmox host)
- Do NOT distribute the root CA to any end-user devices or browsers

PREREQUISITES BRING-UP (pve-test is wiped between passes — bring up the full 04-03 sequence first):

STEP 0 — Verify SDN zones are applied (should be done in 04-03 but confirm):
  pvesh get /nodes/pve-test/sdn/zones
  # Expected: tvmgmt, tvedge, tvsegc all listed

STEP 0b — Bring up harbor-stack:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/harbor-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "10.57.3.10," terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml

STEP 0c — Bring up apt-cacher-stack:
  cd terraform/lxc/stacks/apt-cacher-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "10.57.3.11," terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml

STEP 0d — Bring up authentik-stack:
  cd terraform/lxc/stacks/authentik-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "10.57.1.10," \
    terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml \
    --extra-vars "authentik_secret_key=${AUTHENTIK_SECRET_KEY} authentik_postgres_password=${AUTHENTIK_POSTGRES_PASSWORD}"
  curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/
  # Must return 204 before continuing

STEP 0e — Bring up proxy-stack (Traefik):
  cd terraform/lxc/stacks/proxy-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "10.57.2.10," \
    terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml \
    --extra-vars "cf_dns_api_token=${CF_DNS_API_TOKEN}"
  curl -s -o /dev/null -w "%{http_code}" http://10.57.2.10
  # Must return 301 or 302 before continuing

STEP 1 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/step-ca

STEP 2 — Check IP availability:
  ping -c 3 10.57.1.11
  # Must timeout (no response)
  source .env
  curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://10.57.3.12/api/ipam/ip-addresses/?address=10.57.1.11" | jq .count
  # Must be 0

STEP 3 — Create stack files:
  - terraform/lxc/stacks/step-ca-stack/stack.yaml
    (VMID 152, ip_address 10.57.1.11/24, gateway 10.57.1.1, network: {zone: mgmt_seg},
     cores 1, memory 512 — no docker_storage_size)
  - terraform/lxc/stacks/step-ca-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 4 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-step-ca.yml:
  The playbook should:
  a) Install step CLI and step-ca binaries from Smallstep GitHub releases (pin version)
     Check https://github.com/smallstep/certificates/releases for current stable version
  b) Create /etc/step-ca/ directory
  c) Write STEP_CA_PASSWORD to /etc/step-ca/password.txt (mode 0600)
  d) Bootstrap the CA:
       step ca init \
         --name "Homelab CA" \
         --dns "step-ca,10.57.1.11" \
         --address ":443" \
         --provisioner "acme" \
         --password-file /etc/step-ca/password.txt \
         --non-interactive
  e) Create systemd service for step-ca, enable and start it
  f) Wait for CA to be healthy: retry curl -sk https://10.57.1.11/health until HTTP 200
  g) Export root CA cert:
       step ca root /tmp/homelab-root.crt --ca-url https://10.57.1.11
     Fetch to control machine: save to certs/homelab-root.crt in repository root

STEP 5 — Create terraform/lxc/ansible/playbooks/trust-homelab-ca.yml:
  # WARNING: This playbook must only be run against managed service hosts.
  # Never run against end-user devices or browsers.
  Tasks:
  - copy src=certs/homelab-root.crt dest=/usr/local/share/ca-certificates/homelab-root.crt
  - command: update-ca-certificates
  Idempotent: safe to run multiple times.

STEP 6 — Deploy step-ca LXC:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/step-ca-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "10.57.1.11," \
    terraform/lxc/ansible/playbooks/deploy-step-ca.yml \
    --extra-vars "step_ca_password=${STEP_CA_PASSWORD}"

STEP 7 — Distribute root CA to managed services:
  # Traefik container
  ansible-playbook -i "10.57.2.10," \
    terraform/lxc/ansible/playbooks/trust-homelab-ca.yml

  # Proxmox host
  ansible-playbook -i "192.168.1.40," \
    terraform/lxc/ansible/playbooks/trust-homelab-ca.yml

STEP 8 — Verify resolver from inside Traefik container:
  pct exec 153 -- curl -s \
    --cacert /usr/local/share/ca-certificates/homelab-root.crt \
    https://10.57.1.11/acme/acme/directory | jq .
  # Expected: ACME directory JSON object with newNonce, newAccount, newOrder keys

STEP 9 — Update base LXC Ansible role:
  Add to terraform/lxc/ansible/roles/base-lxc/tasks/main.yml:
    - name: Trust homelab root CA
      copy:
        src: "{{ playbook_dir }}/../../../../certs/homelab-root.crt"
        dest: /usr/local/share/ca-certificates/homelab-root.crt
      notify: update-ca-certificates

STEP 10 — Commit and merge:
  git add terraform/lxc/stacks/step-ca-stack/ \
          terraform/lxc/ansible/playbooks/deploy-step-ca.yml \
          terraform/lxc/ansible/playbooks/trust-homelab-ca.yml \
          terraform/lxc/ansible/roles/base-lxc/ \
          certs/homelab-root.crt
  git commit -m "feat(step-ca): deploy internal CA in mgmt_seg, distribute root cert to managed services (VMID 152)"
  git checkout dev/pve-test && git merge feat/step-ca
  git push origin dev/pve-test

DONE WHEN: step-ca healthy, ACME directory reachable from inside Traefik container,
root CA trusted on Traefik and Proxmox host, base role updated.
Task 04-05 (Monitoring) is now unblocked.
```
