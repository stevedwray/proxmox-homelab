# 04-core-services-05 — Deploy monitoring stack (VictoriaMetrics + Grafana + Loki)

## Rebuild confidence

| Criterion | State |
| --- | --- |
| IaC reproducible | Partial |
| Secrets managed | Yes — Grafana secrets flow from SOPS via `./with-secrets` into `/opt/monitoring-stack/.env` (0600) and Compose `env_file` |
| Integrations wired | Partial |
| Rebuild-safe | **No** |

See [development-status.md](../development-status.md) for the full gap analysis.

## GitHub Issue

[stevedwray/proxmox-homelab#107](https://github.com/stevedwray/proxmox-homelab/issues/107)

## Phase

Phase 04 — Core Shared Services

## Known gaps preventing rebuild-safety

1. **Depends on Authentik OIDC provider existing in SOPS.** The Grafana OIDC client ID and
   secret come from an Authentik OIDC provider that is created manually (in task 04-01
   Step 7). On a rebuild, those values will not exist until Authentik is configured and the
   resulting credentials have been added to `terraform/secrets.enc.yaml`. The monitoring
   stack cannot be deployed in a rebuild until `GRAFANA_OAUTH_CLIENT_ID` and
   `GRAFANA_OAUTH_CLIENT_SECRET` are in SOPS. This is blocked on `terraform-provider-authentik`
   for full automation (see task 04-01).

2. **Scrape targets are minimal.** Only CoreDNS (`10.57.1.13:9153`) is currently scraped.
   No scrape targets for Traefik, Authentik, step-ca, Harbor, or pve-test node_exporter.
   This is acceptable for the current development phase but should expand before Phase 05.

## Prerequisites

- Task 04-01 complete — Authentik running at `10.57.1.10`, first-boot complete
- Task 04-01 Step 7 complete — Grafana OIDC provider created in Authentik UI, resulting
  `GRAFANA_OAUTH_CLIENT_ID` and `GRAFANA_OAUTH_CLIENT_SECRET` recorded in
  `terraform/secrets.enc.yaml`
- Task 04-03 complete — Traefik running at `10.57.2.10`
- Task 04-04 complete — step-ca running at `10.57.1.11` (CA trust distributed to managed hosts)
- MikroTik resolver conditionally forwards `lab.gibbsgreatly.xyz` to CoreDNS
- Phase 02 complete — pve-test at 32 GB (this stack is the most resource-heavy)
- `10.57.1.12` available (ping-verify before deploying)
- `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_OAUTH_CLIENT_ID`, `GRAFANA_OAUTH_CLIENT_SECRET` set to
  real values in `terraform/secrets.enc.yaml`

## Network placement

| Field | Value |
| --- | --- |
| SDN zone | `mgmt_seg` |
| Proxmox VNet | `tvmgmt` (VLAN 20, `10.57.1.0/24`, gw `10.57.1.1` on MikroTik) |
| Container IP | `10.57.1.12` |
| Cross-zone routing | Traefik (`10.57.2.10`) proxies Grafana from `edge_seg` to `mgmt_seg` (`10.57.1.12:3000`). No direct LAN access required — access is via Traefik only. |
| Firewall intent | Inbound: port 3000 (Grafana), 8428 (VictoriaMetrics), 3100 (Loki) from `edge_seg` (Traefik) and `build_seg` (ci-runner-01 log shipping). Outbound: ports 80/443 to Harbor and apt-cacher via infra_seg. |

## Objective

LXC `monitoring-stack` (VMID 154) is running at `10.57.1.12` in `mgmt_seg`. Grafana is
primarily accessed via Traefik at `https://grafana.gibbsgreatly.xyz` with Authentik SSO
protection. All secrets are injected from SOPS at deploy time — no credentials in any on-disk
file. VictoriaMetrics scrapes CoreDNS. Loki receives logs from at least one LXC. Grafana
login works via Authentik OIDC.

Naming policy for this task:

- Public/operator route: `grafana.gibbsgreatly.xyz`
- Internal platform identity: `grafana.lab.gibbsgreatly.xyz`

## Scope

- Create `terraform/lxc/stacks/monitoring-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `monitoring-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` — secrets injected
  from SOPS; compose file references env vars only via `env_file`
- Confirm `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_OAUTH_CLIENT_ID`, `GRAFANA_OAUTH_CLIENT_SECRET`
  are real values in `terraform/secrets.enc.yaml` before deploying
- Run `./with-secrets terragrunt apply` and the Ansible playbook
- Configure VictoriaMetrics and Loki datasources in Grafana

## Out of Scope

- Provisioning all LXC node_exporters (add to base role in Phase 06 when LXCs are redeployed)
- Full Grafana dashboard provisioning (added incrementally in subsequent phases)
- cAdvisor or container metrics (Phase 06)
- Expanding VictoriaMetrics scrape targets beyond CoreDNS (Phase 05)
- `terraform-provider-authentik` implementation — tracked in task 04-01

## Inputs

- `docs/plan/phase-04-core-shared-services.md` — Service 4 section
- Images (via Harbor proxy cache):
  - `10.57.3.10/dockerhub/victoriametrics/victoria-metrics:<pin>`
  - `10.57.3.10/dockerhub/grafana/grafana-oss:<pin>`
  - `10.57.3.10/dockerhub/grafana/loki:<pin>`
  - `10.57.3.10/dockerhub/grafana/promtail:<pin>`
- `GRAFANA_OAUTH_CLIENT_ID` and `GRAFANA_OAUTH_CLIENT_SECRET` from `terraform/secrets.enc.yaml`
  (created in Authentik UI in task 04-01 Step 7)

## Expected Outputs

- `terraform/lxc/stacks/monitoring-stack/stack.yaml`
- `terraform/lxc/stacks/monitoring-stack/terragrunt.hcl`
- `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` — secrets via env_file
- On-disk compose file at `/opt/monitoring-stack/docker-compose.yml` contains no literal credentials
- LXC VMID 154 provisioned; all four containers running

## Constraints and Conventions

- `stack.yaml` values: VMID 154, IP `10.57.1.12/24`, gateway `10.57.1.1`,
  `network: zone: mgmt_seg`, `cores: 2`, `memory: 1536`, `docker_storage_size: "50G"`
- All images via Harbor proxy — never direct pulls
- VictoriaMetrics retention period: `90d`
- Grafana OIDC: `GF_AUTH_GENERIC_OAUTH_ENABLED: "true"` — all OAuth config via env vars from SOPS
- Preferred Grafana access path is `https://grafana.gibbsgreatly.xyz` via Traefik;
  direct `http://10.57.1.12:3000` is operational fallback only
- Secrets injection: `./with-secrets` wraps all commands; playbook writes a SOPS-sourced
  `.env` file; Docker Compose reads it via `env_file`; no `--extra-vars` for secrets
- **LAN ingress**: Grafana accessed via Traefik proxy — confirm Traefik can reach port 3000
- `dns_server` must be set in `stack.yaml` for the monitoring LXC: `10.57.1.1` (`mgmt_seg` gateway)

## Acceptance Criteria

- [ ] LXC VMID 154 running at `10.57.1.12` in zone `mgmt_seg`
- [ ] `curl -s http://10.57.1.12:3000/api/health` returns `{"database":"ok",...}`
- [ ] VictoriaMetrics accessible at `http://10.57.1.12:8428`
- [ ] Loki accessible at `http://10.57.1.12:3100/ready`
- [ ] `/opt/monitoring-stack/docker-compose.yml` contains no literal credentials
- [ ] Grafana datasource "VictoriaMetrics" configured and test passes
- [ ] Grafana datasource "Loki" configured and test passes
- [ ] Grafana admin login via Authentik OIDC works
- [ ] Grafana route `https://grafana.gibbsgreatly.xyz` responds through Traefik and enforces
  Authentik access flow
- [ ] VictoriaMetrics scraping CoreDNS at `10.57.1.13:9153` (current minimum target set)
- [ ] Loki receiving logs from at least one LXC (via Promtail)
- [ ] `dmesg | grep -i oom` on pve-test host shows no new OOM events
- [ ] All Phase 04 stacks survive `pct restart <vmid>` and return healthy
- [ ] `terraform/secrets.enc.yaml` has real values for all three Grafana secrets
- [ ] Branch `feat/monitoring-stack` merged to `dev/pve-test`

### DNS delegation validation commands (required)

Run from a host that can query SDN zone gateways directly:

```bash
dig @10.57.0.1 +short traefik.lab.gibbsgreatly.xyz
dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz
dig @10.57.2.1 +short traefik.lab.gibbsgreatly.xyz
dig @10.57.3.1 +short traefik.lab.gibbsgreatly.xyz
dig @10.57.1.1 +short github.com
```

All four `traefik.lab.gibbsgreatly.xyz` queries must return delegated answers.
`github.com` must still resolve through the MikroTik resolver path.

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy VictoriaMetrics + Grafana + Loki + Promtail inside a new LXC (VMID 154)
at 10.57.1.12 in mgmt_seg. This is the most resource-heavy stack — pve-test must be at
32 GB first.

IMPORTANT: All secret values are in terraform/secrets.enc.yaml and must be injected via
./with-secrets. Do not pass Grafana credentials or OAuth secrets as --extra-vars.
The playbook must write a .env file (read by Docker Compose via env_file) sourced from SOPS.
No literal credentials on disk.

CONTEXT:
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 4 section)
- VMID 154, IP 10.57.1.12/24, gateway 10.57.1.1, network zone mgmt_seg, cores 2,
  memory 1536, docker_storage_size 50G
