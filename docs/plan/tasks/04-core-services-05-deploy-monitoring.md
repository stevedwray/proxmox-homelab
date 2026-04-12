# 04-core-services-05 — Deploy monitoring stack (VictoriaMetrics + Grafana + Loki)

## Status

PENDING

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/107

## Phase

Phase 04 — Core Shared Services

## Prerequisites

- Task 04-01 complete — Authentik running (Grafana will use OIDC against it)
- Task 04-04 complete — Traefik running (monitoring will be exposed via proxy)
- Phase 02 complete — pve-test at 32 GB (this stack is the most resource-heavy)
- Phase 03b complete — VictoriaMetrics, Grafana, Loki, Promtail images in Harbor proxy cache
- `192.168.1.44` available (verify in NetBox before deploying)

## Objective

LXC `monitoring-stack` (VMID 154) is running at `192.168.1.44`, Grafana is accessible at `http://192.168.1.44:3000`, VictoriaMetrics is scraping pve-test node_exporter, Loki is receiving logs from at least one LXC, and Grafana login works via Authentik OIDC.

## Scope

- Create `terraform/lxc/stacks/monitoring-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `monitoring-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`
- Add `GRAFANA_ADMIN_PASSWORD` and `GRAFANA_OAUTH_CLIENT_SECRET` to `.env.template`
- Run `terragrunt apply` and the Ansible playbook
- Configure VictoriaMetrics datasource and Loki datasource in Grafana

## Out of Scope

- Provisioning all LXC node_exporters (add to base role in Phase 06 when LXCs are redeployed)
- Full Grafana dashboard provisioning (incrementally added in subsequent phases)
- cAdvisor or container metrics (Phase 06)

## Inputs

- `docs/plan/phase-04-core-shared-services.md` — Service 5 section
- Images (via Harbor proxy cache):
  - `192.168.1.10/dockerhub/victoriametrics/victoria-metrics:<pin>`
  - `192.168.1.10/dockerhub/grafana/grafana-oss:<pin>`
  - `192.168.1.10/dockerhub/grafana/loki:<pin>`
  - `192.168.1.10/dockerhub/grafana/promtail:<pin>`
- Authentik OIDC client secret (created in Authentik UI after task 04-01)

## Expected Outputs

- `terraform/lxc/stacks/monitoring-stack/stack.yaml` (new)
- `terraform/lxc/stacks/monitoring-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` (new)
- `.env.template` updated with monitoring secrets
- LXC VMID 154 provisioned; all four containers running

## Constraints and Conventions

- `stack.yaml` values: VMID 154, IP `192.168.1.44/24`, `cores: 2`, `memory: 3072`, `docker_storage_size: "50G"`
- All images via Harbor proxy — never direct pulls
- VictoriaMetrics retention period: `90d`
- Grafana OIDC integration with Authentik (generic OAuth) — `GF_AUTH_GENERIC_OAUTH_ENABLED: "true"`
- Create the Authentik OIDC provider in Authentik UI before deploying Grafana
- `GRAFANA_OAUTH_CLIENT_SECRET` comes from the Authentik OIDC provider config
- Secrets injected via `--extra-vars` sourced from `.env`
- **LAN ingress**: Grafana (port 3000) at `192.168.1.44` must be reachable from workstations on the LAN. LXC is on `mgmt_seg` so no cross-segment routing is needed, but confirm port 3000 is published and accessible before considering this task done.

## Acceptance Criteria

- [ ] LXC VMID 154 running at `192.168.1.44`
- [ ] `curl -s http://192.168.1.44:3000/api/health` returns `{"database":"ok",...}`
- [ ] VictoriaMetrics accessible at `http://192.168.1.44:8428`
- [ ] Loki accessible at `http://192.168.1.44:3100/ready`
- [ ] Grafana datasource "VictoriaMetrics" configured and test passes
- [ ] Grafana datasource "Loki" configured and test passes
- [ ] Grafana admin login via Authentik OIDC works
- [ ] VictoriaMetrics scraping at least pve-test node_exporter
- [ ] Loki receiving logs from at least one LXC (via Promtail)
- [ ] `dmesg | grep -i oom` on pve-test host shows no new OOM events
- [ ] All Phase 04 stacks survive `pct restart <vmid>` and return healthy
- [ ] `.env.template` has `GRAFANA_ADMIN_PASSWORD` and `GRAFANA_OAUTH_CLIENT_SECRET`
- [ ] Branch `feat/monitoring-stack` merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy VictoriaMetrics + Grafana + Loki + Promtail inside a new LXC (VMID 154)
at 192.168.1.44. This is the most resource-heavy stack — pve-test must be at 32 GB first.

