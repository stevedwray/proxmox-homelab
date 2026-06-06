# NetBox Population And Reconciliation Plan

## Purpose

This document turns the current NetBox notes into an execution plan for two
separate goals:

1. populate NetBox from the homelab sources of truth that already exist in this
   repo and infrastructure
2. keep that data current without depending on manual UI entry after rebuilds
   or normal day-2 changes

It is intentionally grounded in the code that already exists under
`terraform/lxc/stacks/netbox-stack/integrations/`, the current stack contract,
and the current segmented network model under `terraform/lxc/network/pve.yaml`.

For the short resume point to use in a fresh session, see
`docs/netbox-stack/current-state.md`.

## Implemented Operating Model

As of 2026-06-01, the NetBox refresh job is no longer intended to run as a
timer inside the NetBox LXC.

Current shape:

- the scheduled runner is a dedicated Docker container launched by
  `.github/workflows/netbox-populate.yml`
- the current implementation still uses direct SSH to each guest LXC for some
  runtime inspection, but this is now considered an interim mechanism rather
  than the preferred long-term service discovery path
- the preferred long-term runtime inspection path is read-only Docker API
  access via a tightly scoped `docker-socket-proxy` on Docker hosts/LXCs
- MikroTik discovery prefers `MIKROTIK_READONLY_USER` and
  `MIKROTIK_READONLY_PASSWORD`, with the older names still supported as
  fallbacks
- infrastructure service discovery is intended to come from observed
  Proxmox/MikroTik/LXC/Docker runtime state; Portainer is reserved for later
  application stacks once those stacks are actually managed there
- the NetBox LXC remains focused on NetBox itself; the population job and its
  source-system credentials live outside that container

This is the preferred operating model for day-2 refreshes and daily drift
correction.

## Current Pause State

As of 2026-06-02, the work is paused with the following status:

- NetBox deployment and the external populate workflow are in materially better
  shape than at the start of this plan.
- The preferred NetBox writer token path now exists and production wrapper
  validation has confirmed `with-secrets-prod` exposes `NETBOX_API_TOKEN`.
- Proxmox discovery credential naming has been narrowed successfully to the
  read-only-first path, with compatibility fallbacks still retained.
- Portainer is now treated as optional for infrastructure discovery, and a
  separate live Portainer/Authentiik OAuth regression was repaired outside the
  main NetBox track.
- The MikroTik runtime path is now effectively validated:
  - repo code and templates prefer `MIKROTIK_READONLY_USER` /
    `MIKROTIK_READONLY_PASSWORD`
  - the supported `with-secrets` runtime now exposes those names
  - direct live validation against RouterOS REST succeeded for the read-only
    pair
  - `populate.py --plan` now completes successfully with MikroTik discovery in
    the loop
- Docker/runtime service scraping through `docker-socket-proxy` is parked:
  - `DOCKER_SOCKET_PROXY_URL_TEMPLATE` is now correctly exposed by
    `with-secrets-prod`
  - probes to the expected per-guest endpoints return connection refused
  - no repo-supported provisioning path currently deploys the proxy listeners
    as part of the Docker-host LXC build
  - adding those listeners belongs in a broader container-build/provisioning
    refactor, not in the current NetBox closeout loop

Practical meaning:

- the remaining work is no longer about NetBox or MikroTik credentials
- the preferred Docker scraping path is designed and configured but not
  deployable end-to-end until the Docker-host LXC build path grows managed
  socket-proxy support
- the NetBox plan should now move on to idempotency and drift proof for the
  working source systems instead of continuing proxy endpoint investigation

## Docker Runtime Follow-Up State

As of 2026-06-05, the Docker runtime path has moved forward beyond the earlier
pause state:

- a managed read-only `docker-socket-proxy` path now exists
- the proxy was proven on a disposable `pve-test` Docker LXC
- a live canary was completed on `monitoring-stack`
- NetBox successfully ingested socket-proxy-derived runtime services tagged
  with `runtime-source-socket-proxy`

This means the Docker socket proxy methodology is functionally proven.

- Portainer socket-proxy canary: accepted closed on 2026-06-06.

Important deployment boundary:

- this proof does not mean socket proxy is enabled across production
  infrastructure containers
- the managed role exists and the Docker stack playbooks are wired for opt-in
  deployment
- normal platform stack metadata currently keeps
  `enable_docker_socket_proxy: false`
- the disposable `docker-socket-proxy-test` playbook is the only repo-declared
  deployment path that enables the proxy by default
- treat live production socket-proxy state as unknown until verified directly

For the best short resume path after this proof work, see
`docs/netbox-stack/current-state.md`.

See also: `docs/netbox-stack/portainer-socket-proxy-canary.md` for the
Portainer socket-proxy canary runbook and operator steps.

## Open Design Note: Discovery Coverage

One design question remains on the NetBox side.

The current standard populate flow expects to discover candidate guests from
live sources such as Proxmox before probing socket-proxy endpoints. During the
monitoring canary, the `pve-test` discovery context did not naturally return
the monitoring VM, even though the proxy endpoint itself was reachable and the
runtime inspection worked.

The current code contains a narrow augmentation in `populate.py` to bridge that
gap by mapping declared stack IPs to existing NetBox VMs when
`DOCKER_SOCKET_PROXY_URL_TEMPLATE` is set.

That works, but it is not yet the final architectural answer. The remaining
decision is whether to:

- keep the current augmentation
- replace it with a cleaner explicit target-selection mechanism
- or repair discovery coverage so the augmentation is unnecessary

The next design pass must keep two questions separate:

- which Docker hosts are intended NetBox runtime-discovery targets
- which of those hosts actually have a managed, reachable socket-proxy listener

## Requirement: Support Non-Proxmox Docker Hosts

Future NetBox runtime discovery must not assume that every Docker host will be
managed by Proxmox.

Most inspectable Docker LXCs/VMs will probably come from Proxmox discovery, but
some Docker hosts will exist outside Proxmox. The NetBox population process
therefore needs an explicit way to learn about additional inspectable hosts
that should be probed through `docker-socket-proxy`.

That explicit host-targeting mechanism should be:

- deliberate and visible
- bounded to intended hosts only
- compatible with inspection-derived runtime data
- not dependent on Portainer as a workaround

