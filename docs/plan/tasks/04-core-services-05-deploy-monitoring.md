# 04-core-services-05 — Deploy monitoring stack (VictoriaMetrics + Grafana + Loki)

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/107

## Phase

Phase 04 — Core Shared Services

## Prerequisites

- Task 04-01 complete — Authentik running (Grafana will use OIDC against it)
- Task 04-03 complete — Traefik running at `10.57.2.10` (monitoring will be exposed via proxy)
- Task 04-04 complete — step-ca running at `10.57.1.11` (Grafana uses the internal CA for its own cert via the step-ca resolver in Traefik)
- MikroTik resolver conditionally forwards `lab.gibbsgreatly.xyz` to the internal authoritative DNS server
- Phase 02 complete — pve-test at 32 GB (this stack is the most resource-heavy)
- Phase 03b complete — VictoriaMetrics, Grafana, Loki, Promtail images in Harbor proxy cache
- `10.57.1.12` available (ping-verify before deploying; also check NetBox)

## Network placement

| Field | Value |
|---|---|
| SDN zone | `mgmt_seg` |
| Proxmox VNet | `tvmgmt` (VLAN 20, `10.57.1.0/24`, gw `10.57.1.1` on MikroTik) |
| Container IP | `10.57.1.12` |
| IP selection | Third allocatable host in `mgmt_seg` after Authentik (`10.57.1.10`) and step-ca (`10.57.1.11`). Verified available with ping and NetBox check before deploying. |
| Cross-zone routing | Traefik (`10.57.2.10`) proxies Grafana dashboards from `edge_seg` to `mgmt_seg` (`10.57.1.12:3000`). MikroTik routes between VLAN 30 (edge_seg) and VLAN 20 (mgmt_seg). No inbound from LAN required — access is via Traefik only. |
| Firewall intent | Inbound: port 3000 (Grafana), 8428 (VictoriaMetrics), 3100 (Loki) from `edge_seg` (Traefik) and `build_seg` (ci-runner-01 log shipping). Outbound: ports 80/443 to Harbor (`10.57.3.10`) and apt-cacher (`10.57.3.11`) via MikroTik routing to infra_seg. Promtail scrapes logs from the local LXC only. |

## Objective

LXC `monitoring-stack` (VMID 154) is running at `10.57.1.12` in `mgmt_seg`, Grafana is primarily accessed via Traefik at `https://grafana.gibbsgreatly.xyz` with Authentik protection, the internal URL `http://10.57.1.12:3000` remains available for break-glass operations, VictoriaMetrics is scraping pve-test node_exporter, Loki is receiving logs from at least one LXC, and Grafana login works via Authentik OIDC.

Naming policy for this task:

- Public/operator route remains `grafana.gibbsgreatly.xyz`.
- Internal platform identity uses `grafana.lab.gibbsgreatly.xyz` with step-ca trust for managed internal clients.

## Scope

- Create `terraform/lxc/stacks/monitoring-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `monitoring-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`
- Set `GRAFANA_ADMIN_PASSWORD` and `GRAFANA_OAUTH_CLIENT_SECRET` to real values in `terraform/secrets.enc.yaml`
- Run `terragrunt apply` and the Ansible playbook
- Configure VictoriaMetrics datasource and Loki datasource in Grafana

## Out of Scope

- Provisioning all LXC node_exporters (add to base role in Phase 06 when LXCs are redeployed)
- Full Grafana dashboard provisioning (incrementally added in subsequent phases)
- cAdvisor or container metrics (Phase 06)

## Inputs

- `docs/plan/phase-04-core-shared-services.md` — Service 4 section
- Images (via Harbor proxy cache):
  - `10.57.3.10/dockerhub/victoriametrics/victoria-metrics:<pin>`
  - `10.57.3.10/dockerhub/grafana/grafana-oss:<pin>`
  - `10.57.3.10/dockerhub/grafana/loki:<pin>`
  - `10.57.3.10/dockerhub/grafana/promtail:<pin>`
- Authentik OIDC client secret (created in Authentik UI after task 04-01)

## Expected Outputs

- `terraform/lxc/stacks/monitoring-stack/stack.yaml` (new)
- `terraform/lxc/stacks/monitoring-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` (new)
- `terraform/secrets.enc.yaml` updated with real Grafana credential values
- LXC VMID 154 provisioned; all four containers running

## Constraints and Conventions

- `stack.yaml` values: VMID 154, IP `10.57.1.12/24`, gateway `10.57.1.1`, `network: zone: mgmt_seg`, `cores: 2`, `memory: 1536`, `docker_storage_size: "50G"`
- All images via Harbor proxy — never direct pulls
- VictoriaMetrics retention period: `90d`
- Grafana OIDC integration with Authentik (generic OAuth) — `GF_AUTH_GENERIC_OAUTH_ENABLED: "true"`
- Preferred Grafana access path is `https://grafana.gibbsgreatly.xyz` via Traefik; direct `http://10.57.1.12:3000` is operational fallback only
- Internal identity naming for the monitoring service should follow `grafana.lab.gibbsgreatly.xyz`
- Create the Authentik OIDC provider in Authentik UI before deploying Grafana
- `GRAFANA_OAUTH_CLIENT_SECRET` comes from the Authentik OIDC provider config
- Secrets injected via `./with-secrets bash -c 'ansible-playbook ... --extra-vars "..."'` — values come from `terraform/secrets.enc.yaml` via SOPS
- **LAN ingress**: Grafana (port 3000) at `10.57.1.12` is accessed via Traefik proxy, not directly from LAN. Confirm Traefik can reach port 3000 before considering this task done.

