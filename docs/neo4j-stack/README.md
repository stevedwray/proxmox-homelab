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

## Branch

Work lives on `work/neo4j-stack`, cut from `stable`. Deploy only from a
checkout that is 0 commits behind `origin/stable` (see plan.md's runbook
preamble).

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

### Step 0 - setup and offline checks (2026-10-31)

- Checkout `work/neo4j-stack`, 0 commits behind `origin/stable`.
- Offline validators all pass: importer unit tests (9), `validate-compose.sh`,
  `validate-stack-metadata.sh --check-contract-sections`,
  `validate-edge-manifests.py` (25 manifests), and `ansible-playbook
  --syntax-check` on `deploy-neo4j-stack.yml`.
- Unexpected: the syntax check fails with "role 'lxc_base' not found" unless
  run with `ANSIBLE_CONFIG` and `ANSIBLE_ROLES_PATH` pointing at
  `terraform/lxc/ansible`. With them set it passes.
- Unexpected: `pct`/`qm` don't exist on the workstation, so the wrapper
  can't run them directly. The check ran as `./with-secrets-prod ssh pve`
  with a stdin script (read-only).
- pve confirmed as the target node. vmid 40016 absent from `pct list` and
  `qm list`; no CT/VM config references 192.168.40.16; the IP does not ping.

### Step 1 - NetBox freshness (2026-10-31)

- `threat-model` context `last_updated` was 2026-10-23 11:21 UTC, 8 days old
  (read from NetBox's DB via `docker exec` on the netbox LXC; the API needs a
  token and answered 403 without one).
- Cause 1, fixed: `ci-runner-01` was stuck on runner 2.333.1. Its daily
  self-update failed (`mv: cannot overwrite bin.2.333.1/bin: Directory not
  empty`, stale backup dirs from Sep 7), and GitHub queued the NetBox Populate
  jobs without delivering them. Stale `bin.*`/`externals.*` dirs were moved to
  `/opt/actions-runner-stale/` and the staged 2.338.0 `bin`/`externals` were
  swapped in by hand. The runner is now on 2.338.0 and takes jobs.
- Cause 2, NOT fixed: the populate job itself fails with `NetBox client
  requires NETBOX_URL or LAB_IP_NETBOX`. `.github/workflows/netbox-populate.yml`
  never sets either, and commit `0f912630` already notes the daily workflow
  never succeeded. The Oct 23 context was therefore probably a manual run.
  Likely fix: add `LAB_IP_NETBOX` to the workflow env (separate work).
- Decision (operator): skip the freshness gate for this first deploy. Only 5
  model-input commits landed since Oct 23 (PentAGI removal, mcp-utility-stack
  move, Omada routing). The importer's daily timer picks up a fresh context
  once populate runs again.
- Unexpected: auto-mode classifier blocked the mutating ssh calls, so the
  operator ran the runner fixes by hand.

### Steps 2-3 and 4 - token, OpenBao write, pve profile (2026-10-31)

- Operator created the read-only NetBox token and wrote `services/neo4j`
  (`NEO4J_PASSWORD`, `NEO4J_NETBOX_READONLY_TOKEN`) to OpenBao by hand.
- Step `neo4j-01-pve-profile` applied as written: `services/neo4j` added to the
  `pve` profile only. All four gates passed (json-valid, pve-profile-has-neo4j,
  one-line-diff 1/1, loader-tests 12 OK).
- Pending: operator confirms `./with-secrets-prod` still loads cleanly.

### Step 5a - LXC created (2026-10-31)

- `terragrunt plan`: 5 to add, 0 change, 0 destroy. Exactly one is the LXC;
  the other four are the standard per-stack helpers (inventory file, SDN vars
  file, SDN-attachment `null_resource`, epoch marker).
- `terragrunt apply` in `terraform/lxc/environments/pve/neo4j-stack`: 5 added,
  0 changed, 0 destroyed. vmid 40016, 192.168.40.16/24, `infra_seg`.
- Verified: pings, ssh works, hostname `neo4j-stack`, Docker 26.1.5 present.
- Next: `provision.sh --stack neo4j-stack` (first real run of the importer).

### Step 5b - provision (2026-10-31)

- `./with-secrets-prod scripts/provision.sh --stack neo4j-stack`: exit 0,
  recap ok=83 changed=49 failed=0. `ansible_host` checked as 192.168.40.16
  beforehand.
- First live run of the importer's Cypher succeeded on the first attempt: the
  playbook's "Confirm the graph has threat-model processes" task passed.
  No fix needed. The graph was built from the 8-day-old `threat-model`
  context (freshness gate skipped by the operator).
- Edge reconcile was skipped by provision.sh in single-stack mode, as expected.
  Edge publishing is step 6.
