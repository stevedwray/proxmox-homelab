# neo4j-stack

Status: **deployed to `pve` 2026-10-31** (LXC 40016, `192.168.40.16`, edge
routes live, importer timer armed for 04:30 daily). Browser connects through
Traefik. One known data gap in the imported graph (`ON_VLAN`, see "Known gaps"
below). Start with `plan.md`; the property design is in `metadata.md`.

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

- **`RUNS_ON` initially matched nothing (importer bug, fixed 2026-10-31).**
  NetBox VM names are `<stack>@<node>` but Process names are bare, so the
  join was empty. The importer now strips the node suffix, prefers the VM in
  `pve-cluster` (override with `NEO4J_HOME_CLUSTER`), accepts a stack's only
  VM if it lives on another node, and adds no edge when several non-home VMs
  match. Live result: 19 of 21 Processes linked. The other two are real drift:
  `dns-stack` (destroyed on pve 2026-09-08) and `dhcp-test-client-01` (no
  NetBox VM). `mcp-utility-stack` links to its `@pve-tiny` VM because NetBox
  still says so (stale since the Oct 23 populate; it moved back to pve).
- **Full `populate.py` fails on the evacuation-soak duplicates (not neo4j's,
  found 2026-10-31).** Five guests exist twice, live on `pve-tiny` and stopped
  on `pve` (`cse-controller`, `cse-code-eval`, `pentest-runner`,
  `technitium-tiny-stack`, `cse-panel-stack`). Populate keys IPs by address
  only, so it tries to move each shared IP (`192.168.100.70/.71/.72`,
  `192.168.20.17/.30`) from the live pve-tiny VM to the stopped pve copy.
  NetBox refuses the first one (it is the live VM's primary IP); the dry run
  cannot see that. It needs a guard in `populate.py`: don't take over an
  address assigned to a VM on another node. Until then use the one-section
  refresh below. The daily CI workflow would hit the same wall.
- **The daily NetBox Populate workflow never ran successfully.** It crashed on
  `NETBOX_URL or LAB_IP_NETBOX` because `populate.py` runs on the runner with
  none of the `.env` config the old container wrapper passed through. Fix
  committed on `fix/netbox-populate-ci-env` (`3863bde9`, sources the tracked
  `.env` and `.env.pve`); not pushed, and the OpenBao JWT role only accepts
  the `main` ref, so CI sees it only after it reaches `main`. The runner also
  cannot reach MikroTik (443), so CI runs skip router data (soft warning, no
  deletes).
- **`ON_VLAN` is never created (NetBox data gap).** The importer is correct,
  but NetBox's prefixes have no VLAN assigned (13 VLANs and 10 prefixes exist,
  unlinked).

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

### Step 6a - edge render, Authentik reconcile (2026-10-31)

- `render-edge-traefik.py --json` needs `.env` sourced (without it,
  `${LAB_DOMAIN}` stays unresolved and it reports `failed`). With it: 25
  stacks, 0 warnings, output goes to the ignored `.generated/` dir, nothing to
  commit.
- `reconcile-edge.py` dry-run: planned exactly 2 creates (app + provider);
  top-level `failed` was only `EGR211` drift for those two missing objects.
- `--apply`: passed, 3 writes (create app, create provider, update the shared
  Embedded Outpost to link the new provider; the dry-run had shown the outpost
  as a no-op). Post-apply discovery: both routes `matching`, 0 issues. No DNS
  or Traefik writes.
- Unexpected, not neo4j's: the dry-run's Technitium diff dropped `smokeping`
  from a local generated file. Cause: `smokeping`/`icinga` DNS and Traefik
  were applied from the unmerged, never-pushed
  `feat/argon-icinga-observability`. The Technitium and proxy playbooks do not
  prune records/files they don't generate (zone is Primary), so live
  `smokeping`/`icinga` should survive; baselines of live DNS and the proxy's
  `dynamic/` hashes were taken to prove it after steps 6b/6c. The Argon work
  was merged with `stable` on `task/argon-merge-stable` and opened as PR #547.

### Step 6b - proxy-stack republish (2026-10-31)

- `provision.sh --stack proxy-stack`: exit 0, ok=111 changed=4 failed=0, its
  own smoke test passed. `ansible_host` checked as 192.168.30.10.
- Baseline vs after on `/opt/proxy-stack/dynamic/*.yml` (sha256): the only
  difference is the new `neo4j-stack.yml`. All 27 other files, including the
  Argon-applied `smokeping.yml`, are byte-identical.
- Unauthenticated probes straight to Traefik: `netbox.` and `smokeping.`
  302 to Authentik, `dashboards.` 302 to its OIDC login, `neo4j.` 302 to
  Authentik (new client), `neo4j-bolt.` 200. These show routing, not a
  completed login; the interactive login check is the operator's.

### Step 6c - technitium-stack republish (2026-10-31)

- `provision.sh --stack technitium-stack`: exit 0, ok=289 changed=3 failed=0,
  smoke test passed. `ansible_host` checked as 192.168.20.15.
- DNS baseline (56 names resolved against 192.168.20.15) vs after: the only
  differences are `neo4j` and `neo4j-bolt`, both now 192.168.30.10.
  `smokeping`, `icinga` and every other name unchanged. The secondary
  (192.168.20.17) already answers the new names.