This should be treated as a NetBox runtime-discovery design task, not as part
of Portainer migration work.

### Declared socket-proxy probe targets

Stacks may optionally declare explicit Docker host probe candidates using the
`docker_socket_proxy_targets` metadata key in their `stack.yaml`. This can be
either a single string or a list of addresses (optionally using `${TOKEN}`
env-style placeholders). When `DOCKER_SOCKET_PROXY_URL_TEMPLATE` (or
`DOCKER_SOCKET_PROXY_URL`) is set, the populate augmentation will resolve
those candidates and attempt to map them to existing NetBox VM/interface
records by IP so runtime inspection can attach services to the existing
inventory object. Important: this augmentation will not create new NetBox VMs
— the declared address must already be present in NetBox for services to be
attached.

Example `stack.yaml` snippet:

```yaml
docker_socket_proxy_targets:
  - "${MONITORING_VM_IP}"
  - "10.57.99.10"
```

## Closeout Summary (Session 27)

- Date: 2026-06-03
- Session: `Session 27 - NetBox Stack Closeout`
- Step 7: accepted.
- `pve` reconciliation: applied and final plan proof passed (no remaining high-risk churn).
- `pve-test`: node is online but discovery reports 0 LXCs and 0 QEMU VMs (empty by design or not yet provisioned).
- MikroTik: single shared router is present and working as expected.
- Docker runtime scraping via `docker-socket-proxy`: deliberately deferred until Docker-host LXC provisioning/refactor is implemented.
- No SSH workaround was used during reconciliation; runtime SSH probes emitted warnings but were not acted on.
- No further live NetBox apply is required in this closeout session.

See `docs/netbox-stack/current-state.md` for the current durable resume point.

## Review Summary

The current repo is in a better position on NetBox deployment than on NetBox
data management.

Confirmed strengths:

- NetBox deployment is real, current, and idempotent enough to bootstrap the
  service itself.
- Discovery code already exists for Proxmox, MikroTik, and runtime service
  inspection inside guests/LXCs.
- Population code already exists for the main NetBox domains we care about:
  DCIM, virtualization, IPAM, services, and tags.
- Focused tests already exist around discovery behavior and NetBox API path
  contracts.

Main weaknesses that block a "keep it up to date" claim today:

- `docs/netbox-stack/README.md` was mostly a gap analysis, not an operator plan.
- `terraform/lxc/stacks/netbox-stack/README.md` is stale and still describes a
  Portainer-managed deployment plus `.env`-driven operation.
- `terraform/lxc/stacks/netbox-stack/integrations/client.py` implements
  create-or-exists behavior, but not true reconciliation of changed fields.
- `terraform/lxc/stacks/netbox-stack/integrations/populate.py --clean` wipes
  whole NetBox object classes and is not safe once NetBox contains any
  non-repo-managed data.
- There is no single supported command path for discovery, drift review,
  apply, and verification.

The practical conclusion is:
NetBox is deployable, but the population path still needs to be made safe,
explicit, and repeatable before it can be treated as a trusted operational view
of infrastructure reality.

## Target Operating Model

NetBox should be treated as a derived operational inventory for this lab.

Authoritative upstream sources should be:

- Proxmox for VM/LXC existence, state, sizing, and node placement
- MikroTik for router identity, VLANs, routed interface addresses, and live
  edge network state
- LXC/Docker running state for observed services, published ports, networks,
  and container metadata
- Portainer only for later application stacks that are intentionally deployed
  and managed through Portainer
- repo metadata and network intent files only as seed/fallback context where a
  live source does not expose the detail we need

NetBox should not be the first place operators type core infrastructure data by
hand. Manual UI edits should be limited to fields that are explicitly out of
scope for automation.

## Today's Working Assumptions

To keep this work actionable today, the plan assumes:

- infrastructure discovery is reality-first, not intent-first
- Docker runtime discovery should move toward `docker-socket-proxy`, not
  long-lived SSH-based inspection
- raw `/var/run/docker.sock` mounts into the collector are out of scope
- unauthenticated Docker TCP (`2375`) is out of scope
- Proxmox credentials should be a dedicated read-only, privilege-separated API
  token
- MikroTik credentials should be a dedicated read-only user with a custom
  minimal group, not the default `read` group
- NetBox writes should use a dedicated non-superuser service account with only
  the object permissions the reconciler needs
- NetBox token format should move toward a write-enabled v2 token when the
  client path is updated to support it cleanly

## Security And Access Model

Credential expectations for the intended end state:

- NetBox:
  - dedicated service user such as `svc-netbox-sync`
  - non-superuser
  - write-capable token because reconciliation must create and patch objects
  - permissions limited to the NetBox object classes actually managed by the
    workflow
- Proxmox:
  - dedicated service user
  - privilege-separated API token
  - read-only role set sufficient for node, guest, config, status, storage, and
    network discovery
- MikroTik:
  - dedicated service user
  - custom group granting only the minimum read and REST/API capabilities needed
    for discovery
  - source-address restrictions where practical
- Docker:
  - prefer `docker-socket-proxy`
  - allow only the API sections needed for container, port, network, and info
    discovery
  - disable mutating methods such as `POST`

## Scope For The First Good Version

In scope:

- one site
- physical device record for the Proxmox host
- physical device record for the MikroTik router
- one virtualization cluster for Proxmox
- platform, manufacturer, device role, and device type seed data
- VMs and LXCs discovered from Proxmox
- one primary interface per discovered VM or LXC
- primary IPs for the Proxmox host, router interfaces, and discovered guests
- routed prefixes for each managed segment
- VLANs discovered from MikroTik
- published or listening services discovered from LXC/Docker running state
- ownership tags or equivalent metadata for all automation-managed objects

Explicitly out of scope for the first version:

- racks, rack elevations, cables, power feeds, and circuits
- firewall rules, NAT rules, and DHCP details
- patch panels, switch port modeling, and physical cabling
- tenants, contacts, and rich business metadata
- any manual object cleanup outside the automation ownership boundary

## Recommended Object Ownership Rules

Before any live population work, define a strict ownership boundary.

Required rules:

- Every object created by this workflow must carry a consistent ownership marker
  such as a tag or custom field like `managed-by-proxmox-homelab`.
