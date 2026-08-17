# elasticsearch-stack — Stack Contract

## Purpose

Dedicated, single-node Elasticsearch + Kibana store for security findings —
starting with Harbor vulnerability scan results and GVM/Greenbone network
scan results (see `docs/elasticsearch-stack/plan.md`). Not a resurrection
of Wazuh/Security Onion/TPOTCE, and not the legacy `elastic-stack` LXC
(vmid 112, `192.168.1.24`) — that container is a separate, drifted,
natively-installed instance out of scope for this stack; see plan.md's
"Corrected facts about the legacy container" for why it isn't reused.
End goal is a store an LLM/automation layer can read, enrich, and act on
(`findings-mcp`, later phase), not primarily a human dashboard.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `infra_seg` (VLAN 40)    |
| IP           | `192.168.40.13/24`       |
| Gateway      | `192.168.40.1`           |
| VMID         | 40013                    |

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| Harbor registry | `registry_host` (`LAB_IP_HARBOR`) | Image pulls via the existing `dockerhub` proxy-cache project — `elastic/elasticsearch` and `elastic/kibana` are Elastic's own official Docker Hub publish target (confirmed live 2026-08-17), no new Harbor mirror project needed |
| apt-cacher | `apt_cacher_host:3142` | apt proxy during provisioning |
| `ELASTIC_PASSWORD` | SOPS `terraform/secrets.common.enc.yaml` | **New secret, not yet added.** Built-in `elastic` superuser password. Must be added before Stage 3 (Ansible deploy) can run. |
| `ELASTIC_KIBANA_SYSTEM_PASSWORD` | SOPS `terraform/secrets.common.enc.yaml` | **New secret, not yet added.** Password the playbook sets for the built-in `kibana_system` service user (via the ES security API, same pattern Elastic's own official docker-compose reference uses) so Kibana can authenticate to Elasticsearch. |
| `LAB_IP_ELASTICSEARCH` | `.env.pve` (and `.env.pve-test-vm` if ever needed there) | **Not yet added.** Needed for `edge.yaml`'s `${LAB_IP_ELASTICSEARCH}` interpolation once Stage 4 (edge exposure) runs. |

## Provides

| Service | Port | Protocol | Notes |
|---------|------|----------|-------|
| `elasticsearch-http` | 9200 | tcp | Auth required (`xpack.security.enabled=true`), plain HTTP not TLS — internal-only, no public Traefik route by design (see plan.md's Auth decision). Reached only from inside the SDN: `harbor-stack` (same zone), and after Stage 5's additive rules, `mgmt_seg` (Grafana datasource) and `pentest_seg` (GVM sync job). |
| `kibana-http` | 5601 | tcp | Fronted by Traefik `forwardAuth` (Authentik) at `kibana.${LAB_DOMAIN}` — see `edge.yaml`. No native Kibana OIDC on the free tier. |

## Dependencies

| Stack | Why |
|-------|-----|
| `harbor-stack` | Image pulls (`elastic/elasticsearch`, `elastic/kibana` via the `dockerhub` proxy-cache project) |
| `apt-cacher-stack` | apt proxy during provisioning |

Cross-zone access needed (additive, Stage 5 of `runbook.md`, applied
directly on the MikroTik — not Terraform-managed):
`mgmt_seg → infra_seg tcp/9200` (Grafana datasource) and
`pentest_seg → infra_seg tcp/9200` (GVM findings sync job). A third,
`ai_seg → infra_seg tcp/9200`, is deferred until `findings-mcp` actually
exists (plan.md Phase 8) — no rule before something needs it.

## Persistent State

| Path | Storage | Contents |
|------|---------|----------|
| `/var/lib/elasticsearch-data` | `extra_mount` (150G, `durable-zfs` profile, grow-only) | Elasticsearch index data — bind-mounted into the `elasticsearch` container at `/usr/share/elasticsearch/data`. Owned `1000:1000` (the image's non-root `elasticsearch` user). |
| Docker volumes (`docker_storage`, 20G) | `docker_mount` | Kibana's own small data volume (saved objects cache, etc.) — not index data. |

## What May Depend On This Stack

- `findings-mcp` (later phase, `ai_seg`) — reads/writes findings via a
  scoped ES API key, not raw admin credentials.
- The Harbor and GVM findings-sync jobs (`harbor-stack`, `pentest_seg`
  respectively) — write findings via bulk index API.
- Grafana (`monitoring-stack`) — reads via its Elasticsearch datasource
  plugin, for dashboards.

## What Must Not Be Edited Casually

- `discovery.type=single-node` is deliberate — this is not a cluster, do
  not add `cluster.initial_master_nodes`/`discovery.seed_hosts` settings
  meant for multi-node without also reconsidering data durability (single
  node = single point of failure for this store, accepted for a home-lab
  scale deployment).
- `xpack.security.http.ssl.enabled=false` is deliberate, not an oversight
  — auth is still required (`xpack.security.enabled=true`), but TLS is
  skipped because 9200 is never exposed outside `infra_seg`/the two
  additive cross-zone rules, consistent with this repo's convention of
  plain internal HTTP behind SDN isolation (Traefik terminates TLS at the
  edge for anything public; this port is never public). Do not flip this
  on without also solving self-signed cert distribution to every
  consumer (Grafana, the sync jobs, `findings-mcp`).
- `vm.max_map_count` on the `pve` host itself was checked live
  2026-08-17 and is already `262144` (Elasticsearch's documented
  minimum) — no host-level sysctl change was needed for this stack. If a
  future ES container fails to start with a "max virtual memory areas...
  too low" error, re-check this on the Proxmox host, not just inside the
  LXC (it's a host-kernel-wide setting, not per-container-namespaced).

## Playbook

`deploy-elasticsearch-stack`

`lxc_base` + `docker_base` + conditional `docker_socket_proxy` roles,
plus direct tasks that template `docker-compose.yml` inline (like
`deploy-graylog-stack.yml` does, not a static file in this stack's
directory) so `ES_JAVA_OPTS` can be computed from the container's real
memory budget at deploy time, same formula Graylog's Data Node heap
uses.

## Implementation Files

| File | Role | Status |
|------|------|--------|
| `terraform/lxc/stacks/elasticsearch-stack/stack.yaml` | Terraform-side stack definition | existing |
| `terraform/lxc/stacks/elasticsearch-stack/edge.yaml` | Traefik/Authentik route for Kibana | existing |
| `terraform/lxc/stacks/elasticsearch-stack/terragrunt.hcl` | Terragrunt entrypoint (boilerplate) | new |
| `terraform/lxc/environments/pve/elasticsearch-stack/` | Terragrunt entrypoint | new — mirrors `terraform/lxc/environments/pve/graylog-stack/`'s shape |
| `terraform/lxc/stacks/elasticsearch-stack/inventory.yml` | Generated Terraform→Ansible handoff — do not hand-edit, regenerated by `terragrunt apply` | generated |
| `terraform/lxc/ansible/playbooks/deploy-elasticsearch-stack.yml` | Stack playbook | new |

No dedicated Ansible role exists for this stack (matching `ci-runner-01`'s
and `deploy-graylog-stack.yml`'s pattern) — stack-specific logic lives
directly in the playbook. The separate `es_findings_ingest` role
(`plan.md`'s Ingestion pattern section, deployed onto `harbor-stack` and
inside `pentest_seg`, not onto this stack) is out of scope for this file.
