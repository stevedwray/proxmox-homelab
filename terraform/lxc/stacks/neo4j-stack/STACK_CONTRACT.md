# neo4j-stack — Stack Contract

## Purpose

Neo4j Community graph database holding the lab's architecture as a graph for
threat modeling. A daily importer rebuilds it from NetBox. The source is the
`threat-model` config context (trust boundaries, external entities,
processes, data stores and data flows, derived by netbox-populate's
`flows.py` from `stack.yaml`, `edge.yaml` and network intent), plus NetBox's
VM, primary-IP, service, prefix and VLAN inventory. Operators query it with
Cypher in Neo4j Browser and can layer hand-authored threat/mitigation nodes
on top. See `docs/neo4j-stack/` for the graph model and example queries.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `infra_seg` (VLAN 40) |
| IP           | `192.168.40.16/24` |
| Gateway      | `192.168.40.1` |
| VMID         | `40016` |

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `NEO4J_PASSWORD` | OpenBao `kv/services/neo4j` | Password for the built-in `neo4j` user. Only applied on first start (empty `/data`) |
| `NEO4J_NETBOX_READONLY_TOKEN` | OpenBao `kv/services/neo4j` | Read-only NetBox API token the importer uses. Not netbox-populate's write token |
| `LAB_IP_NEO4J` | `.env` | This stack's own IP, for `edge.yaml` |
| `LAB_IP_NETBOX` | `.env` | Already exists. Importer's NetBox API base (`http://<ip>:8080`) |
| `LAB_DOMAIN`, `LAB_FQDN_HARBOR`, `HARBOR_ADMIN_PASSWORD`, `LAB_IP_TECHNITIUM` | `.env` / OpenBao | Platform defaults, same as opensearch-stack |

## Provides

| Service | Port | Protocol | Notes |
|---------|------|----------|-------|
| `neo4j-browser-http` | `7474` | `tcp` | Browser UI + HTTP Cypher API. Published as `neo4j.${LAB_DOMAIN}` behind Authentik forwardAuth |
| `neo4j-bolt` | `7687` | `tcp` | Bolt (incl. websocket). Published as `neo4j-bolt.${LAB_DOMAIN}`, `auth.mode: none`, with Neo4j's password as the boundary |

## Dependencies

| Stack | Why |
|-------|-----|
| `harbor-stack` | Neo4j image pulled through Harbor's `dockerhub` proxy-cache |
| `apt-cacher-stack` | Package installs during `lxc_base`/`docker_base` |
| `netbox-stack` | The importer's only data source (read-only API) |
| `authentik-stack` | forwardAuth on the Browser route |

## Persistent State

| Path | Storage | Contents |
|------|---------|----------|
| `neo4j-data` volume (`/data`) | docker_storage (20 GiB) | Graph store. The `:Homelab` part is regenerable from NetBox; hand-authored nodes are not |
| `neo4j-logs` volume (`/logs`) | docker_storage | Neo4j logs |
| `/etc/neo4j-import/env` | rootfs | Importer credentials (0600) |
| `:Attack*`, `:Sensor`, `:Control` nodes | `neo4j-data` volume | MITRE ATT&CK v20 and the per-process threat-informed-defence overlay. Regenerable: the dataset is pinned in git and the overlay comes from `docs/threat-model/attack/*.yaml` |

## What May Depend On This Stack

Nothing depends on this stack. It's a leaf read model.

## What Must Not Be Edited Casually

- `:Sensor` and `:Control` nodes and the `ASSESSED_AGAINST`, `MONITORS`, `PROTECTS`, `IMPLEMENTS` and `PROVIDES` relationships belong to the
  ATT&CK mapping. A re-load prunes any that the mapping file no longer says, so change `docs/threat-model/attack/<process>.yaml`, not the graph.
- `NEO4J_AUTH` is only honored when `/data` is empty. Changing
  `NEO4J_PASSWORD` in OpenBao after first deploy breaks the importer and the
  playbook's Cypher check until the operator also runs
  `ALTER CURRENT USER SET PASSWORD FROM '<old>' TO '<new>'` in Browser.
- The importer deletes every `:Homelab` node and imported relationship that a
  run didn't produce. Put hand-authored threat-modeling nodes under their own
  labels (`:Threat`, `:Mitigation`, ...) without `:Homelab`, or the next
  import removes them.
- `NEO4J_server_bolt_advertised__address` must match the `neo4j-bolt` route
  host in `edge.yaml`, or Browser tries to reach Bolt at an unroutable address.

## Playbook

`deploy-neo4j-stack`. It uses `lxc_base`, `docker_base`, the stack's
`docker-compose.yml`, and the importer's systemd service and timer
(`neo4j-import.timer`, daily 04:30, after netbox-populate).

## Implementation Files

- `terraform/lxc/stacks/neo4j-stack/stack.yaml`
- `terraform/lxc/stacks/neo4j-stack/docker-compose.yml`
- `terraform/lxc/stacks/neo4j-stack/edge.yaml`
- `terraform/lxc/stacks/neo4j-stack/terragrunt.hcl`
- `terraform/lxc/environments/pve/neo4j-stack/terragrunt.hcl`
- `terraform/lxc/stacks/neo4j-stack/importer/neo4j_import.py` (+ `test_neo4j_import.py`)
- `terraform/lxc/ansible/playbooks/deploy-neo4j-stack.yml`