- Images (all via Harbor proxy cache at 10.57.3.10):
    10.57.3.10/dockerhub/victoriametrics/victoria-metrics:<pin>
    10.57.3.10/dockerhub/grafana/grafana-oss:<pin>
    10.57.3.10/dockerhub/grafana/loki:<pin>
    10.57.3.10/dockerhub/grafana/promtail:<pin>
- GRAFANA_OAUTH_CLIENT_ID and GRAFANA_OAUTH_CLIENT_SECRET must already be in
  terraform/secrets.enc.yaml before this task begins — they are created in Authentik UI
  during task 04-01 Step 7. If they are still CHANGEME_ values, stop and complete that
  step first. This is a known rebuild gap until terraform-provider-authentik is implemented.

PREREQUISITES BRING-UP (bring up the full Phase 04 stack first):

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

STEP 0d — Bring up authentik-stack (and complete first-boot):
  cd terraform/lxc/stacks/authentik-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.1.10," \
    terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml
  curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/
  # Must return 204.
  # Complete first-boot and create Grafana OIDC provider (see task 04-01 Step 7).
  # Confirm GRAFANA_OAUTH_CLIENT_ID and GRAFANA_OAUTH_CLIENT_SECRET are in SOPS.

STEP 0e — Bring up proxy-stack (Traefik):
  cd terraform/lxc/stacks/proxy-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.2.10," \
    terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml
  curl -s -o /dev/null -w "%{http_code}" http://10.57.2.10
  # Must return 301 or 302

