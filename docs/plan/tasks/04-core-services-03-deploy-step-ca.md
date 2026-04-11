# 04-core-services-03 — Deploy step-ca internal PKI

## Status

PENDING

## Phase

Phase 04 — Core Shared Services

## Prerequisites

- Task 04-01 complete — Authentik running
- Task 04-02 complete — Headscale running (admins can reach the management network via VPN)
- Phase 02 complete — pve-test at 32 GB
- Phase 03c complete — apt-cacher-ng at `192.168.1.35`
- `192.168.1.42` available (verify in NetBox before deploying)

## Objective

LXC `step-ca` (VMID 152) is running at `192.168.1.42`, `step ca health` returns OK, the root CA cert is distributed to the pve-test host, and at least one internal service has been issued a certificate from the internal CA.

## Scope

- Create `terraform/lxc/stacks/step-ca-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `step-ca-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-step-ca.yml` (native binary, systemd, no Docker)
- Add `STEP_CA_PASSWORD` and `STEP_CA_PROVISIONER_PASSWORD` to `.env.template` and `.env`
- Run `terragrunt apply` and the Ansible playbook
- Distribute root CA cert to pve-test host

## Out of Scope

- Distributing the root CA cert to all LXCs via a base role task (that happens incrementally as LXCs are re-run in subsequent phases)
- Issuing certs for application stacks (Phase 06)
- Traefik ACME config pointing at step-ca (task 04-04)

## Inputs

- `terraform/lxc/stacks/harbor-stack/terragrunt.hcl` — copy verbatim
- `docs/plan/phase-04-core-shared-services.md` — Service 3 section

## Expected Outputs

- `terraform/lxc/stacks/step-ca-stack/stack.yaml` (new)
- `terraform/lxc/stacks/step-ca-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-step-ca.yml` (new)
- `.env.template` updated with `STEP_CA_PASSWORD` and `STEP_CA_PROVISIONER_PASSWORD`
- LXC VMID 152 provisioned; step-ca running at `:443`
- Root CA cert saved locally as `certs/homelab-root.crt` (gitignored)

## Constraints and Conventions

- step-ca is a native binary install — no Docker in this LXC
- `stack.yaml` values: VMID 152, IP `192.168.1.42/24`, `cores: 1`, `memory: 512`
- Use `step ca init` with `--provisioner acme` to set up ACME provisioner
- The ACME directory URL will be `https://192.168.1.42/acme/acme/directory`; Traefik (task 04-04) uses this URL
- Pin the step-ca release version — do not use `latest` in download URLs
- Secrets passed via `--extra-vars` sourced from `.env`; never hardcode in playbook

## Acceptance Criteria

- [ ] LXC VMID 152 running at `192.168.1.42`
- [ ] `step ca health --ca-url https://192.168.1.42` returns OK
- [ ] Root CA cert extracted and trusted on pve-test host
- [ ] ACME provisioner configured (ACME directory endpoint responding)
- [ ] `.env.template` has `STEP_CA_PASSWORD` and `STEP_CA_PROVISIONER_PASSWORD` placeholders
- [ ] Branch `feat/step-ca-stack` merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy step-ca as a native ACME certificate authority inside a new LXC (VMID 152)
at 192.168.1.42 on pve-test.

CONTEXT:
- step-ca is installed as a native binary (NOT Docker).
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 3 section)
- VMID 152, IP 192.168.1.42, cores 1, memory 512 MB
- The ACME directory URL that Traefik will use: https://192.168.1.42/acme/acme/directory

STEP 1 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/step-ca-stack

STEP 2 — Check IP availability:
  source .env
  curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.42" | jq .count
  # Must be 0

STEP 3 — Create stack files:
  - terraform/lxc/stacks/step-ca-stack/stack.yaml (VMID 152, IP 192.168.1.42/24, cores 1, memory 512)
  - terraform/lxc/stacks/step-ca-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 4 — Add secrets to .env.template and .env:
  STEP_CA_PASSWORD=            # password protecting root CA key: openssl rand -hex 32
  STEP_CA_PROVISIONER_PASSWORD=# ACME provisioner password: openssl rand -hex 32

STEP 5 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-step-ca.yml:
  - Install step-ca and step CLI binaries from GitHub releases (pin versions)
  - Create /etc/step-ca/password.txt containing ${STEP_CA_PASSWORD}
  - Run: step ca init --name "Homelab CA" --dns "step-ca,192.168.1.42" \
          --address ":443" --provisioner "acme" --password-file /etc/step-ca/password.txt
    (only if /etc/step-ca/config/ca.json does not already exist — idempotent check)
  - Create systemd unit /etc/systemd/system/step-ca.service
  - Run: systemctl daemon-reload && systemctl enable --now step-ca

STEP 6 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/step-ca-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "192.168.1.42," terraform/lxc/ansible/playbooks/deploy-step-ca.yml \
    --extra-vars "step_ca_password=${STEP_CA_PASSWORD}"

STEP 7 — Validate:
  step ca health --ca-url https://192.168.1.42
  # Note: use --root flag or --insecure initially until root cert is trusted

STEP 8 — Extract and trust root CA cert:
  mkdir -p certs
  step ca root certs/homelab-root.crt --ca-url https://192.168.1.42 --insecure
  # Add certs/ to .gitignore if not already there

  # Trust on pve-test host (SSH in first):
  scp certs/homelab-root.crt root@<pve-test-host>:/usr/local/share/ca-certificates/homelab-root.crt
  ssh root@<pve-test-host> "update-ca-certificates"

STEP 9 — Commit and merge:
  git add terraform/lxc/stacks/step-ca-stack/ terraform/lxc/ansible/playbooks/deploy-step-ca.yml .env.template
  git commit -m "feat(step-ca): deploy internal PKI certificate authority (VMID 152)"
  git checkout dev/pve-test && git merge feat/step-ca-stack
  git push origin dev/pve-test

DONE WHEN: step ca health returns OK, root cert trusted on pve-test host.
Task 04-04 (Traefik) is now unblocked. The ACME URL is: https://192.168.1.42/acme/acme/directory
```