## Acceptance Criteria

- [ ] LXC VMID 154 running at `10.57.1.12` in zone `mgmt_seg`
- [ ] `curl -s http://10.57.1.12:3000/api/health` returns `{"database":"ok",...}`
- [ ] VictoriaMetrics accessible at `http://10.57.1.12:8428`
- [ ] Loki accessible at `http://10.57.1.12:3100/ready`
- [ ] Grafana datasource "VictoriaMetrics" configured and test passes
- [ ] Grafana datasource "Loki" configured and test passes
- [ ] Grafana admin login via Authentik OIDC works
- [ ] Grafana route `https://grafana.gibbsgreatly.xyz` responds through Traefik and enforces Authentik access flow
- [ ] `grafana.lab.gibbsgreatly.xyz` resolves via delegated `lab.gibbsgreatly.xyz` DNS path from SDN clients
- [ ] Managed-host trust path for `grafana.lab.gibbsgreatly.xyz` validates via step-ca
- [ ] VictoriaMetrics scraping at least pve-test node_exporter
- [ ] Loki receiving logs from at least one LXC (via Promtail)
- [ ] `dmesg | grep -i oom` on pve-test host shows no new OOM events
- [ ] All Phase 04 stacks survive `pct restart <vmid>` and return healthy
- [ ] `terraform/secrets.enc.yaml` has real values for `GRAFANA_ADMIN_PASSWORD` and `GRAFANA_OAUTH_CLIENT_SECRET` (not CHANGEME_)
- [ ] Branch `feat/monitoring-stack` merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy VictoriaMetrics + Grafana + Loki + Promtail inside a new LXC (VMID 154)
at 10.57.1.12 in mgmt_seg. This is the most resource-heavy stack — pve-test must be at 32 GB first.

CONTEXT:
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 4 section)
- VMID 154, IP 10.57.1.12/24, gateway 10.57.1.1, network zone mgmt_seg, cores 2, memory 1536, docker_storage_size 50G
- Images (all via Harbor proxy cache at 10.57.3.10):
    10.57.3.10/dockerhub/victoriametrics/victoria-metrics:<pin>
    10.57.3.10/dockerhub/grafana/grafana-oss:<pin>
    10.57.3.10/dockerhub/grafana/loki:<pin>
    10.57.3.10/dockerhub/grafana/promtail:<pin>
  Check Harbor UI for pre-pulled version tags from Phase 03b.
- Authentik OIDC provider for Grafana must be created in Authentik UI at 10.57.1.10:9000 BEFORE
  running this playbook. Record the client secret as GRAFANA_OAUTH_CLIENT_SECRET in .env.

PREREQUISITES BRING-UP (pve-test is wiped between passes — bring up the full Phase 04 stack first):

STEP 0 — Verify SDN zones are applied:
  pvesh get /nodes/pve-test/sdn/zones
  # Expected: tvmgmt, tvedge, tvsegc all listed

STEP 0b — Bring up harbor-stack:
  cd terraform/lxc/stacks/harbor-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.3.10," terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml

STEP 0c — Bring up apt-cacher-stack:
  cd terraform/lxc/stacks/apt-cacher-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook -i "10.57.3.11," terraform/lxc/ansible/playbooks/deploy-apt-cacher-stack.yml

STEP 0d — Bring up authentik-stack:
  cd terraform/lxc/stacks/authentik-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i "10.57.1.10," \
    terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml \
    --extra-vars "authentik_secret_key=${AUTHENTIK_SECRET_KEY} authentik_postgres_password=${AUTHENTIK_POSTGRES_PASSWORD}"
  curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/
  # Must return 204

