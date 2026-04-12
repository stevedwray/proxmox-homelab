# 04-core-services-04 — Deploy step-ca internal certificate authority

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/107

## Phase

Phase 04 — Core Shared Services

## Prerequisites

- Task 04-03 complete — Traefik running at `192.168.1.43`, `step-ca` resolver block present in `traefik.yml`
- Phase 02 complete — pve-test at 32 GB
- `192.168.1.42` available (verify in NetBox before deploying)
- `STEP_CA_PASSWORD` and `STEP_CA_PROVISIONER_PASSWORD` set in `.env`

## Objective

LXC `step-ca` (VMID 152) is running at `192.168.1.42` and serving an ACME directory. The root CA cert is saved to `certs/homelab-root.crt` in the repository. The homelab root CA is trusted by the Traefik container and the Proxmox host. The `step-ca` resolver in Traefik can reach the ACME directory and is confirmed working. The base LXC Ansible role is updated to distribute the root CA cert to all future containers.

This task does not change any existing browser-facing routes. Let's Encrypt remains the resolver for all routes configured in task 04-03. The step-ca resolver becomes available for opt-in use by internal management routes.

## Scope

- Create `terraform/lxc/stacks/step-ca-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `step-ca-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-step-ca.yml`:
  - Install step-ca binary and step CLI (pinned version)
  - Bootstrap CA with `step ca init`
  - Install and start systemd service
  - Export root CA cert to repository at `certs/homelab-root.crt`
- Create `terraform/lxc/ansible/playbooks/trust-homelab-ca.yml` — reusable playbook for distributing the root cert to a target host
- Distribute root CA to Traefik container (VMID 153) and Proxmox host (192.168.1.2)
- Update base LXC Ansible role to include root CA trust task
- Verify Traefik `step-ca` resolver can reach the ACME directory

## Out of Scope

- Migrating any existing route from `letsencrypt` to `step-ca` resolver
- SSH certificate provisioning
- mTLS between services — future phase
- Distributing the root CA to browsers or end-user devices — this must never happen

## Inputs

- `docs/plan/phase-04-core-shared-services.md` — Service 3 section
- Traefik LXC for resolver verification: VMID 153, IP `192.168.1.43`
- Proxmox host for CA trust: `192.168.1.2`

## Expected Outputs

- `terraform/lxc/stacks/step-ca-stack/stack.yaml` (new)
- `terraform/lxc/stacks/step-ca-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-step-ca.yml` (new)
- `terraform/lxc/ansible/playbooks/trust-homelab-ca.yml` (new)
- `certs/homelab-root.crt` (new — committed to repository, safe to commit as it is a public cert)
- Base LXC Ansible role updated with CA trust task
- LXC VMID 152 provisioned; step-ca running at `192.168.1.42`

## Constraints and Conventions

- `stack.yaml` values: VMID 152, IP `192.168.1.42/24`, `cores: 1`, `memory: 512`, no `docker_storage_size` (step-ca runs as a systemd service, not in Docker)
- step-ca binary installed from Smallstep GitHub releases — pin version, do not use package manager builds
- `step ca init` must use `--provisioner acme` — this is what Traefik's ACME client expects
- CA private key is protected by `STEP_CA_PASSWORD` — this password must be in `.env` and never hardcoded
- `certs/homelab-root.crt` is safe to commit — it is a public certificate, not a private key
- The root CA must **only** be distributed to managed service targets. It must never be pushed to end-user devices, browsers, or any host outside the managed service layer. Add a comment to `trust-homelab-ca.yml` making this explicit
- `trust-homelab-ca.yml` must be idempotent — safe to run multiple times on the same host
- After CA trust distribution to the Traefik container, verify the resolver from inside the container — do not assume it works from the Proxmox host

## Acceptance Criteria

- [ ] LXC VMID 152 running at `192.168.1.42`
- [ ] `step ca health --ca-url https://192.168.1.42` returns OK
- [ ] ACME directory reachable: `curl -sk https://192.168.1.42/acme/acme/directory` returns JSON
- [ ] `certs/homelab-root.crt` committed to repository
- [ ] Homelab root CA trusted on Traefik container: `pct exec 153 -- update-ca-certificates` runs without error, cert present at `/usr/local/share/ca-certificates/homelab-root.crt`
- [ ] Homelab root CA trusted on Proxmox host `192.168.1.2`
- [ ] Traefik `step-ca` resolver can reach ACME directory from inside the container:
  `pct exec 153 -- curl -s --cacert /usr/local/share/ca-certificates/homelab-root.crt https://192.168.1.42/acme/acme/directory | jq .` returns valid JSON
- [ ] Base LXC Ansible role includes CA trust task
- [ ] No existing Let's Encrypt route has been changed or reassigned
- [ ] Branch `feat/step-ca` merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy step-ca as an internal certificate authority at 192.168.1.42 (VMID 152).
Activate the step-ca resolver already pre-configured in Traefik (VMID 153).

CONTEXT:
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 3 section)
- VMID 152, IP 192.168.1.42, cores 1, memory 512 — no docker_storage_size (systemd service, not Docker)
- step-ca does NOT run in Docker — install as a systemd service
- Traefik resolver block is already present in traefik.yml at 192.168.1.43 — no Traefik config changes needed
- The root CA cert must be saved to certs/homelab-root.crt in the repository root
- certs/homelab-root.crt is a public cert — safe to commit
- CA trust must be distributed to VMID 153 (Traefik) and 192.168.1.2 (Proxmox host)
- Do NOT distribute the root CA to any end-user devices or browsers

STEP 1 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/step-ca

STEP 2 — Check IP availability:
  source .env
  curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.42" | jq .count
  # Must be 0

STEP 3 — Create stack files:
  - terraform/lxc/stacks/step-ca-stack/stack.yaml
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
         --dns "step-ca,192.168.1.42" \
         --address ":443" \
         --provisioner "acme" \
         --password-file /etc/step-ca/password.txt \
         --non-interactive
  e) Create systemd service for step-ca, enable and start it
  f) Wait for CA to be healthy: retry curl -sk https://192.168.1.42/health until HTTP 200
  g) Export root CA cert:
       step ca root /tmp/homelab-root.crt --ca-url https://192.168.1.42
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
  ansible-playbook -i "192.168.1.42," \
    terraform/lxc/ansible/playbooks/deploy-step-ca.yml \
    --extra-vars "step_ca_password=${STEP_CA_PASSWORD}"

STEP 7 — Distribute root CA to managed services:
  # Traefik container
  ansible-playbook -i "192.168.1.43," \
    terraform/lxc/ansible/playbooks/trust-homelab-ca.yml

  # Proxmox host
  ansible-playbook -i "192.168.1.2," \
    terraform/lxc/ansible/playbooks/trust-homelab-ca.yml

STEP 8 — Verify resolver from inside Traefik container:
  pct exec 153 -- curl -s \
    --cacert /usr/local/share/ca-certificates/homelab-root.crt \
    https://192.168.1.42/acme/acme/directory | jq .
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
  git commit -m "feat(step-ca): deploy internal CA, distribute root cert to managed services (VMID 152)"
  git checkout dev/pve-test && git merge feat/step-ca
  git push origin dev/pve-test

DONE WHEN: step-ca healthy, ACME directory reachable from inside Traefik container,
root CA trusted on Traefik and Proxmox host, base role updated.
Task 04-05 (Monitoring) is now unblocked.
```