- The workflow may create, patch, and delete only objects carrying that marker.
- The workflow must not use "wipe the whole object class" as its normal update
  model.
- Manual objects created later in NetBox must remain untouched unless they are
  explicitly brought under the same ownership marker.

This is the difference between a population script and a reconciler.

## Step Types

Use these labels when scheduling or handing work off:

- `Light` means analysis, documentation, small code edits, or a single simple
  validation command.
- `Heavy` means significant code changes, live mutation, multi-command
  validation, or coordinated updates across code, docs, and workflow.

## Step-By-Step Delivery Plan

### Step 1 - Lock The Data Model And Ownership Boundary (`Light`)

Goal:
Define exactly what the first automated sync owns and what it ignores.

Work:

- Decide the ownership marker name and apply it consistently across DCIM,
  virtualization, IPAM, services, VLANs, and tags.
- Define which NetBox objects are always repo-managed and which may remain
  operator-managed.
- Decide the object naming rules for:
  - site
  - Proxmox cluster
  - Proxmox host
  - router
  - stack VMs and LXCs
  - generated service objects
- Document source precedence so the code never has to guess.

Verification:

- a short ownership matrix exists in this doc or a linked stack doc
- deletion rules are explicit before any reconcile code is broadened

Exit criteria:

- everyone can answer "if this object drifts, which source wins?"

Why this is `Light`:

- mostly analysis and documentation
- may require only small doc edits once decisions are made
- no live mutations required

#### Step 1 Decisions

The following decisions are now the baseline for the first automated NetBox
sync.

##### Ownership Marker

Use a NetBox tag named `managed-by-proxmox-homelab` as the required ownership
marker for every object created by this workflow.

Rules:

- the reconciler may create only objects that it also tags with
  `managed-by-proxmox-homelab`
- the reconciler may patch only objects that already carry that tag
- the reconciler may report drift or stale state for untagged objects, but must
  not mutate them
- the reconciler must not use broad class wipes as part of normal operation
- any future cleanup mode must scope deletions to objects carrying only the
  automation ownership tag or another explicit automation-owned marker set

##### Ownership Matrix

| NetBox object class | First-version owner | Automation action allowed | Notes |
|---|---|---|---|
| site (`Homelab`) | repo-managed | create, patch | single site for this lab |
| manufacturers | repo-managed | create, patch | seed data only |
| platforms | repo-managed | create, patch | seed data only |
| cluster types | repo-managed | create, patch | seed data only |
| device roles | repo-managed | create, patch | seed data only |
| device types | repo-managed | create, patch | seed data only |
| Proxmox cluster | repo-managed | create, patch | derived from lab topology |
| Proxmox host device | repo-managed | create, patch | single physical hypervisor |
| router device | repo-managed | create, patch | physical edge/gateway record |
| VM/LXC records | repo-managed | create, patch, stale-report | existence comes from Proxmox |
| VM/LXC interfaces | repo-managed | create, patch, stale-report | one managed primary interface per guest in phase 1 |
| host/router interfaces | repo-managed | create, patch | limited to modeled interfaces in scope |
| prefixes | repo-managed | create, patch | routed segments only |
| VLAN groups and VLANs | repo-managed | create, patch, stale-report | sourced from MikroTik |
| IP addresses | repo-managed | create, patch, stale-report | only for managed interfaces and prefixes |
| services | repo-managed | create, patch, stale-report | derived from Portainer published ports |
| tags used by automation | repo-managed | create, patch | includes ownership tag and stack/source tags |
| racks, cables, power, tenancy, contacts | operator-managed | no action | explicitly out of scope |
| any untagged manual object | operator-managed | no action | visible for review, not mutation |

Deletion policy for phase 1:

- no hard deletes outside a future explicit cleanup mode
- normal reconcile runs should prefer:
  - patch when source data still exists
  - mark stale or report-only when source data disappears
- if deletion is later introduced, it must be limited to objects carrying
  `managed-by-proxmox-homelab`

##### Naming Rules

Adopt these names as the desired stable identifiers for phase 1:

- site:
  - name: `Homelab`
  - slug: `homelab`
- Proxmox cluster:
  - name: `pve-cluster`
  - type: `Proxmox VE`
- Proxmox host device:
  - name: `pve`
- router device:
  - name: MikroTik system identity when available
  - fallback name: `mikrotik-router`
- VMs and LXCs:
  - name must match the Proxmox guest name exactly
- prefixes:
  - name/description should reflect the routed segment name, for example
    `infra_seg`, `mgmt_seg`, `edge_seg`, `build_seg`
- services:
  - parent object is the owning VM/LXC
  - service name should be stable per workload, not per discovery run
  - when a workload exposes one port/protocol, use the container or workload
    name
  - when a workload exposes multiple ports or protocols, use
    `<workload>-<port>-<protocol>` to avoid collisions
- tags:
  - keep the ownership tag stable
  - stack tags should follow repo stack names where practical
  - source tags should be reserved for reconciliation metadata, not free-form
    operator notes

Shared-inventory requirement:

- the production NetBox must document assets from both `pve` and `pve-test`
- any identity that is currently global, such as `pve-cluster`, device name
  `pve`, router name `MikroTik`, or VM lookup by bare `name`, must become
  environment-aware before both environments can be safely reconciled into the
  same NetBox
- until that identity work is complete, the current implementation should be
  treated as single-source reconciliation into a shared target, not true
  multi-environment coexistence

##### Source Precedence

When sources disagree, use this precedence order.

For object existence:

1. Proxmox is authoritative for whether a VM or LXC exists
2. MikroTik is authoritative for live router identity, VLAN definitions, and
   router interface addressing
3. LXC/Docker runtime inspection is authoritative for whether an observed
   infrastructure service is currently running and exposed
4. Portainer is authoritative only for later application stacks that are
   intentionally managed there
5. repo metadata and network intent files enrich names, tags, and missing
   context, but do not override authoritative live sources

For specific fields:

- guest name, VMID, node placement, status, CPU, memory, and disk:
  Proxmox wins
- router device name, VLAN IDs, VLAN names, and router-facing IP details:
  MikroTik wins
- observed service ports, protocols, container labels, and running/listening
  state:
  LXC/Docker runtime inspection wins
