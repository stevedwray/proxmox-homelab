# neo4j-stack

Status: **repo files authored and validated offline. Not deployed to `pve`
yet.** Start with `plan.md`. Everything that's left is operator work in
production: OpenBao writes, a NetBox token, `terragrunt apply`,
`provision.sh`, and edge publishing.

## What this is

A Neo4j Community LXC (`192.168.40.16`, vmid `40016`, `infra_seg`) that holds
the lab's architecture as a graph for threat modeling. A daily importer
rebuilds it from NetBox: the auto-derived `threat-model` config context
(trust boundaries, external entities, processes, data stores, data flows)
joined to NetBox's VM, IP, service, prefix and VLAN inventory. Operators
query it with Cypher in Neo4j Browser at `https://neo4j.lab.gibbsgreatly.xyz`
and can layer their own threat/mitigation nodes on top.

The pipeline is IaC → NetBox → Neo4j:

```
stack.yaml / edge.yaml / network intent
      │  netbox-populate (flows.py), daily
      ▼
NetBox config context 'threat-model'  +  VMs / IPs / services / prefixes / VLANs
      │  neo4j-import.timer (neo4j_import.py), daily 04:30, read-only token
      ▼
Neo4j (:Homelab graph)  ◀── hand-authored :Threat / :Mitigation nodes (never pruned)
```

## Decisions (operator, 2026-10-30)

- **Graph scope:** the DFD (threat-model context) plus NetBox inventory.
  CVE findings from OpenSearch are out of scope for the first pass.
- **Edition:** Neo4j Community `5.26.31-community` (5.26 LTS line). It has no
  SSO, so the Browser route sits behind Authentik forwardAuth and the Neo4j
  login is a second factor.
- **Placement:** `pve`, `infra_seg`, `192.168.40.16`, vmid `40016`, next to
  NetBox. The importer's NetBox read stays inside the zone, so it needs no
  MikroTik rule.
- **Importer:** a systemd timer on neo4j-stack itself, reading NetBox with a
  dedicated read-only token. It does not extend netbox-populate.

## Fixed along the way

- `flows.py` had been crashing on `pve`'s network intent since the greenbone
  scan-reach policy (`to:` is a list) landed around 2026-08-16.
  `populate_threat_model` swallows the exception, so **NetBox's
  `threat-model` context has silently stopped updating since then.** Fixed
  in this branch, with a unit test. netbox-stack has to be redeployed for the
  fix to reach the populate timer (runbook step 1).

## Known gaps the graph will show (not fixed here)

- `flows.py` reuses one flow id for every Traefik route to a multi-route
  stack (e.g. `df-traefik-to-torrent-stack-lab` ×6). The importer suffixes
  repeats (`#2`, `#3`...) so no route is lost. The real fix belongs in
  `flows.py`, where it needs care with `annotations.yaml` keys.
- 12 flow endpoints don't resolve to any process `flows.py` defines
  (`p-traefik`, `p-ci-runner`, `p-greenbone`, `p-ai-services`, ...). They show
  up as `:Unresolved` nodes, which makes them a ready-made worklist for
  improving the derived model.

## Hand-back log

_No steps executed yet._
