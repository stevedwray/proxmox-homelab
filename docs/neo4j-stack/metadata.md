# neo4j-stack metadata design

What properties the graph's nodes and edges should carry, where each one
comes from, and what is built. Companion to the graph model in `plan.md`.
Written 2026-10-31 from the real derived model and NetBox, not from the
plan's assumptions.

**Status key:** **Live** = importer produces it · **1b** = needs `flows.py` to
emit it (then a populate run) · **2/3** = needs a new source · **Open** = needs
data written by hand.

## Ground rules

- Neo4j properties are primitives or arrays of primitives only. Nested maps
  are flattened (as `provides` already is) or JSON-encoded by `_clean_props`.
- Missing is not the same as `none`. The model leaves `auth` and
  `transport_security` empty on its 50 zone-policy flows; that is *unknown*,
  and the graph says so (`auth_kind: unknown`) instead of leaving a hole a
  query can't see.
- Derived props never override a value the model supplies itself.
- Keep provenance honest: the model already marks flows with `inferred_from`
  and `needs_annotation`; those are kept as they are.
- Hand-authored overlay nodes (`:Threat`, `:Mitigation`, ...) never carry
  `:Homelab`, so a re-import cannot prune them.

## Nodes

| Node | Properties | Status |
|---|---|---|
| **Process** | name, stack, vmid, zone, deployment_tier, tags, provides[] | Live |
| | `platforms`, `technologies` (base images), container privilege counts, `docker_socket_proxy`, `host_bind_mounts`, `device_passthrough` | **1b built** (not deployed) |
| | `stack.yaml`: cores, memory, rootfs_size, backup_policy | 1b |
| | `routed`, `route_auth_modes` (from `edge.yaml`) | **1b built** (not deployed) |
| | compose: images[], digests | 2 |
| | vulnerability counts (critical/high), last scan (Harbor, Greenbone, OpenSearch; the CVE overlay deferred in `plan.md`) | 2 |
| **VirtualMachine** | name, cluster, status, vcpus, memory, tags | Live |
| | `node`, `disk`, `platform`, `observed_state` (parsed from the description's `[Status: ...]`) | Live |
| **IPAddress** | address, `scope` (private / public / loopback) | Live |
| | status, dns_name, primary flag (needs a fetch of `ipam/ip-addresses`; `dns_name` is empty in NetBox today) | 2 |
| **Service** | name, protocol, ports, description, `last_seen` (parsed from the description's `last-seen=`) | Live |
| **Zone / TrustBoundary** | name, type, enforcement, description | Live |
| | default policy and allowed zones (network intent, MikroTik) | 2 |
| **DataStore** | type, data_classification, contents, encryption_at_rest, notes | Live |
| | backup_policy | 1b |
| | retention, PII flag | Open |
| **ExternalEntity** | trust_level, description | Live |
| | kind (human / internet-service / vendor) | Open |
| **Prefix / VLAN** | prefix, status, description / vid, name, group | Live |
| | prefix to VLAN link | blocked: NetBox prefixes have no VLAN |

## Edges

**`FLOWS_TO`**: one data flow.

| Property | Meaning | Status |
|---|---|---|
| protocol, port / ports, auth, transport_security, data_classification, trust_boundary_crossing, flow_type, trigger, inferred_from, needs_annotation, notes | straight from the model | Live |
| `auth_kind` | `none` / `unknown` / `forward-auth` / `oidc` / `mtls` / `token` / `other`, normalised from the free-text `auth` | Live |
| `encrypted` | true when a transport is stated and isn't `none`; false for `none`; omitted when unknown | Live |
| `from_zone`, `to_zone` | the endpoints' SDN zones (`external` for an ExternalEntity; omitted for an Unresolved endpoint) | Live |
| `crosses_zone` | true / false when both zones are known, else omitted | Live |
| `exposure` (`internet` / `lan` / `zone-internal`) | from `edge.yaml` | 1b |
| `tls_issuer` | from `edge.yaml` (`letsencrypt` or step-ca) | 1b |
| `flow_id` | stable id, replacing the `#2` suffix workaround | 1b |
| `allowed_by` | the firewall rule that permits it | 2 |
| `confidence` (`declared` / `inferred` / `observed`), `last_observed` | needs traffic evidence; no source verified yet | 3 |

**Other relationships**

| Relationship | Added | Status |
|---|---|---|
| `RUNS_ON` | `matched_by` (`home-cluster` or `only-vm`) | Live |
| `DEPENDS_ON` (Process to Process) | from `stack.yaml depends_on`; answers "what breaks if X is down" without any flow data | **1b built** (not deployed) |
| `PROTECTED_BY` (Flow to Authentik Application) | turns `auth: forward-auth` into a concrete object with groups | 2 |

## What the real model looks like (140 flows, 2026-10-31)

| Property | Values |
|---|---|
| `auth_kind` | none 55, unknown 51, forward-auth 21, oidc 10, token 2, other 1 |
| `encrypted` | false 71, true 19, omitted 50 |
| `crosses_zone` | true 93, false 11, omitted 36 |

23 flows are **unencrypted, have no auth (or unknown), and cross a zone**.
`data_classification` is `varies` on 51 flows, which makes "secret data over
plaintext" queries unreliable; fixing that is annotation work, not importer
work.

## Example queries

```cypher
// Zone-crossing flows with no encryption and no (or unknown) auth
MATCH (a)-[f:FLOWS_TO]->(b)
WHERE f.crosses_zone = true AND f.encrypted = false AND f.auth_kind IN ['none', 'unknown']
RETURN a.key, b.key, f.from_zone, f.to_zone, f.port, f.auth_kind ORDER BY f.from_zone, f.to_zone;

// The gaps: flows the model says nothing about
MATCH (a)-[f:FLOWS_TO]->(b) WHERE f.auth_kind = 'unknown' RETURN f.from_zone, f.to_zone, count(*) ORDER BY count(*) DESC;

// Processes whose VM is on another node than the model assumes
MATCH (p:Process)-[r:RUNS_ON {matched_by: 'only-vm'}]->(v) RETURN p.name, v.name, v.node;

// Services NetBox hasn't seen recently
MATCH (s:Service) WHERE s.last_seen < '2026-10-24' RETURN s.name, s.last_seen ORDER BY s.last_seen;
```

## Where to derive each thing

NetBox has no custom fields, and structured data in descriptions is fragile
(`[Status: running]`, `last-seen=...`). Derive in `flows.py` (model) and the
importer (graph); add NetBox custom fields only for values an operator edits
by hand.

## Phasing

1. **Live:** everything marked Live above (importer only, no new sources).
2. **1b:** extend `flows.py` so the threat-model context carries the
   `stack.yaml` / `edge.yaml` fields, then run populate (or the one-section
   refresh) and extend the importer for `DEPENDS_ON` and the Process props.
3. **2:** vulnerability overlay and Authentik objects.
4. **3:** declared-versus-observed flows, only once a traffic source is
   verified (MikroTik connection logs via Graylog is the candidate; untested).