- Portainer-managed application service metadata:
  Portainer wins when that stack is actually managed in Portainer
- routed segment names, subnet labels, and descriptive annotations:
  repo network files may supply fallback context where the live source does not
  expose enough detail
- stack tags and descriptive metadata:
  repo metadata may enrich objects unless it conflicts with authoritative live
  state
- manually edited unowned fields:
  operator edits remain untouched unless they are later brought under the
  ownership marker

For drift handling:

- if Proxmox no longer reports a guest, the NetBox object becomes stale-report
  candidate rather than immediate delete
- if runtime inspection no longer reports a published or listening service, the
  NetBox service becomes stale-report candidate rather than immediate delete
- if Portainer later no longer reports a Portainer-managed application service,
  the NetBox service becomes stale-report candidate rather than immediate delete
- if MikroTik no longer reports a VLAN or router IP, that object becomes
  stale-report candidate until deletion policy is explicitly expanded
- if repo intent disagrees with live state, live state wins and the repo should
  be corrected separately rather than pushed into NetBox

Step 1 is considered complete once the code changes in later steps are made to
follow these rules rather than redefining them.

### Step 2 - Reduce Intent Dependence And Remove Hardcoded Seed Data (`Heavy`)

Goal:
Make the first population run reflect current observed infrastructure instead of
an old single-LAN assumption or a repo-first model.

Work:

- Replace the hardcoded `PREFIX` in `populate.py`.
- Replace the static Proxmox host IP seed with a declared environment value.
- Model one prefix per routed segment rather than only `192.168.1.0/24`,
  preferring live-discovered context where it is available.
- Decide whether the workstation LAN stays in scope for phase 1 or remains
  intentionally out of scope.
- Keep the site, cluster type, platform, role, and device type seed data.
- Treat repo network intent as fallback context, not the primary live source for
  infrastructure truth.

Verification:

- running the population logic against current source data would create the
  right prefixes for `infra_seg`, `mgmt_seg`, `edge_seg`, and `build_seg`
- no phase 1 object depends on a stale literal IP baked into the script
- no infrastructure object requires repo intent to exist when a live source can
  supply the value

Exit criteria:

- the data model matches the actual segmented network design

Why this is `Heavy`:

- requires code changes in `populate.py`
- touches source-of-truth assumptions for prefixes and host addressing
- likely needs tests plus repeated local verification

#### Step 2 Implementation Notes

The population entrypoint now derives routed prefixes and Proxmox host address
from repo and environment inputs instead of hardcoded LAN literals.

Environment/file selection for network intent:

1. `NETBOX_NETWORK_INTENT_PATH` (explicit file path override)
2. `NETBOX_NETWORK_ENV` (`pve` or `pve-test`)
3. `PVE_ENV`
4. `TF_VAR_proxmox_node`

If no explicit path is provided and none of the environment selectors above are
set, `populate.py` now fails with a clear targeting error instead of silently
defaulting to `pve-test`.

Mapped network intent files:

- `pve` -> `terraform/lxc/network/pve.yaml`
- `pve-test` -> `terraform/lxc/network/pve-test.yaml`
- explicit file-path override with no environment selector -> labeled as
  `custom` in runtime output

Prefix extraction behavior:

- create one NetBox prefix per routed segment declared under `zones`
- resolve each zone through its `attachment`
- include only attachments with `type: sdn_vnet`
- resolve `${...}` subnet placeholders from environment values
- skip unresolved placeholders and non-routed attachments

Proxmox host address behavior:

- no static host IP literal in `populate.py`
- host address is derived from:
  1. `NETBOX_PROXMOX_HOST_ADDRESS`
  2. `LAB_IP_PROXMOX_HOST`
  3. `PROXMOX_HOST_IP`
- if no CIDR is provided, append `/24` by default (override with
  `NETBOX_PROXMOX_HOST_PREFIXLEN`)

### Step 3 - Prove Reality-First Discovery Source By Source (`Heavy`)

Goal:
Confirm what each upstream integration contributes before trusting apply logic.

Suggested validation commands:

```bash
./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/discover.py
./with-secrets-prod python3 terraform/lxc/stacks/netbox-stack/integrations/discover.py
```

Work:

- Run discovery on `pve-test` first.
- Run the same discovery on `pve` once `pve-test` output is understood.
- Capture whether each source succeeds independently:
  - Proxmox
  - MikroTik
- Confirm Docker/LXC runtime service discovery reflects currently running and
  exposed services.
- Decide and document the replacement path from SSH-based guest inspection to
  `docker-socket-proxy`.
- Confirm any current Portainer enrichment is treated as optional and
  app-stack-specific, not required for infrastructure coverage.
- Confirm that MikroTik discovery is complete enough for the VLAN and router IP
  model we want in NetBox.
- Record a representative discovery payload and summarize what each source adds.

Verification:

- discovery exits `0`
- the VM/LXC list is complete enough to explain every deployed stack
- service discovery is clearly attributable to runtime inspection or another
  explicit live source
- optional-source failures degrade clearly instead of failing silently

Exit criteria:

- live discovery is understood, not assumed

Why this is `Heavy`:

- requires live integration checks against multiple external systems
- likely involves more than one command and repeated investigation
- results need to be captured and interpreted, not just observed

#### Step 3 Findings

Live discovery validation established:

- Proxmox guest discovery now works on both `pve-test` and `pve` using the
  current wrapper-injected `TF_VAR_*` env names directly.
- MikroTik discovery works on both `pve-test` and `pve` and returns:
  - router identity
  - router interfaces
  - VLANs
  - router IP addresses
- Portainer enrichment is not currently operational:
  - `pve-test`: `PORTAINER_ADMIN_PASSWORD` is not injected, so enrichment is
    skipped
  - `pve`: credentials are present, but Portainer currently returns zero
    non-local endpoints, so no service enrichment is produced
- Portainer endpoint resolution also has a precedence bug:
  - this was fixed during the Step 3 follow-up slice by ignoring unresolved
    template literals like `${LAB_IP_PORTAINER}`

Observed discovery coverage:

- `pve-test`:
  - guest objects discovered: `14`
  - services discovered: `1` synthetic `portainer-api` service only
  - MikroTik interfaces: `14`
  - MikroTik VLANs: `5`
  - MikroTik router IPs: `7`