STEP 0f — Bring up step-ca and distribute CA trust:
  cd terraform/lxc/stacks/step-ca-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.1.11," \
    terraform/lxc/ansible/playbooks/deploy-step-ca.yml
  curl -sk https://10.57.1.11/health
  # Must return HTTP 200.
  # Then run retroactive CA trust distribution (see task 04-04 Step 7).

STEP 1 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/monitoring-stack

STEP 2 — Check IP availability:
  ping -c 3 10.57.1.12
  # Must timeout (no response)

STEP 3 — Confirm secrets in SOPS:
  SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --decrypt terraform/secrets.enc.yaml \
    | grep -E "GRAFANA_ADMIN_PASSWORD|GRAFANA_OAUTH_CLIENT_ID|GRAFANA_OAUTH_CLIENT_SECRET"
  # All three must have real values (not CHANGEME_)
  # If not, stop — update them in SOPS before continuing:
  #   SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml

STEP 4 — Create stack files:
  - terraform/lxc/stacks/monitoring-stack/stack.yaml
    (VMID 154, ip_address 10.57.1.12/24, gateway 10.57.1.1, network: {zone: mgmt_seg},
     cores 2, memory 1536, docker_storage_size 50G, dns_server 10.57.1.1)
  - terraform/lxc/stacks/monitoring-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 5 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml:
  The playbook must read all credentials from environment (injected by ./with-secrets).
  Deploy at /opt/monitoring-stack/ with:
  a) Write /opt/monitoring-stack/.env from SOPS-injected env (no literal values):
       GRAFANA_ADMIN_PASSWORD={{ lookup('env', 'GRAFANA_ADMIN_PASSWORD') }}
       GRAFANA_OAUTH_CLIENT_ID={{ lookup('env', 'GRAFANA_OAUTH_CLIENT_ID') }}
       GRAFANA_OAUTH_CLIENT_SECRET={{ lookup('env', 'GRAFANA_OAUTH_CLIENT_SECRET') }}
  b) Write docker-compose.yml referencing env_file: .env (no literal secret values)
     Services:
     - victoriametrics: --storageDataPath=/storage --retentionPeriod=90d
     - grafana: GF_SECURITY_ADMIN_PASSWORD, GF_AUTH_GENERIC_OAUTH_ENABLED=true,
                GF_AUTH_GENERIC_OAUTH_CLIENT_ID, GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET,
                GF_AUTH_GENERIC_OAUTH_AUTH_URL=http://10.57.1.10:9000/application/o/authorize/
                GF_AUTH_GENERIC_OAUTH_TOKEN_URL=http://10.57.1.10:9000/application/o/token/
     - loki: with /loki data volume
     - promtail: scraping /var/log, pushing to loki:3100
  c) docker compose up -d

