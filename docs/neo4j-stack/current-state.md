# neo4j-stack: current state

**Checkpoint 2026-10-31.** Verified the same day against the repo, GitHub and, read-only, production. The history of
how it got here is the hand-back log in [README.md](README.md); the plan is in [plan.md](plan.md#roadmap).

## Purpose and direction

Neo4j holds the lab's architecture as a graph (NetBox inventory plus the derived threat model) so it can support
**threat-informed defence against MITRE ATT&CK**. It is **not an alert source**: alerting built on it was added and
reverted on 2026-10-31 at the operator's direction. We are in the **setup phase**: the foundation is built and proven
on one process; working through ATT&CK (reviewing assessments, acting on gaps) has not started.

## Live in production

| What | State |
|---|---|
| LXC | `neo4j-stack`, vmid 40016, `192.168.40.16`, `infra_seg`, Neo4j Community 5.26.31 |
| Access | `https://neo4j.lab.gibbsgreatly.xyz` (Authentik forward-auth), Bolt at `neo4j+s://neo4j-bolt.lab.gibbsgreatly.xyz:443` (Neo4j password is the boundary). Both proven by the operator |
| Importer | `neo4j-import.timer`, daily about 04:30; rebuilds `:Homelab` from NetBox in one transaction. **The deployed importer predates `DEPENDS_ON`** |
| Homelab graph | 40 processes, 162 flows, 50 VMs; 284 nodes and 395 relationships in all. `RUNS_ON` links 34 of 40 processes to their VM |
| ATT&CK layer | Enterprise v20.0: 3,353 `:Attack*`, `:Sensor`, `:Control` nodes and 50 overlay relationships (`authentik-stack`). Survives the importer; nothing in it carries `:Homelab` |
| NetBox | `threat-model` config context refreshed 2026-10-31 04:09 UTC from PR #549's model (40 processes, 162 flows) |

## Built and in git, **not live**

- Per-process asset facts (`platforms`, `technologies`, container privilege counts, `routed`, `route_auth_modes`,
  socket-proxy and host-access facts) and `DEPENDS_ON` edges: PR #553 and the importer change in #552. In production no
  Process has `platforms` and there are 0 `DEPENDS_ON` edges. Taking effect needs the threat-model refresh and an
  importer run.
- The runner self-update alert and the `deploy-ci-runner.yml` version-pin fix (#551); the populate fixes (#550).

## Pull requests and merge order

| PR | What | Base | Depends on |
|---|---|---|---|
| #547 | Argon/Icinga/SmokePing work, live in prod but unmerged | stable | none; confirm prod matches its head first |
| #549 | Traceable threat model: 40 processes, no dangling ids, Authentik consumers as edges | stable | none |
| #553 | Asset facts on every process | #549 | #549 (retarget to stable when it merges) |
| #550 | Daily populate: CI config and shared-address guard | stable | none; merge #549 first so a populate run does not revert the model |
| #551 | Runner self-update alert and the `runner_version` pin | stable | none |
| #548 | neo4j-stack itself (draft) | stable | none |
| #552 | ATT&CK layer, `DEPENDS_ON`, matrix view, viewer | #548 | #548 (retarget to stable when it merges) |

Suggested order: #547, #549, #553, #550, #551, #548, #552. After each merge the next branch needs `stable` merged in and
its validators re-run; stacked PRs need retargeting.

## Where production is ahead of git, or fragile

- **NetBox `threat-model` context** comes from #549's branch. A populate or refresh run from a `stable` checkout would
  put the old 21-process model back. Nothing runs that automatically, because the daily CI populate has never worked.
- **neo4j-stack** was deployed from unmerged branches; it exists only on them.
- **`ci-runner-01`** was repaired by hand (stale `bin.*`/`externals.*` moved to `/opt/actions-runner-stale/`, 2.338.0
  swapped in). `stable`'s `deploy-ci-runner.yml` still pins 2.333.1, so **re-provisioning it before #551 merges would
  silently downgrade the runner** and bring the stuck state back.
- **Argon** (`smokeping` DNS and Traefik, `icinga` DNS) is live from a branch that was never merged (#547).
- **A full `populate.py` run is not safe yet:** it fails on five guests that exist on both pve and pve-tiny (#550), and
  from `stable` it would revert the threat model.

## Decisions on record

| Date | Decision |
|---|---|
| 2026-10-30 | Graph scope is the DFD plus NetBox inventory (CVEs deferred); Neo4j Community 5.26 LTS; placed on pve `infra_seg`; importer is a timer on the stack itself, read-only NetBox token |
| 2026-10-31 | The 8-day-old threat model was accepted for the first deploy (freshness gate skipped) |
| 2026-10-31 | Neo4j and the threat model are for threat-informed defence, **not alerting**; the alerting added was reverted |
| 2026-10-31 | ATT&CK scope: Enterprise plus Containers, detection coverage in scope, Authentik as the pilot |
| 2026-10-31 | The current phase is setup, not analysis; the next setup item was left to my judgement (the matrix viewer) |

## Known gaps

- **Model quality:** 51 of 162 flows have unknown auth, 18 need annotation, and the 9 Authentik `auth-dependency` flows
  need their endpoint and TLS status; `data_classification` is `varies` on many flows; downstream dependencies (a
  service's own storage) are not modelled.
- **Inventory:** `ON_VLAN` is never created (NetBox prefixes have no VLAN). Six processes have no `RUNS_ON`:
  `comfyui-stack` and `llm-gpu-stack` (Framework host, not a NetBox VM), `dns-stack` (destroyed), `dhcp-test-client-01`,
  `harness-target-pve`, `tpot`.
- **Pipeline:** the daily NetBox Populate workflow has never succeeded (#550 fixes it, provable only once it reaches
  `main`); the runner cannot reach MikroTik on 443, so CI runs skip router data.
- **ATT&CK:** one process mapped, assessments unreviewed, `assumed` telemetry never seen in events, and no detection-rule
  layer (telemetry coverage is not detection).
- **Backups:** the Homelab graph and the ATT&CK layer are regenerable from git and NetBox; hand-authored
  `:Threat`/`:Mitigation` nodes would not be, and there is no `neo4j-admin database dump` yet.

## How to

**See the data-flow graph** (read-only; the credentials stay on the host):

```bash
./with-secrets-prod ssh root@192.168.40.16 'set -a; . /etc/neo4j-import/env; python3 -' \
    < terraform/lxc/stacks/neo4j-stack/viewer/export_graph.py > graph-export.json
python3 terraform/lxc/stacks/neo4j-stack/viewer/build_graph_view.py graph-export.json graph-view.html
```

Trace a request, filter risky flows, hover for detail. `export_from_model.py` previews a checkout's model without touching
NetBox or Neo4j.

**See the ATT&CK matrix**: `build_matrix_view.py`, see [attack.md](attack.md#seeing-it). Offline, no Neo4j.

**Refresh only the NetBox threat-model context** (a production write, so it needs the usual preflight and approval; run
it from a checkout whose `flows.py` is the model you intend; dry run first, then `--apply`):

```python
import sys; sys.path.insert(0, "terraform/lxc/stacks/netbox-stack/integrations")
import populate
nb = populate.NetBoxClient(dry_run="--apply" not in sys.argv)
site = nb.get("/dcim/sites/", name="Homelab")["results"][0]
populate.populate_threat_model(nb, site, populate._managed_tag_refs(), env="pve")
```

run as `./with-secrets-prod python3 refresh.py [--apply]`, then `systemctl start neo4j-import.service` on the stack to
rebuild the graph. Verify `last_updated` in NetBox before and the counts in Neo4j after.

**Add an ATT&CK mapping for another process**: [attack.md](attack.md#adding-a-process).

## Housekeeping

Scratch worktrees from this work sit under the session scratchpad (one per open branch) and are safe to delete once the
branches merge. The graph-view builder now lives in `terraform/lxc/stacks/neo4j-stack/viewer/`; its output goes to the
git-ignored `docs/neo4j-stack/artifacts/`.