- `pve`:
  - guest objects discovered: `25`
  - services discovered: `0`
  - MikroTik interfaces: `14`
  - MikroTik VLANs: `5`
  - MikroTik router IPs: `7`

Implication for the next phase:

- Proxmox and MikroTik are good enough to support further NetBox work
- infrastructure NetBox work should not block on Portainer
- service discovery should move toward `docker-socket-proxy` rather than
  expanding SSH-based inspection

### Step 4 - Turn Population Into Real Reconciliation (`Heavy`)

Goal:
Make the current script safe for repeated runs and meaningful for drift
correction.

Work:

- Extend `NetBoxClient.ensure()` or add a new helper so owned objects are
  patched when managed fields drift.
- Keep lookup keys narrow and stable so updates do not create duplicates.
- Add an explicit dry-run or report mode that shows intended creates, patches,
  and deletes without mutating NetBox.
- Limit `--clean` to automation-managed objects only, or replace it with a more
  specific recovery command.
- Add tests for changed-field reconciliation, not only path stability.

Verification:

- a second run with unchanged discovery data produces no duplicates
- a changed field such as memory, disk, tag set, or service port results in a
  patch rather than a duplicate or silent no-op
- cleanup can no longer delete unrelated manual objects

Exit criteria:

- the workflow is a reconciler, not just a bootstrap seed

Why this is `Heavy`:

- requires non-trivial code changes in client and population behavior
- needs new tests, careful ownership handling, and safety review
- changes the semantics of sync, cleanup, and drift handling

#### Step 4 Implementation Notes

The NetBox population flow now behaves like a bounded reconciler for
automation-owned objects.

Reconciliation behavior added:

- `NetBoxClient.ensure()` now patches managed fields when an owned object
  already exists but differs from desired state.
- lookup keys remain narrow and stable, while mutable fields such as tags,
  descriptions, resource sizing, and service ports are applied through patch
  operations instead of duplicate creates.
- direct primary IP updates now use a helper that respects dry-run mode instead
  of calling raw patch logic.

Ownership and cleanup behavior added:

- automation-managed objects are now tagged with
  `managed-by-proxmox-homelab`
- `--clean` is scoped to automation-owned objects only
- when the ownership tag does not yet exist live, cleanup and stale reporting
  fail closed instead of issuing broad queries

Plan/report behavior added:

- `populate.py --plan` now produces a read-only report of planned creates,
  updates, and stale managed objects
- dry-run mode keeps a synthetic in-memory object view so dependent objects can
  be planned consistently in a single run
- stale reporting compares the desired lookup set against currently managed live
  objects without mutating NetBox

Step 4 validation completed so far:

- unit coverage now includes:
  - changed-field reconciliation in the client
  - dry-run synthetic object lookup behavior
  - cleanup behavior when the ownership tag is missing live
  - stale reporting behavior with and without the live ownership tag
- `./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/populate.py --plan`
  now completes successfully against `pve-test`

What Step 4 still does not claim:

- no live apply was performed as part of Step 4 acceptance
- stale objects are reported, not deleted automatically outside explicit
  cleanup mode
- application-stack service reconciliation via Portainer is still limited by the
  current discovery constraints documented in Step 3
- infrastructure service reconciliation should be driven by runtime inspection,
  not blocked on Portainer

### Step 5 - Seed Shared NetBox From One Source Environment (`Heavy`)

Goal:
Exercise the full create path against the shared production NetBox using one
source environment, and verify that the first managed object set lands
correctly.

Suggested temporary apply command during the validation phase:

```bash
./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/populate.py
```

Work:

- Start with an empty or near-empty shared NetBox managed object set.
- Run the current population flow after the Step 2 and Step 4 fixes.
- Verify that foundation objects, devices, cluster, prefixes, VMs, IPs,
  services, and VLANs all appear as expected.
- Record object counts and spot-check representative objects in the UI or API.
- Record which source environment supplied the discovered data for this first
  seed.

Verification:

- the first apply exits `0`
- expected NetBox object counts become non-zero in the right categories
- created objects carry the ownership marker

Exit criteria:

- first-time population works without manual UI patch-up

Why this is `Heavy`:

- runs live population against a real NetBox instance
- depends on earlier code changes being correct
- requires verification across API output, UI state, and object counts

#### Step 5 Validation Notes

The first live population apply completed successfully against the shared
production NetBox using `pve-test` as the discovery source.

What this proved:

- the reconciler can seed the shared production NetBox from one source
  environment
- the first managed object set lands cleanly with ownership tags and primary
  IPs

What this did not yet prove:

- coexistence of both `pve` and `pve-test` in the same NetBox
- environment-aware identity separation for clusters, devices, VMs, and
  services

Observed object counts after the first live apply:

- `1` site
- `2` devices (`pve`, `MikroTik`)
- `14` virtual machines
- `4` routed prefixes
- `22` IP address objects
- `1` service object
- `4` VLAN objects

Representative post-apply verification confirmed:

- all sampled created objects carry the `managed-by-proxmox-homelab` tag
- both physical devices have primary IPv4 set
- all discovered VMs created in this pass have primary IPv4 set
- no stale managed objects were reported on the first apply

Important observation from live validation:

- MikroTik discovery reports `5` VLAN entries, but only `4` unique VLAN IDs
  are present
- the extra entry is `vlan1-wan`, which also uses `vlan-id: 10`
- the reconciler therefore converges to `4` VLAN objects keyed by VLAN group
  and VID, with `vlan10-build` winning for VID `10`

This means the Step 5 apply is acceptable for first seeding, but any future
VLAN naming policy should explicitly decide how duplicate-discovery names for
the same VID should be handled.

### Step 6 - Add Shared-Inventory Identity Boundaries (`Heavy`)

Goal:
Make it safe for one production NetBox to document both `pve` and `pve-test`
without cross-environment collisions.

Work:

- Replace global object identities with environment-aware identities where
  needed:
  - cluster name
  - hypervisor device name
  - router device name if shared naming would collide
  - any other global object whose current lookup key is only `name`
- Add a stable environment discriminator for VM reconciliation, for example:
  - environment-specific cluster membership
  - environment-specific host linkage
  - VMID plus environment, if needed
