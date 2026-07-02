# 04-core-services-04 — Deploy step-ca internal certificate authority

> Historical task packet.
> This document reflects the earlier `pve-test` Phase 04 deployment workflow
> and should not be treated as the current operator runbook.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md),
> [docs/workflow/environments.md](../../workflow/environments.md), and
> [docs/teardown-test/README.md](../../teardown-test/README.md).

## Rebuild confidence

| Criterion | State |
| --- | --- |
| IaC reproducible | Yes |
| Secrets managed | Yes — step-ca passwords flow from SOPS via `./with-secrets` env injection |
| Integrations wired | Yes |
| Rebuild-safe | Partial |

See [development-status.md](../development-status.md) for the full gap analysis.

## GitHub Issue

[stevedwray/proxmox-homelab#125](https://github.com/stevedwray/proxmox-homelab/issues/125)

## Phase

Phase 04 — Core Shared Services

## Known gaps preventing full rebuild-safety

1. **CA rebuild invalidates all issued certs.** `step ca init` in the playbook generates a
   new root CA keypair on each deployment. Any cert previously issued by the old CA (including
   Traefik ACME certs obtained via the step-ca resolver) becomes invalid. The committed
   `certs/homelab-root.crt` also changes. This is tolerable during development but means the
   CA and all consumers must be rebuilt together on each pass.

2. **CA persistence strategy not decided.** There are two options:
   - **Regenerate on each rebuild** (current) — simple, but invalidates all issued certs.
     The CA root changes every pass; all consumers must re-trust.
   - **Persist the CA keypair** — store encrypted CA key in SOPS or a Proxmox host
     bind-mount. Survives LXC rebuild; issued certs remain valid. More complex to implement.
   This decision must be made and documented before the platform is considered production-ready.

3. **Automatic CA trust distribution not yet enforced in rebuild sequence.** The
  `trust-homelab-ca.yml` playbook exists, but tooling does not yet guarantee it runs
  automatically after step-ca deploy. Containers deployed
   before step-ca will not trust the new root CA until `trust-homelab-ca.yml` is run against
   them retroactively. The intended sequence is:

   1. Deploy step-ca (generates new root CA)
   2. Fetch `certs/homelab-root.crt` from step-ca and commit to repo
   3. Run `trust-homelab-ca.yml` against all already-deployed LXCs (retroactive)
   4. All subsequent LXC deployments pick up the CA cert automatically via `lxc_base` role

  This sequence is documented but not yet enforced in tooling. The target state is that
  step 3 runs automatically as a post-step-ca deployment action.

## Prerequisites

- Task 04-03 complete — Traefik running at `10.57.2.10`, `step-ca` resolver block present
  in `traefik.yml`
- Phase 02 complete — pve-test at 32 GB
- `10.57.1.11` available (ping-verify before deploying)
- `STEP_CA_PASSWORD` and `STEP_CA_PROVISIONER_PASSWORD` set to real values in
  `terraform/secrets.enc.yaml`

## Network placement

| Field | Value |
| --- | --- |
| SDN zone | `mgmt_seg` |
| Proxmox VNet | `tvmgmt` (VLAN 20, `10.57.1.0/24`, gw `10.57.1.1` on MikroTik) |
| Container IP | `10.57.1.11` |
| Cross-zone routing | Traefik (`10.57.2.10`) reaches step-ca ACME at `https://10.57.1.11/acme/acme/directory`. step-ca httpChallenge callback reaches Traefik at `10.57.2.10:80`. MikroTik routes between VLAN 30 and VLAN 20. Requires MikroTik policy: `mgmt_seg → edge_seg tcp/80`. |
| Firewall intent | Inbound: port 443 from `edge_seg` (Traefik) and managed hosts. Outbound: ports 80/443 to Harbor and apt-cacher via infra_seg. No public exposure. |

## Objective

LXC `step-ca` (VMID 152) is running at `10.57.1.11` in `mgmt_seg` and serving an ACME
directory. The root CA cert is saved to `certs/homelab-root.crt` in the repository. Automatic
post-step-ca trust distribution updates Traefik, Proxmox host, and all already-deployed
managed LXCs. The `step-ca` resolver in Traefik can reach the ACME directory and is confirmed
working from inside the container. The base LXC Ansible role is updated to distribute the root
CA cert to all future containers. All secrets are injected from SOPS — `STEP_CA_PASSWORD` is
never passed as an `--extra-vars` argument.

## Scope

- Validate `terraform/lxc/stacks/step-ca-stack/stack.yaml`
- Validate `terraform/lxc/stacks/step-ca-stack/terragrunt.hcl`
- Maintain `terraform/lxc/ansible/playbooks/deploy-step-ca.yml` — secrets from SOPS via
  `./with-secrets`; install step-ca as a systemd service (not Docker)
- Maintain `terraform/lxc/ansible/playbooks/trust-homelab-ca.yml` — reusable, idempotent
  playbook for distributing the root cert to a target host
- Distribute root CA to Traefik container (VMID 153) and Proxmox host (192.168.1.40)
- Update base LXC Ansible role to include root CA trust task
- Verify Traefik `step-ca` resolver can reach the ACME directory from inside the container

## Out of Scope

- Migrating any existing route from `letsencrypt` to `step-ca` resolver
- SSH certificate provisioning
- mTLS between services — future phase
- Distributing the root CA to browsers or end-user devices — this must never happen
- CA keypair persistence strategy implementation — documented as a gap, decision pending

## Inputs

- `docs/plan/phase-04-core-shared-services.md` — Service 3 section
- Traefik LXC for resolver verification: VMID 153, IP `10.57.2.10`
- Proxmox host for CA trust: `192.168.1.40`

## Expected Outputs

- `terraform/lxc/stacks/step-ca-stack/stack.yaml`
- `terraform/lxc/stacks/step-ca-stack/terragrunt.hcl`
- `terraform/lxc/ansible/playbooks/deploy-step-ca.yml` — secrets via with-secrets
- `terraform/lxc/ansible/playbooks/trust-homelab-ca.yml`
- `certs/homelab-root.crt` committed to repository (public cert — safe to commit)
- Base LXC Ansible role updated with CA trust task
- LXC VMID 152 provisioned; step-ca running at `10.57.1.11`

## Constraints and Conventions

- `stack.yaml` values: VMID 152, IP `10.57.1.11/24`, gateway `10.57.1.1`,
  `network: zone: mgmt_seg`, `cores: 1`, `memory: 512` — no `docker_storage_size`
  (step-ca runs as a systemd service, not in Docker)
- step-ca binary installed from Smallstep GitHub releases — pin version explicitly
- `step ca init` must leave ACME enabled and publish the ACME directory endpoint that
  Traefik uses; the exact bootstrap flags may differ from the original sketch
- CA private key is protected by `STEP_CA_PASSWORD` from SOPS — the playbook must read it
  from the environment injected by `./with-secrets`, not from `--extra-vars`
- `certs/homelab-root.crt` is safe to commit — it is a public certificate, not a private key
- The root CA must **only** be distributed to managed service targets. It must never be
  pushed to end-user devices, browsers, or any host outside the managed service layer.
  Add an explicit comment to `trust-homelab-ca.yml` making this restriction clear
- `trust-homelab-ca.yml` must be idempotent — safe to run multiple times on the same host
- After CA trust distribution to the Traefik container, verify the resolver from inside
  the container — do not assume it works from the Proxmox host

## Acceptance Criteria

- [ ] LXC VMID 152 running at `10.57.1.11` in zone `mgmt_seg`
- [ ] `step ca health --ca-url https://10.57.1.11` returns OK
- [ ] ACME directory reachable: `curl -sk https://10.57.1.11/acme/acme/directory` returns JSON
- [ ] `certs/homelab-root.crt` committed to repository
- [ ] Homelab root CA trusted on Traefik container and Proxmox host
- [ ] Automatic post-step-ca trust distribution executed successfully for all already-deployed managed hosts
- [ ] Traefik `step-ca` resolver reaches ACME directory from inside container:
      `TRAEFIK_VMID=$(pct list | awk 'NR>1 && ($4=="proxy-stack" || $4=="traefik") {print $1; exit}') && pct exec "$TRAEFIK_VMID" -- curl -s --cacert /usr/local/share/ca-certificates/homelab-root.crt https://10.57.1.11/acme/acme/directory | jq .`
      returns valid JSON with `newNonce`, `newAccount`, `newOrder` keys
- [ ] Base LXC Ansible role includes CA trust task
- [ ] No existing Let's Encrypt route changed or reassigned
- [ ] `/opt/proxy-stack/certs/step-ca/acme.json` — still 0 bytes (no internal certs issued yet;
      the internal TLS path is untested end-to-end until a lab route uses `certresolver=step-ca`)
- [ ] Branch `feat/step-ca` merged to `baseline/teardown-validated`

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy step-ca as an internal certificate authority at 10.57.1.11 (VMID 152) in mgmt_seg.
Activate the step-ca resolver already pre-configured in Traefik (VMID 153 at 10.57.2.10).

IMPORTANT: All secret values are in terraform/secrets.enc.yaml and must be injected via
./with-secrets. Do not pass STEP_CA_PASSWORD or any other secret as --extra-vars.
The playbook reads the password from the environment variable injected by ./with-secrets.

CONTEXT:
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 3 section)
- VMID 152, IP 10.57.1.11/24, gateway 10.57.1.1, network zone mgmt_seg
- No docker_storage_size — step-ca runs as a systemd service, not Docker
- Traefik resolver block is already present in traefik.yml at 10.57.2.10 — no Traefik changes
- The root CA cert must be saved to certs/homelab-root.crt in the repository root
- certs/homelab-root.crt is a public cert — safe to commit
- CA trust must be distributed to VMID 153 (Traefik) and 192.168.1.40 (Proxmox host)
- Do NOT distribute the root CA to any end-user devices or browsers
- NOTE: CA rebuild generates a new root keypair — all previously issued certs become invalid.
  After this task, certs/homelab-root.crt in the repo will reflect the new CA.

