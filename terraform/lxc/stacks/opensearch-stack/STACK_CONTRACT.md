# opensearch-stack — Stack Contract

## Purpose

Dedicated, single-node OpenSearch + OpenSearch Dashboards store for
security findings — replacing `elasticsearch-stack` (vmid 40013). Same
purpose as that stack (Harbor vulnerability scan results, later GVM/
Greenbone network scan results — see `docs/elasticsearch-stack/plan.md`,
being migrated to `docs/opensearch-stack/`), different engine: Elasticsearch's
SAML/OIDC realm requires a paid Platinum+ subscription, which the operator
declined to pay for. OpenSearch's security plugin bundles SAML/OIDC for
free, so real Authentik single-sign-on is achievable here without a paid
license — see `/home/steve/.claude/plans/jiggly-cuddling-squid.md` for the
full migration plan and rationale.

Not the legacy `elastic-stack` LXC (vmid 112, `192.168.1.24`) — that
container is a separate, drifted, natively-installed instance, unrelated
and out of scope. Not a resurrection of Wazuh/Security Onion/TPOTCE.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `infra_seg` (VLAN 40)    |
| IP           | `192.168.40.14/24`       |
| Gateway      | `192.168.40.1`           |
| VMID         | 40014                    |

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| Harbor registry | `registry_host` (`LAB_IP_HARBOR`) | Image pulls via the existing `dockerhub` proxy-cache project — `opensearchproject/opensearch` and `opensearchproject/opensearch-dashboards` are OpenSearch's own official Docker Hub publish targets |
| apt-cacher | `apt_cacher_host:3142` | apt proxy during provisioning |
| `OPENSEARCH_ADMIN_PASSWORD` | SOPS `terraform/secrets.common.enc.yaml` | **New secret.** Sets `OPENSEARCH_INITIAL_ADMIN_PASSWORD` — mandatory as of OpenSearch 2.12+, the security plugin refuses to start without it. |
| `OPENSEARCH_OIDC_CLIENT_SECRET` | SOPS `terraform/secrets.common.enc.yaml` | **New secret, added at Stage 4 (OIDC).** Authentik OAuth2 client secret for Dashboards' real SSO login. |
| `LAB_IP_OPENSEARCH` | `.env` | **New.** Needed for `edge.yaml`'s `${LAB_IP_OPENSEARCH}` interpolation. |

## Provides

| Service | Port | Protocol | Notes |
|---------|------|----------|-------|
| `opensearch-http` | 9200 | tcp | Auth required (security plugin enabled). **TLS stays ON for the HTTP layer** — unlike elasticsearch-stack's `xpack.security.http.ssl.enabled=false`, OpenSearch 2.12+ has an [open bug](https://github.com/opensearch-project/security/issues/4348) when the equivalent (`plugins.security.ssl.http.enabled=false`) is disabled (demo certs don't even get generated). Internal callers use OpenSearch's own demo/self-signed cert and skip verification rather than fight this. Internal-only, no public Traefik route by design. |
| `opensearch-dashboards-http` | 5601 | tcp | Fronted by Traefik with **real OIDC** (`auth.mode: oidc` in `edge.yaml`, not just forwardAuth) — Authentik login lands the user directly in Dashboards, authenticated. This is the actual point of the migration; see Stage 4 of the plan. |

## Dependencies

| Stack | Why |
|-------|-----|
| `harbor-stack` | Image pulls via the `dockerhub` proxy-cache project |
| `apt-cacher-stack` | apt proxy during provisioning |

Cross-zone access (Grafana datasource, GVM sync job) and the Harbor
findings-ingestion re-point are separate, later work — not part of
standing this stack up. See the migration plan's revised sequencing.

## Persistent State

| Path | Storage | Contents |
|------|---------|----------|
| `/var/lib/opensearch-data` | `extra_mount` (150G, `durable-zfs` profile, grow-only) | OpenSearch index data. |
| Docker volumes (`docker_storage`, 20G) | `docker_mount` | Dashboards' own small data volume. |

## What Must Not Be Edited Casually

- `discovery.type=single-node` is deliberate — same reasoning as
  elasticsearch-stack: this is not a cluster, home-lab scale, accepted
  single point of failure.
- HTTP-layer TLS stays **enabled** (opposite of elasticsearch-stack's
  choice) — see Provides table above. Do not try to disable it without
  first confirming the OpenSearch 2.12+ bug is actually fixed in whatever
  version is running.
- `OPENSEARCH_INITIAL_ADMIN_PASSWORD` is only consulted on first bootstrap
  (empty data directory) — rotating the SOPS secret later does not change
  the live admin password; that needs OpenSearch's own user-management API.

## Playbook

`deploy-opensearch-stack`

Same shape as `deploy-elasticsearch-stack.yml`: `lxc_base` + `docker_base`
+ conditional `docker_socket_proxy`, plus direct tasks templating
`docker-compose.yml` inline (heap sizing computed from real container
memory, same formula as Graylog's Data Node / the old elasticsearch-stack).

## Implementation Files

| File | Role | Status |
|------|------|--------|
| `terraform/lxc/stacks/opensearch-stack/stack.yaml` | Terraform-side stack definition | new |
| `terraform/lxc/stacks/opensearch-stack/edge.yaml` | Traefik/Authentik OIDC route for Dashboards | new |
| `terraform/lxc/stacks/opensearch-stack/terragrunt.hcl` | Terragrunt entrypoint (boilerplate) | new |
| `terraform/lxc/environments/pve/opensearch-stack/` | Terragrunt entrypoint | new |
| `terraform/lxc/ansible/playbooks/deploy-opensearch-stack.yml` | Stack playbook | new |

The `es_findings_ingest` role (reworked for OpenSearch's security API) is
separate, later work — out of scope for getting this stack itself running
and logged into.