- Make sure `pve-test` discovery cannot patch or overwrite `pve` objects, and
  vice versa.
- Add tests that prove both environments can be planned into the same NetBox
  without name-based collisions.
- Run plan mode for both environments against the same NetBox target and review
  the resulting object separation.

Verification:

- planning `pve-test` after `pve`, or `pve` after `pve-test`, does not propose
  cross-environment patches to the same cluster, device, or VM objects
- the same VM name can exist in both environments if the environments are
  intentionally modeled as separate objects
- the shared production NetBox can represent all network assets from both
  environments

Exit criteria:

- the production NetBox can safely hold both `pve` and `pve-test` topology

Why this is `Heavy`:

- requires identity-model changes across reconciliation logic
- affects lookup keys, object naming, and operator expectations
- is the prerequisite for treating shared NetBox coverage as complete

#### Step 6 Implementation Notes

Shared-inventory identity is now modeled explicitly:

- hypervisor device identity is derived from the Proxmox target node
  (`pve`, `pve-test`)
- cluster identity is derived from the target node
  (`pve-cluster`, `pve-test-cluster`)
- VM identity is now environment-safe in NetBox:
  - `<source-name>@<source-node>`
  - examples:
    - `authentik-stack@pve-test`
    - `authentik-stack@pve`
- environment-scoped objects now also carry an environment tag:
  - `netbox-env-pve-test`
  - `netbox-env-pve`

Migration behavior added:

- a one-time legacy-name migration path exists for the currently seeded
  `pve-test` records
- that migration renames previously bare objects such as:
  - `pve` -> `pve-test`
  - `pve-cluster` -> `pve-test-cluster`
  - `authentik-stack` -> `authentik-stack@pve-test`
- legacy bare-name migration is intentionally disabled for `pve` planning so a
  production-source run cannot hijack already-migrated `pve-test` objects

Validation completed:

- local tests now cover:
  - environment-aware inventory context building
  - VM name scoping by source node
  - legacy migration enablement rules
  - client-side legacy lookup migration
- a live `pve-test` apply migrated the shared NetBox from legacy bare names to
  environment-aware `pve-test` identities
- a follow-up `pve-test` plan reported no stale managed objects
- a live `pve` plan against the same NetBox target proposed separate `pve`
  cluster/device/VM objects instead of patching the `pve-test` ones

What remains for the next step:

- a clean no-op rerun is not fully proven yet
- some fields still show planned updates that are not cross-environment
  identity problems, including:
  - cluster/site and prefix/site normalization
  - interface `type` normalization
  - duplicate-source VLAN naming on VID `10`

### Step 7 - Prove Idempotency And Drift Repair (`Heavy`)

Goal:
Show that repeated runs keep NetBox current rather than merely filling it once.

Status update:

- partially complete
- the hypervisor host IP is now derived from the inspected Proxmox node rather
  than the old shared seed value
- a live `pve-test` apply corrected `pve-test` to `192.168.1.40/24` and
  removed the stale managed `192.168.1.2/24` assignment from `vmbr0`
- a full clean no-op rerun is still not proven because other normalization
  churn remains

Work:

- Run the same apply command a second time with no upstream changes.
- Confirm there are no duplicate VMs, interfaces, services, or IPs.
- Introduce at least one controlled upstream change in a test source
  environment, then rerun:
  - adjust a stack tag
  - change a VM memory allocation
  - add or remove a published service port
- Confirm the next run patches the owned NetBox object correctly.
- Decide the first deletion policy:
  - report only
  - soft-retire or tag as stale
  - hard delete after confirmation

Recommended first deletion policy:

- first version should report stale objects and optionally tag them as stale
- hard deletion should wait until the ownership boundary and reconcile behavior
  have been proven

Verification:

- no-op rerun is clean
- changed upstream data is reflected in NetBox
- disappearing upstream data is surfaced clearly

Exit criteria:

- NetBox freshness is testable, not assumed

Why this is `Heavy`:

- requires repeated apply and verification cycles
- may require controlled upstream changes to prove reconciliation behavior
- directly tests whether the workflow is safe for day-2 operation

### Step 8 - Package The Supported Operator Workflow (`Heavy`)

Goal:
Replace ad hoc Python entrypoints with one documented command surface.

Recommended target shape:

- `discover` for read-only source inspection
- `plan` for drift review
- `apply` for reconciliation
- `verify` for post-run checks

Recommended implementation options:

- a dedicated repo wrapper script under `scripts/`
- a stack-specific Ansible playbook
- a thin wrapper around the existing Python modules plus structured output

Requirements:

- credentials come from `./with-secrets` or `./with-secrets-prod`, never from
  `source .env`
- production mutation should go through an explicitly approved command path
- command output should be readable enough to paste into evidence or handback
- the workflow should set or derive `NETBOX_URL` instead of requiring manual
  exports
- the workflow should use dedicated least-privilege source credentials
- the preferred Docker runtime discovery path should be `docker-socket-proxy`
  rather than guest SSH
- the NetBox writer should be a dedicated non-superuser service account token

Important production note:

- `with-secrets-prod` currently treats `python3` as a read-only command class
  even though `populate.py` mutates NetBox over HTTP
- before calling production apply "supported", package it behind a command path
  that is clearly treated as a mutation and requires deliberate approval

Verification:

- operators have one documented way to inspect, apply, and verify sync
- stale `.env` examples are removed from stack-local NetBox docs

Exit criteria:

- NetBox sync is an operational workflow, not a repo trivia fact

## Operator entrypoint

To provide a single supported command surface for operators and CI, this
repository exposes a thin wrapper script: `scripts/netbox-populate.sh`.

- Supported verbs (exact mapping):
  - `discover` : runs `terraform/lxc/stacks/netbox-stack/integrations/discover.py` (read-only). Uses `./with-secrets` when available for local runs.
  - `plan`     : runs the containerized `populate.py --plan` (dry-run) via the internal helper.
  - `apply`    : runs the containerized `populate.py` (default apply behavior) via the internal helper.
  - `clean`    : runs the containerized `populate.py --clean` via the internal helper.