PREREQUISITES BRING-UP (bring up the full 04-01 through 04-03 sequence first):

STEP 0 — Verify SDN zones are applied:
  pvesh get /nodes/pve-test/sdn/zones
  # Expected: tvmgmt, tvedge, tvsegc, tvinfra all listed

STEP 0b — Bring up harbor-stack:
  cd terraform/lxc/stacks/harbor-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.3.10," terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml

STEP 0c — Bring up apt-cacher-stack:
  cd terraform/lxc/stacks/apt-cacher-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.3.11," terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml

STEP 0d — Bring up authentik-stack (and complete first-boot setup):
  cd terraform/lxc/stacks/authentik-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.1.10," \
    terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml
  curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/
  # Must return 204 before continuing.
  # Complete first-boot and create Proxy Provider outpost (see task 04-01 Step 7).

STEP 0e — Bring up proxy-stack (Traefik):
  cd terraform/lxc/stacks/proxy-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.2.10," \
    terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml
  curl -s -o /dev/null -w "%{http_code}" http://10.57.2.10
  # Must return 301 or 302 before continuing

STEP 1 — Create branch:
  git checkout baseline/teardown-validated && git pull
  git checkout -b feat/step-ca

STEP 2 — Check IP availability:
  ping -c 3 10.57.1.11
  # Must timeout (no response)