CONTEXT:
- Reference for stack.yaml format: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-04-core-shared-services.md (Service 5 section)
- VMID 154, IP 192.168.1.44, cores 2, memory 3072, docker_storage_size 50G
- Images (all via Harbor proxy cache at 192.168.1.10):
    victoriametrics/victoria-metrics:<pin>
    grafana/grafana-oss:<pin>
    grafana/loki:<pin>
    grafana/promtail:<pin>
  Check Harbor UI for pre-pulled version tags from Phase 03b.
- Authentik OIDC provider for Grafana must be created in Authentik UI at 192.168.1.46 BEFORE
  running this playbook. Record the client secret as GRAFANA_OAUTH_CLIENT_SECRET in .env.

STEP 1 — Pre-requisite: create Authentik OIDC provider for Grafana:
  In Authentik UI (http://192.168.1.46:9000), admin → Applications → Providers → OAuth2/OIDC:
  - Name: Grafana
  - Redirect URI: http://192.168.1.44:3000/login/generic_oauth
  - Copy the client ID and secret to .env as GRAFANA_OAUTH_CLIENT_ID and GRAFANA_OAUTH_CLIENT_SECRET

STEP 2 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/monitoring-stack

STEP 3 — Check IP availability:
  source .env
  curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.44" | jq .count
  # Must be 0

STEP 4 — Create stack files:
  - terraform/lxc/stacks/monitoring-stack/stack.yaml (VMID 154, IP 192.168.1.44/24, cores 2, memory 3072, docker_storage_size 50G)
  - terraform/lxc/stacks/monitoring-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 5 — Add secrets to .env.template and .env:
  GRAFANA_ADMIN_PASSWORD=        # initial Grafana admin password
  GRAFANA_OAUTH_CLIENT_ID=       # from Authentik OIDC provider
  GRAFANA_OAUTH_CLIENT_SECRET=   # from Authentik OIDC provider

STEP 6 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml:
  Deploy at /opt/monitoring-stack/docker-compose.yml with:
  - victoriametrics: --storageDataPath=/storage --retentionPeriod=90d
  - grafana: with GF_SECURITY_ADMIN_PASSWORD, GF_AUTH_GENERIC_OAUTH_ENABLED=true,
             GF_AUTH_GENERIC_OAUTH_CLIENT_ID, GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET,
             GF_AUTH_GENERIC_OAUTH_AUTH_URL=http://192.168.1.46:9000/application/o/authorize/
             GF_AUTH_GENERIC_OAUTH_TOKEN_URL=http://192.168.1.46:9000/application/o/token/
  - loki: with /loki data volume
  - promtail: scraping /var/log from host and configured to push to loki:3100

STEP 7 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/monitoring-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "192.168.1.44," terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml \
    --extra-vars "grafana_admin_password=${GRAFANA_ADMIN_PASSWORD} grafana_oauth_client_id=${GRAFANA_OAUTH_CLIENT_ID} grafana_oauth_client_secret=${GRAFANA_OAUTH_CLIENT_SECRET}"

STEP 8 — Validate:
  curl -s http://192.168.1.44:3000/api/health | jq .database   # Expect: "ok"
  curl -s http://192.168.1.44:8428/metrics | head -5            # Expect: VM metrics
  curl -s http://192.168.1.44:3100/ready                        # Expect: ready

STEP 9 — Configure Grafana datasources (Grafana UI at http://192.168.1.44:3000):
  - Add datasource: Prometheus (or VictoriaMetrics) → URL http://victoriametrics:8428
  - Add datasource: Loki → URL http://loki:3100
  - Test both datasources

STEP 10 — OOM check on pve-test host:
  ssh root@<pve-test-host> "dmesg | grep -i oom | tail -5"
  # Should be empty (no new OOM events)

STEP 11 — Commit and merge:
  git add terraform/lxc/stacks/monitoring-stack/ terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml .env.template
  git commit -m "feat(monitoring): deploy VictoriaMetrics + Grafana + Loki monitoring stack (VMID 154)"
  git checkout dev/pve-test && git merge feat/monitoring-stack
  git push origin dev/pve-test

DONE WHEN: All four containers running, Grafana datasources test OK, Authentik OIDC login works,
no OOM events on pve-test host. Phase 04 is complete. Phase 05 is now unblocked.
```