The internal helper `scripts/run-netbox-populate-container.sh` remains an
implementation detail (it handles building the env file and mounting an SSH
identity when present). CI and humans should prefer `scripts/netbox-populate.sh`
as the single supported entrypoint. The GitHub Actions workflow now invokes the
wrapper so CI and operators use the same path.

Deferred verbs:

- `verify` is intentionally deferred because there is no single underlying
  canonical verification action implemented in the integrations; if you need a
  custom post-apply check, run discovery or inspect NetBox API directly.

Why this is `Heavy`:

- requires new wrapper code or playbook work plus doc updates
- touches production-safety expectations and approval flow
- may require coordinated changes to stack-local docs and scripts

### Step 9 - Complete Shared-Inventory Rollout And Define Day-2 Cadence (`Heavy`)

Goal:
Move from first-source seeding to a durable shared production NetBox practice
that covers both `pve` and `pve-test`.

Shared-inventory rollout sequence:

1. complete Step 6 identity-boundary work
2. run discovery on the remaining environment not yet represented safely
3. compare the payload with the already-proven first-source model
4. run the supported shared-NetBox apply command
5. verify counts and representative objects
6. rerun once to confirm idempotency after both environments are represented

Day-2 triggers for rerun:

- after `scripts/provision.sh --stack <name>`
- after any stack rebuild or teardown/redeploy cycle
- after VLAN, subnet, or gateway changes on the MikroTik
- after Docker-exposed infrastructure service changes
- after later Portainer-managed application service exposure changes
- on a scheduled periodic cadence for drift review

Recommended cadence:

- `discover` or `plan` after every infra change
- `apply` after verified infra changes that should appear in NetBox
- a weekly read-only drift review even if no deliberate change occurred
- a post-teardown repopulation run before declaring the rebuild complete

Verification:

- operators can distinguish "NetBox is up" from "NetBox is current"
- repopulation after rebuild succeeds without manual object repair

Exit criteria:

- NetBox stays current through normal lab operations

Why this is `Heavy`:

- involves production validation and repeated operator workflow checks
- includes rollout sequencing, verification, and ongoing operational policy
- combines live commands, documentation, and process decisions

## Recommended Work Order By Weight

Start with the `Light` step:

1. Step 1 - lock ownership, naming, and source precedence

Then move through the `Heavy` steps in this order:

1. Step 2 - reduce intent dependence and remove hardcoded seed data
2. Step 3 - prove reality-first discovery inputs
3. Step 4 - build real reconciliation behavior
4. Step 5 - seed shared NetBox from one source environment
5. Step 6 - add shared-inventory identity boundaries
6. Step 7 - prove idempotency and drift handling
7. Step 8 - package the supported operator workflow
8. Step 9 - complete shared-inventory rollout and define cadence

## What "Done" Looks Like

This work is complete when all of the following are true:

- NetBox can be deployed empty and then populated entirely from automation
- NetBox reflects observed infrastructure reality more than repo intent
- the sync path is safe to run repeatedly
- managed objects are patched when source data changes
- stale objects are reported predictably and handled within an explicit policy
- production sync goes through an approved command path
- stack-local NetBox docs match the real deployment and sync workflow

## Immediate Next Actions

The shortest useful path from the current state is:

1. audit socket-proxy rollout state before assuming production coverage:
   - repo-declared opt-in state in stack metadata
   - generated inventories, if relevant
   - live listener/container state only through an explicitly approved
     production-check command
2. define the explicit Docker host-targeting model for NetBox runtime
   discovery:
   - Proxmox-discovered Docker guests
   - explicitly declared non-Proxmox Docker hosts
   - hosts intentionally excluded from probing
3. decide whether the current `populate.py` augmentation should be kept,
   narrowed, or replaced by that host-targeting model
4. only after the target model is clear, plan any opt-in enablement on selected
   production infrastructure containers

Important note:

- do not treat the disposable test stack or the monitoring canary as proof of
  broad production rollout
- do not use SSH as a workaround for Docker scraping; if a future deployment or
  verification step needs host access, it must be justified as part of the
  rollout audit or provisioning path

## Copilot Execution Contract

This plan is intended to be handed off to GitHub Copilot using `GPT-5 mini`
only.

To keep Copilot productive and recoverable:

- one Copilot session must do exactly one bounded chunk of work
- each chunk must have one primary objective and one explicit stop condition
- prefer sessions that touch `2-4` files, not broad repo-wide rewrites
- do not combine design decisions, transport changes, credential redesign, and
  live validation in the same pass
- do not ask one pass to both refactor code and prove production behavior unless
  the code change is tiny
- if a pass uncovers ambiguity, the pass should stop and hand back the exact
  blocker rather than broadening scope
- a pass may update docs, code, tests, or workflow files, but should not try to
  complete multiple plan steps at once
- production mutation is a late-stage activity; early Copilot passes should stay
  local, reviewable, and easy to validate
- when preparing a Copilot session for a human operator, the final prompt must
  be delivered in chat as one copy/pasteable fenced code block, not only as a
  file path or summary

Use this rule of thumb for `GPT-5 mini` handoff sizing:

- good:
  - rename one env contract and update the affected docs/tests
  - add one small discovery helper and its focused tests
  - fix one playbook structure bug and run syntax/local validation
  - make one workflow input optional and document the fallback behavior
- bad:
  - redesign discovery transport, credentials, docs, tests, and workflow in one
    pass
  - perform broad cleanup of all NetBox stack docs plus live validation plus
    auth redesign
  - mix `pve-test` and `pve` production behavior changes with refactors

## Local Artifact Discipline

Session handbacks, prompts, and handoffs for `netbox-stack` are local work
artifacts. They may be useful during active work, but they are not durable
project documentation and must remain ignored by Git.

Use this ignored path for local session artifacts:

- `docs/netbox-stack/artifacts/`

Rules:

- create a new handback file for each session
- do not overwrite the previous session's handback
- use a stable name such as:
  - `SESSION-01-<short-topic>-HANDBACK.md`
  - `SESSION-02-<short-topic>-HANDBACK.md`
- if a new session handoff is needed, place it under
  `docs/netbox-stack/artifacts/`
- any durable state learned from a session must be summarized in tracked docs
  such as `docs/netbox-stack/current-state.md`