STEP 6 — Deploy:
  cd terraform/lxc/stacks/monitoring-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.1.12," \
    terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml

STEP 7 — Validate:
  curl -s http://10.57.1.12:3000/api/health | jq .database   # Expect: "ok"
  curl -s http://10.57.1.12:8428/metrics | head -5            # Expect: VM metrics
  curl -s http://10.57.1.12:3100/ready                        # Expect: ready

  # Verify no literal credentials in compose file:
  pct exec 154 -- grep -i "GRAFANA_ADMIN_PASSWORD" /opt/monitoring-stack/docker-compose.yml
  # Must show only env var reference, not a password value

STEP 8 — Configure Grafana datasources (Grafana UI at http://10.57.1.12:3000):
  - Add datasource: Prometheus/VictoriaMetrics → URL http://victoriametrics:8428
  - Add datasource: Loki → URL http://loki:3100
  - Test both datasources

STEP 9 — OOM check on pve-test host:
  ssh root@pve-test.gibbsgreatly.xyz "dmesg | grep -i oom | tail -5"
  # Should be empty (no new OOM events after monitoring stack deploy)

STEP 10 — Commit and merge:
  git add terraform/lxc/stacks/monitoring-stack/ \
          terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
  git commit -m "feat(monitoring): deploy VictoriaMetrics + Grafana + Loki in mgmt_seg (VMID 154)"
  git checkout dev/pve-test && git merge feat/monitoring-stack
  git push origin dev/pve-test

DONE WHEN: All four containers running, compose file has no literal credentials, Grafana
datasources test OK, Authentik OIDC login works, no OOM events. Phase 04 complete.
```