STEP 3 — Validate stack files:
  - terraform/lxc/stacks/step-ca-stack/stack.yaml
    (VMID 152, ip_address 10.57.1.11/24, gateway 10.57.1.1, network: {zone: mgmt_seg},
     cores 1, memory 512 — no docker_storage_size)
  - terraform/lxc/stacks/step-ca-stack/terragrunt.hcl
  - Update only if the committed files drift from these values

STEP 4 — Validate Ansible playbook terraform/lxc/ansible/playbooks/deploy-step-ca.yml:
  The playbook must read STEP_CA_PASSWORD and STEP_CA_PROVISIONER_PASSWORD from
  environment (injected by ./with-secrets).
  Validate that it:
  a) Installs pinned step CLI and step-ca binaries from Smallstep GitHub releases
  b) Creates /etc/step-ca/
  c) Writes local password files at mode 0600 before bootstrap
  d) Bootstraps the CA with ACME enabled and without passing secrets on the command line
  e) Creates the systemd service for step-ca, enables it, and starts it
  f) Waits for CA health before continuing
  g) Fetches the root CA cert back to certs/homelab-root.crt in the repository root
  Update the playbook only if any of the above regresses.

STEP 5 — Validate terraform/lxc/ansible/playbooks/trust-homelab-ca.yml:
  # WARNING: Run only against managed service hosts — never end-user devices or browsers.
  Tasks:
  - copy src=certs/homelab-root.crt dest=/usr/local/share/ca-certificates/homelab-root.crt
  - command: update-ca-certificates
  Idempotent: safe to run multiple times.
  Update only if the committed playbook drifts from this behavior.

STEP 6 — Deploy step-ca LXC:
  cd terraform/lxc/stacks/step-ca-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.1.11," \
    terraform/lxc/ansible/playbooks/deploy-step-ca.yml

STEP 7 — Retroactive CA trust distribution (automatic target behavior):
  Trigger the standard post-step-ca automation to run trust-homelab-ca.yml against all
  already-deployed managed hosts.
  Temporary fallback until tooling is updated:
  # Traefik container
  ./with-secrets ansible-playbook -i "10.57.2.10," \
    terraform/lxc/ansible/playbooks/trust-homelab-ca.yml
  # Proxmox host
  ./with-secrets ansible-playbook -i "192.168.1.40," \
    terraform/lxc/ansible/playbooks/trust-homelab-ca.yml
  # Any other already-deployed LXCs — run trust-homelab-ca.yml against each

STEP 8 — Verify resolver from inside Traefik container:
  pct exec 153 -- curl -s \
    --cacert /usr/local/share/ca-certificates/homelab-root.crt \
    https://10.57.1.11/acme/acme/directory | jq .
  # Expected: ACME directory JSON with newNonce, newAccount, newOrder keys

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
  git commit -m "feat(step-ca): deploy internal CA in mgmt_seg, distribute root cert (VMID 152)"
  git checkout baseline/teardown-validated && git merge feat/step-ca
  git push origin baseline/teardown-validated

DONE WHEN: step-ca healthy, ACME directory reachable from inside Traefik container,
root CA trusted on Traefik and Proxmox host, certs/homelab-root.crt committed to repo,
base role updated. Task 04-05 (Monitoring) is now unblocked.
```
