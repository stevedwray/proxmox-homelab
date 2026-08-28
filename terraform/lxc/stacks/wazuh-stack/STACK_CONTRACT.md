# wazuh-stack — Stack Contract

## Purpose

Wazuh (open-source SIEM/host intrusion detection) — manager + indexer +
dashboard, Wazuh's official single-node Docker deployment. Server-only
in this pass: no agents enrolled, no telemetry, no ingestion into
`opensearch-stack`. See `docs/wazuh-stack/plan.md` for the full design
and phase scope. Not a resurrection of the separate, unrelated
`security-stack` LXC (vmid 109, `192.168.1.11`).

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `infra_seg` (VLAN 40)    |
| IP           | `192.168.40.15/24`       |
| Gateway      | `192.168.40.1`           |
| VMID         | 40015                    |

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `LAB_IP_HARBOR` | env var (mandatory) | Registry host — images pull via the existing `dockerhub` proxy-cache project; no dedicated Wazuh Harbor project needed |
| `LAB_IP_APT_CACHER` | `apt_cacher_host` (stack.yaml) | apt proxy during provisioning |
| `WAZUH_INDEXER_ADMIN_PASSWORD` | SOPS (`terraform/secrets.common.enc.yaml`), mandatory | Replaces the indexer's demo `admin` password on first bootstrap |
| `WAZUH_API_PASSWORD` | SOPS (`terraform/secrets.common.enc.yaml`), mandatory | Replaces the manager/dashboard's shared `wazuh-wui` API service-account password |
| `WAZUH_OIDC_CLIENT_SECRET` | SOPS (`terraform/secrets.common.enc.yaml`), mandatory | Authentik OAuth2 client secret for the dashboard's OIDC login |
| `LAB_IP_AUTHENTIK` | env var (mandatory) | Authentik host, for the OIDC discovery URL |
| `LAB_IP_WAZUH` | `.env` | This stack's own IP |

## Provides

| Service | Port | Protocol | Notes |
|---------|------|----------|-------|
| `wazuh-dashboard-http` | 5601 | tcp | Fronted by Traefik with real OIDC (`auth.mode: oidc` in `edge.yaml`), same pattern as `opensearch-stack`'s Dashboards route |
| `wazuh-manager-agent` | 1514 | tcp | Agent event reporting — bound by the manager, not consumed by anything yet this phase |
| `wazuh-manager-enrollment` | 1515 | tcp | Agent enrollment — same, unused this phase |
| `wazuh-api` | 55000 | tcp | Wazuh API — internal-only, used by the dashboard itself |

## Dependencies

| Stack | Why |
|-------|-----|
| `harbor-stack` | Image pulls via the `dockerhub` proxy-cache project |
| `apt-cacher-stack` | apt proxy during LXC provisioning |
| `authentik-stack` | OIDC client for the dashboard's SSO login |

## Persistent State

| Path | Storage | Contents |
|------|---------|----------|
| `/var/lib/wazuh-indexer-data` | `extra_mount` (50G, `durable-zfs` profile, grow-only) | Wazuh indexer index data |
| Docker named volumes under `/var/lib/docker` | `docker_mount` (20G) | Manager config/queue/logs, indexer SSL certs, dashboard config |

## What Must Not Be Edited Casually

- Upstream's official compose sets `memlock: -1:-1` (unlimited) on both
  `wazuh.manager` and `wazuh.indexer` — this is stripped in this stack's
  compose. Nested LXC rejects an unlimited memlock ulimit, the same
  failure mode already confirmed for `elasticsearch-stack`/
  `opensearch-stack`. Do not restore these ulimits from upstream's file.
- Certificate generation is a one-time pre-step (Wazuh's own
  `generate-indexer-certs.yml` helper), run before the main compose's
  first `up` — not a service inside the main stack.
- `WAZUH_INDEXER_ADMIN_PASSWORD` and `WAZUH_API_PASSWORD` are only
  consulted on first bootstrap. Rotating the SOPS secret later does not
  change the live password without running Wazuh's own
  password-rotation tool.
- `vm.max_map_count` on the host must be `262144` (verified already true
  on `pve` as of 2026-08-17 for the same reason `elasticsearch-stack`
  needed it — host-kernel-wide, not per-container). Re-verify on
  `pve-test-vm` rather than assuming it's inherited.

## Playbook

`deploy-wazuh-stack`

Same shape as `deploy-opensearch-stack.yml`/`deploy-greenbone-stack.yml`:
`lxc_base` + `docker_base`, plus direct tasks vendoring Wazuh's official
compose (images rewritten through Harbor's `dockerhub` proxy-cache
project, `memlock` ulimits stripped) rather than a dedicated role.

## Implementation Files

| File | Role | Status |
|------|------|--------|
| `terraform/lxc/stacks/wazuh-stack/stack.yaml` | Terraform-side stack definition | new |
| `terraform/lxc/stacks/wazuh-stack/edge.yaml` | Traefik/Authentik OIDC route for the dashboard | new |
| `terraform/lxc/stacks/wazuh-stack/terragrunt.hcl` | Terragrunt entrypoint (boilerplate) | new |
| `terraform/lxc/environments/pve-test-vm/wazuh-stack/` | Terragrunt entrypoint (validation) | new |
| `terraform/lxc/ansible/playbooks/deploy-wazuh-stack.yml` | Stack playbook | new |
| `terraform/lxc/ansible/files/wazuh-stack/add_openid_auth_domain.py` | Helper: adds the `openid_auth_domain` block to the indexer's live security config.yml (no vendored source exists for that file) | new |