STEP 0e — Bring up proxy-stack (Traefik):
  cd terraform/lxc/stacks/proxy-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets bash -c 'ansible-playbook -i "10.57.2.10," \
    terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml \
    --extra-vars "cf_dns_api_token=${CF_DNS_API_TOKEN}"'
  curl -s -o /dev/null -w "%{http_code}" http://10.57.2.10
  # Must return 301 or 302

STEP 0f — Bring up step-ca:
  cd terraform/lxc/stacks/step-ca-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets bash -c 'ansible-playbook -i "10.57.1.11," \
    terraform/lxc/ansible/playbooks/deploy-step-ca.yml \
    --extra-vars "step_ca_password=${STEP_CA_PASSWORD}"'
  curl -sk https://10.57.1.11/health
  # Must return HTTP 200 before continuing

STEP 1 — Pre-requisite: create Authentik OIDC provider for Grafana:
  In Authentik UI (http://10.57.1.10:9000), admin → Applications → Providers → OAuth2/OIDC:
  - Name: Grafana
  - Redirect URI: http://10.57.1.12:3000/login/generic_oauth
  - Copy the client ID and secret to .env as GRAFANA_OAUTH_CLIENT_ID and GRAFANA_OAUTH_CLIENT_SECRET

STEP 2 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/monitoring-stack

STEP 3 — Check IP availability:
  ping -c 3 10.57.1.12
  # Must timeout (no response)
  ./with-secrets curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://10.57.3.12/api/ipam/ip-addresses/?address=10.57.1.12" | jq .count
  # Should be 0

STEP 4 — Create stack files:
  - terraform/lxc/stacks/monitoring-stack/stack.yaml
    (VMID 154, ip_address 10.57.1.12/24, gateway 10.57.1.1, network: {zone: mgmt_seg},
     cores 2, memory 1536, docker_storage_size 50G)
  - terraform/lxc/stacks/monitoring-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 5 — Set real Grafana secrets in terraform/secrets.enc.yaml:
  SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml
  # Update these keys from CHANGEME_ to real values:
  GRAFANA_ADMIN_PASSWORD         # initial Grafana admin password
  GRAFANA_OAUTH_CLIENT_ID        # from Authentik OIDC provider (add as new key if absent)
  GRAFANA_OAUTH_CLIENT_SECRET    # from Authentik OIDC provider

STEP 6 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml:
  Deploy at /opt/monitoring-stack/docker-compose.yml with:
  - victoriametrics: --storageDataPath=/storage --retentionPeriod=90d
  - grafana: with GF_SECURITY_ADMIN_PASSWORD, GF_AUTH_GENERIC_OAUTH_ENABLED=true,
             GF_AUTH_GENERIC_OAUTH_CLIENT_ID, GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET,
             GF_AUTH_GENERIC_OAUTH_AUTH_URL=http://10.57.1.10:9000/application/o/authorize/
             GF_AUTH_GENERIC_OAUTH_TOKEN_URL=http://10.57.1.10:9000/application/o/token/
  - loki: with /loki data volume
  - promtail: scraping /var/log from host and configured to push to loki:3100

STEP 7 — Deploy:
  cd terraform/lxc/stacks/monitoring-stack && ../../../../with-secrets terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ./with-secrets bash -c 'ansible-playbook -i "10.57.1.12," terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml \
    --extra-vars "grafana_admin_password=${GRAFANA_ADMIN_PASSWORD} grafana_oauth_client_id=${GRAFANA_OAUTH_CLIENT_ID} grafana_oauth_client_secret=${GRAFANA_OAUTH_CLIENT_SECRET}"'

STEP 8 — Validate:
  curl -s http://10.57.1.12:3000/api/health | jq .database   # Expect: "ok"
  curl -s http://10.57.1.12:8428/metrics | head -5            # Expect: VM metrics
  curl -s http://10.57.1.12:3100/ready                        # Expect: ready

STEP 9 — Configure Grafana datasources (Grafana UI at http://10.57.1.12:3000):
  - Add datasource: Prometheus (or VictoriaMetrics) → URL http://victoriametrics:8428
  - Add datasource: Loki → URL http://loki:3100
  - Test both datasources

STEP 10 — OOM check on pve-test host:
  ssh root@<pve-test-host> "dmesg | grep -i oom | tail -5"
  # Should be empty (no new OOM events)

STEP 11 — Commit and merge:
  git add terraform/lxc/stacks/monitoring-stack/ terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
  git commit -m "feat(monitoring): deploy VictoriaMetrics + Grafana + Loki in mgmt_seg (VMID 154)"
  git checkout dev/pve-test && git merge feat/monitoring-stack
  git push origin dev/pve-test

DONE WHEN: All four containers running, Grafana datasources test OK, Authentik OIDC login works,
no OOM events on pve-test host. Phase 04 is complete. Phase 05 is now unblocked.
```