- Re-check through real DNS, system trust store: `netbox.` and `smokeping.`
  302 to Authentik, `dashboards.` 302 to its OIDC login, `neo4j.` 302 to
  Authentik, `neo4j-bolt.` 200, all with valid TLS. The edge certs are Let's
  Encrypt, so the browser does not need the homelab root CA (an earlier probe
  with `--cacert certs/homelab-root.crt` failed only because it replaced the
  system trust store).
- Operator reply "proceed" after the step 6b message was taken as acceptance
  of the netbox/dashboards check and approval of this step.

### Step 7 - browser check (2026-10-31, operator)

- Worked: `https://neo4j.lab.gibbsgreatly.xyz` through Authentik, then
  Browser connected to `neo4j+s://neo4j-bolt.lab.gibbsgreatly.xyz:443` as
  `neo4j` (server Neo4j 5.26.31). Bolt over websocket through Traefik works;
  the `bolt://192.168.40.16:7687` fallback was not needed.

### Step 8 - final counts (2026-10-31, run over ssh from stdin)

| Node kind | Count |
|---|---|
| DataStore | 8 |
| ExternalEntity | 7 |
| IPAddress | 44 |
| Prefix | 10 |
| Process | 21 |
| Service | 76 |
| TrustBoundary | 7 |
| Unresolved | 12 |
| VLAN | 13 |
| VirtualMachine | 49 |
| Zone | 25 |

Relationships: EXPOSES 76, FLOWS_TO 131, HAS_IP 44, HOSTED_ON 8, IN_PREFIX 29,
IN_ZONE 21. No `RUNS_ON` or `ON_VLAN` (see Known gaps). Cypher errors: none.
Importer timer `neo4j-import.timer` next fires 2026-11-01 04:31 NZDT.

### Step 8b - RUNS_ON fix redeployed (2026-10-31)

- Importer fix `b26a313e` (15 unit tests; 4 of the 6 new ones fail on the old
  code). `provision.sh --stack neo4j-stack`: exit 0, ok=71 changed=4 failed=0.
  `ansible_host` 192.168.40.16.
- After: RUNS_ON 19, every other node and relationship count unchanged
  (FLOWS_TO 131, VirtualMachine 49, Process 21). No Process has more than one
  RUNS_ON. Unlinked: `dns-stack`, `dhcp-test-client-01`.
- Process note: the first verification call failed because `TASK_APPROVAL`
  was not set in that shell; it ran no remote command and was re-run.

### After the PR opened (2026-10-31)

- **Runner repair (step 1 side quest, no repo change).** Covered in the
  step 1 entry above; `ci-runner-01` is on 2.338.0 and takes jobs.
- **Full populate apply, failed partway.** Dry run (`--plan`): 5 creates, 112
  updates, 0 deletes, 0 stale. The apply made the 5 creates (the
  `neo4j-stack@pve` VM, `eth0`, `192.168.40.16/24`, tags `neo4j` and
  `threat-model`) and 20 benign updates, then NetBox refused
  `PATCH /ipam/ip-addresses/80/` (see Known gaps). No IP was reassigned. The
  step is idempotent, so nothing needed undoing.
- **Threat-model refresh, one section only.** A throwaway script ran
  `populate_threat_model()` alone (dry run first), writing only the `data`
  field of config context `threat-model` (id 1): 21 processes, 138 flows,
  `last_updated` 2026-10-31 03:45 UTC, verified in NetBox's DB. The model has
  no `neo4j-stack` process until this branch merges, because it derives from
  `stable`'s manifests.
- **Importer run on demand** (`systemctl start neo4j-import.service`):
  success. FLOWS_TO 131 to 138, VirtualMachine 49 to 50, IPAddress 44 to 45,
  Unresolved 12 to 14, Zone 25 to 26, RUNS_ON unchanged at 19.
- **Metadata design and phase 1** (`metadata.md`): the importer now derives
  `auth_kind`, `encrypted`, `from_zone`, `to_zone`, `crosses_zone` on flows,
  `node`/`disk`/`platform`/`observed_state` on VMs, `scope` on IPs,
  `last_seen` on services and `matched_by` on `RUNS_ON`. 22 unit tests. Not
  yet deployed when this entry was written; the deploy entry follows below.

### Metadata phase 1 deployed (2026-10-31)

- `provision.sh --stack neo4j-stack`: exit 0, ok=71 changed=2 failed=0
  (`ansible_host` 192.168.40.16). Totals unchanged (FLOWS_TO 138,
  VirtualMachine 50).
- Live check: `auth_kind` none 54, unknown 51, forward-auth 20, oidc 10,
  token 2, other 1; `encrypted` true 19, false 69, omitted 50; 23 flows cross
  a zone unencrypted with no or unknown auth (matches the offline count on the
  derived model). VM `observed_state` on 49 of 50 (the new `neo4j-stack@pve`
  has no status text yet), `node`/`platform` on 50, service `last_seen` on
  76 of 76, IP `scope` private on all 45, `RUNS_ON` `matched_by`
  home-cluster 16, only-vm 3.
- The model differs by 2 flows between this checkout (140, includes the
  neo4j routes) and what the graph holds (138, from `stable`'s manifests); it
  closes when this branch merges and populate runs.