- if a session prompt is prepared for operator use, store it on disk and also
  present the exact prompt text in chat as a copy/pasteable fenced code block

Each local handback should be detailed enough for:

- post-mortem analysis
- deciding the next Copilot chunk
- recovering from partial changes or wrong turns
- understanding what was verified versus merely edited

Minimum required handback content:

- session identifier and date
- model used: `GitHub Copilot GPT-5 mini`
- objective and explicit scope boundary
- files reviewed
- files changed
- commands run
- validation actually completed
- validation not completed
- concrete outcomes
- blockers or unexpected behavior
- risks introduced or left unresolved
- recommended next single Copilot session

## Copilot Session Roadmap

Use the roadmap below when handing work to Copilot. Each session is purposely
small enough that `GPT-5 mini` should not need to hold too many moving parts at
once.

### Session 1 - Audit The Current Uncommitted NetBox Work

Goal:

- produce a mismatch matrix between the current uncommitted implementation and
  this updated plan

Scope:

- docs and code review only
- no implementation changes unless a tiny doc correction is unavoidable

Primary files:

- `docs/netbox-stack/README.md`
- `terraform/lxc/stacks/netbox-stack/integrations/discover.py`
- `terraform/lxc/stacks/netbox-stack/integrations/client.py`
- `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`

Done when:

- the handback lists which changes are aligned, misaligned, broken, or stale

### Session 2 - Repair The Broken Playbook Structure Only

Goal:

- make `deploy-netbox-stack.yml` structurally valid again without redesigning
  the populate architecture

Scope:

- one playbook
- syntax/structure fix only

Primary files:

- `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`

Done when:

- the playbook parses cleanly
- the handback states whether the timer block is still conceptually valid after
  the structural fix

### Session 3 - Align Stack Docs And Contract Files With The New Model

Goal:

- remove stale claims that infrastructure discovery is SSH-first or
  Portainer-required

Scope:

- docs only

Primary files:

- `terraform/lxc/stacks/netbox-stack/README.md`
- `terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md`
- `.env.template`
- `.env.pve-test.template`

Done when:

- docs describe reality-first discovery, `docker-socket-proxy` as the preferred
  direction, and least-privilege credential expectations

### Session 4 - Introduce A Neutral NetBox Writer Token Surface

Goal:

- stop hardcoding the implementation to a superuser-named env var

Scope:

- env/interface cleanup only
- do not redesign permissions bootstrap in the same pass

Primary files:

- `terraform/lxc/stacks/netbox-stack/integrations/client.py`
- relevant tests under `terraform/lxc/stacks/netbox-stack/integrations/`
- stack docs/contracts if needed

Done when:

- the code prefers a neutral name such as `NETBOX_API_TOKEN`
- backward compatibility is documented if retained

### Session 5 - Narrow Proxmox Discovery Credentials

Goal:

- align Proxmox discovery inputs with a dedicated read-only, privilege-separated
  token model

Scope:

- env names, docs, and focused client handling only

Primary files:

- `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py`
- `.env.template`
- `.env.pve-test.template`
- stack docs/contracts

Done when:

- the handback clearly states the expected read-only Proxmox credential
  contract

### Session 6 - Narrow MikroTik Discovery Credentials

Goal:

- align MikroTik discovery inputs with a dedicated read-only user model

Scope:

- env names, docs, and focused client handling only

Primary files:

- `terraform/lxc/stacks/netbox-stack/integrations/mikrotik_client.py`
- `.env.template`
- `.env.pve-test.template`
- stack docs/contracts

Done when:

- the handback clearly states the expected read-only MikroTik credential
  contract

### Session 7 - Isolate Runtime Service Discovery Behind One Interface

Goal:

- make service discovery transport replaceable without changing the rest of the
  reconciliation flow

Scope:

- discovery refactor only
- no workflow switch yet

Primary files:

- `terraform/lxc/stacks/netbox-stack/integrations/discover.py`
- focused discovery tests

Done when:

- the code has a clear seam between "discover services" and "how transport
  reaches Docker state"

### Session 8 - Add `docker-socket-proxy` Discovery Support

Goal:

- add a preferred Docker runtime discovery path that does not require guest SSH

Scope:

- discovery code, env contract, and tests only
- do not remove the old path in the same pass unless it is trivially isolated

Primary files:

- `terraform/lxc/stacks/netbox-stack/integrations/discover.py`
- `terraform/lxc/stacks/netbox-stack/integrations/Dockerfile`
- relevant tests
- docs/contracts

Done when:

- the handback shows what env/config is expected for proxy-based discovery

### Session 9 - Switch The Runner/Workflow To The Preferred Discovery Path

Goal:

- update the workflow and wrapper scripts to use the preferred non-SSH runtime
  discovery path

Scope:

- workflow/wrapper only
- no client refactors in the same pass

Primary files:

- `.github/workflows/netbox-populate.yml`
- `scripts/run-netbox-populate-container.sh`

Done when:

- the runner no longer depends on mounted guest SSH keys for the infrastructure
  discovery path

### Session 10 - Make Portainer Explicitly Optional And App-Stack-Only

Goal:

- ensure Portainer is an optional enrichment source, not an infrastructure
  dependency

Scope:

- focused discovery/docs cleanup

Primary files:

- `terraform/lxc/stacks/netbox-stack/integrations/discover.py`
- stack docs/contracts
- relevant tests

Done when:

- infrastructure discovery still works without Portainer inputs
- docs clearly state Portainer is for later app stacks

### Session 11 - Package The Supported Operator Entry Point

Goal:

- present one supported command surface for discover/plan/apply/verify

Scope:

- wrapper surface and docs only
- no new transport redesign in this pass

Primary files:

- `scripts/`
- `docs/netbox-stack/README.md`
- stack docs/contracts

Done when:

- operators have one documented and reviewable command path

### Session 12 - Validation And Closeout Evidence

Goal:

- prove what now works locally and what still requires live validation

Scope:

- validation and docs only
- no broad refactors

Done when:

- the handback distinguishes:
  - code changed
  - locally validated
  - not yet live-proved
  - blocked or deferred

That keeps the work focused on the real gap:
NetBox is already deployed, but it is not yet being maintained as a trusted,
rebuild-safe view of observed infrastructure reality.
