# pve Production Readiness Plan

## Goal

Prepare the existing LXC deployment pipeline to target the production Proxmox
host `pve` safely, with environment-specific storage and network configuration,
and without accidental collisions against the workloads already running there.

This plan is based on:

- repo inspection of the current Terraform, stack, storage, and network model
- read-only SSH inspection of `root@pve.gibbsgreatly.xyz`

## Status Update

As of May 25, 2026:

- the `apt-cacher-stack` production canary on `pve` passed after the VLAN 40
  trunk fix
- the direct-access provisioning model is now proven on `pve`
- the main operational lesson is collision control: if a stack reuses the same
  service IP on `pve-test` and `pve`, stop or destroy the `pve-test`
  counterpart before bringing up the `pve` instance
- the `monitoring-stack` canary on `pve` completed and passed
- the `portainer-stack` canary on `pve` completed and passed
- the `netbox-stack` canary on `pve` completed and passed
- operator sign-in is currently confirmed through Authentik for `portainer`,
  `grafana`, `harbor`, and `netbox`
- the live `pve` branch state now looks ready for promotion planning to a
  production-focused long-lived branch instead of more break/fix work
- the next low-risk production migration after `netbox-stack` is
  `ci-runner-01`
- monitoring canary closure evidence is captured under
  `docs/productionize-refactor/09-monitoring-canary-closure.md`
- portainer canary closure evidence is captured under
  `docs/productionize-refactor/11-portainer-canary-closure.md`

## Refactor Scope

This refactor covers five tightly related concerns:

1. Make the stack catalog environment-aware instead of `pve-test`-pinned.
2. Model production storage and production network intent as tracked source.
3. Add strict controls around any production credential exposure to AI.
4. Prove production networking early with canary validation.
5. Enable incremental, service-by-service migration from `pve-test` to `pve`.

This refactor does not assume:

- a single full teardown of the platform
- one-shot cutover of every service
- immediate production mutation access for AI

## Desired End State

At the end of this refactor, we want:

- `terraform/lxc/storage/pve.yaml` to exist and be validated
- `terraform/lxc/network/pve.yaml` to match the active VLAN-zone design
- active platform stacks to be targetable to `pve` without hardcoded
  `proxmox_node: pve-test`
- production credential handling to be separated from the normal dev workflow
- a documented canary path for first deployment on `pve`
- a documented migration order for moving real services off `pve-test`

## Branching For This Refactor

Refactor integration branch:

- `refactor/productionize`

Original refactor base:

- `baseline/teardown-validated`

Production promotion target after `pve` validation:

- `prod/pve-infra`

Recommended implementation branches:

- `work/productionize-01-storage-manifest`
- `work/productionize-02-network-intent`
- `work/productionize-03-prod-credential-controls`
- `work/productionize-04-stack-target-decoupling`
- `work/productionize-05-canary-gate`
- `work/productionize-06-service-migration-order`

Branching rule:

- each work branch should complete one coherent slice
- merge each slice into `refactor/productionize`
- keep productionization planning and implementation grouped under this branch
  family until the whole program is coherent
- once the production branch state is validated on `pve`, promote it to
  `prod/pve-infra`

## Task Breakdown

Detailed task docs live under:

- [tasks/README.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/README.md:1)

Primary tasks:

1. [Task 01: Production Credential Controls](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/01-credential-controls.md:1)
2. [Task 02: Production Environment Model](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/02-production-environment-model.md:1)
3. [Task 03: Production Storage Manifest](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/03-production-storage-manifest.md:1)
4. [Task 04: Production Network Intent](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/04-production-network-intent.md:1)
5. [Task 05: Stack Target Decoupling](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/05-stack-target-decoupling.md:1)
6. [Task 06: Canary Validation Gate](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/06-canary-validation-gate.md:1)
7. [Task 07: Incremental Migration Plan](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/07-incremental-migration-plan.md:1)

## Current Findings

### 1. Production storage is usable, but not modeled in repo

The production host already has the storage backends needed for this work:

- `infrastructure-containers`
- `storage-containers`
- `storage-template`
- `local`
- `local-zfs`

The required Docker template already exists on production in
`storage-template` as `debian-13.1-2-docker-template.tar.gz`.

The gap is in tracked configuration:

- `terraform/lxc/storage/pve.yaml` does not exist
- Terraform expects `storage/<proxmox_node>.yaml` and hard-fails if it is
  missing

### 2. Production network intent is not aligned with the active design

The current production network intent file `terraform/lxc/network/pve.yaml`
describes:

- `simple` SDN zones
- zone names like `apps`, `infra`, `apps_seg`, `media_seg`, `observe_seg`

The active design and active platform stacks use:

- Proxmox SDN VLAN zones
- zone names `build_seg`, `mgmt_seg`, `edge_seg`, `infra_seg`

This means the production intent file must be reworked before the current
platform stacks can target `pve`.

### 3. Production VLAN readiness is now an assumed prerequisite, but must be validated early

Earlier inspection showed:

- `vmbr0` is the active LAN bridge on `192.168.1.2/24`
- Proxmox SDN zones and VNets were empty at the time of inspection

Current planning assumption:

- the operator has now prepared the switch and `pve` host for VLAN use on
  `vmbr0`
- we should proceed on the assumption that this is intended to work

Planning rule:

- treat VLAN readiness as a prerequisite supplied outside this repo
- validate it as the first technical gate before any service migration or real
  production apply

### 4. Platform stacks are environment-pinned today

The active platform stack definitions still include `proxmox_node: pve-test`.
That is expected for the current dev workflow, but it means production cannot
be driven by environment parameters alone yet.

This affects at least:

- `authentik-stack`
- `step-ca-stack`
- `monitoring-stack`
- `dns-stack`
- `portainer-stack`
- `proxy-stack`
- `harbor-stack`
- `apt-cacher-stack`
- `netbox-stack`
- `ci-runner-01`

### 5. Production credential controls are not yet strong enough

Current repo guardrails are oriented around keeping normal work on `pve-test`:

- `with-secrets` defaults to `PVE_ENV=pve-test`
- non-`pve-test` execution is blocked unless `ALLOW_PVE=true`

That is helpful, but it is not sufficient for safe production AI operation.

Productionization should assume:

- production secrets must be separated from default dev secret flows
- production read-only access and production mutating access should not share
  the same execution path
- production mutations require additional approval controls beyond environment
  variables alone

## Collision Inventory

## VMID collisions

For the active platform cohort, the intended VMIDs do not currently collide
with production VMIDs.

Planned platform VMIDs:

- `10063` ci-runner-01
- `20010` authentik-stack
- `20011` step-ca
- `20012` monitoring-stack
- `20013` dns-stack
- `20020` portainer-stack
- `30010` proxy-stack
- `40010` harbor-stack
- `40011` apt-cacher-stack
- `40012` netbox-stack

Observed production CT/VM IDs:

- CTs: `100, 101, 102, 103, 104, 105, 107, 109, 110, 112, 114, 115, 116, 119, 121, 131, 910`
- VMs: `106, 108, 111, 113, 120`

Conclusion:

- no direct VMID collision for the production platform stack set
- the validation/test CT `131` already exists on production and remains a
  collision for `test-docker`, but that is outside the production platform
  rollout scope

## IP address collisions

Current production workloads are primarily on `192.168.1.0/24`.

Existing production service examples:

- `management-stack` at `192.168.1.4`
- `harbor-stack` at `192.168.1.10`
- `netbox-stack` at `192.168.1.30`

The repo template currently defines segmented addresses:

- `build_seg`: `192.168.10.0/24`
- `mgmt_seg`: `192.168.20.0/24`
- `edge_seg`: `192.168.30.0/24`
- `infra_seg`: `192.168.40.0/24`

Conclusion:

- if production adopts the segmented VLAN ranges, there is no direct overlap
  with the current `192.168.1.0/24` workloads
- if we attempted to deploy onto the flat LAN instead, there would be immediate
  addressing and routing ambiguity
- when a service intentionally reuses its `pve-test` segmented IP on `pve`,
  cutover sequencing must ensure the `pve-test` counterpart is stopped first

## Hostname and service-role collisions

There are already production containers named:

- `harbor-stack`
- `netbox-stack`

There is also an existing `management-stack` that overlaps in role with the
future Portainer/Auth/management plane.

Conclusion:

- this must be treated as a migration/cutover problem, not a clean first
  deployment
- we need an explicit strategy for whether services are replaced in place,
  rebuilt in parallel, or temporarily duplicated under alternate names

## Storage collisions

There is no backend-name collision problem in the sense of missing storage.
Instead, the production issue is backend selection and coexistence:

- current production containers already consume `infrastructure-containers`
- some existing workloads also consume `storage-containers`
- the repo currently only models the `pve-test` storage mapping

Conclusion:

- production needs a deliberate storage policy document and manifest
- we should avoid ad hoc reuse of `local-lvm`-style assumptions from
  `pve-test`

## Recommended Strategy

### 1. Keep the environment model, do not fork the stack model

Recommended:

- keep one shared stack catalog
- move production-specific choices into environment manifests and env overlays

That means:

- remove or override `proxmox_node: pve-test` from active platform stacks
- keep stack-local intent like VMID, rootfs size, docker size, and zone
- put production-specific storage and network mapping into `pve` manifests

### 2. Make production network look like the active design, not the old `pve.yaml`

Recommended production target model:

- the same logical zones used by the current active platform stacks:
  `build_seg`, `mgmt_seg`, `edge_seg`, `infra_seg`
- VLAN-backed SDN attachments
- MikroTik as the L3 gateway and DNS entry point, matching the current design

Do not keep the current `simple`-zone `pve.yaml` model unless we consciously
choose to diverge production from dev.

### 3. Use a migration path, not an in-place blind apply

Recommended migration stance:

- first prepare host networking and manifests
- then decide service-by-service whether to:
  - replace an existing production container in place
  - create a parallel replacement on the new segmented network
  - preserve an existing service outside this rollout

For safety, prefer parallel deployment plus cutover for services that already
exist on `pve`.

### 4. Treat production credential control as a first-class workstream

Recommended control posture:

- default AI workflow remains `pve-test` only
- production credentials are not loaded by the standard `./with-secrets`
  wrapper
- production read-only inspection has a separate, more constrained path
- production mutating operations require an additional explicit gate

### 5. Validate early, migrate gradually

Recommended migration stance:

- test network readiness before changing real services
- prove one canary deployment on `pve`
- then move one low-risk real service at a time
- avoid coupling the whole productionization effort to a single cutover event

## Workstreams

## Workstream 1: Production environment parameterization

Create a production env overlay, for example `.env.pve`, that defines:

- `PROXMOX_HOST=pve.gibbsgreatly.xyz`
- `TF_VAR_proxmox_node=pve`
- production `LAB_IP_*`
- production `LAB_GW_*`
- production `LAB_SUBNET_*`
- production `LAB_DOMAIN` and active-stack `LAB_FQDN_*`
- optional `LAB_ADMIN_USERNAME` / `LAB_ADMIN_EMAIL` values when operator identity
  should be explicit instead of playbook-defaulted
- matching `TF_VAR_lab_*` exports for Terraform template rendering
- production-specific route, DNS, and certificate settings as needed

Files likely involved:

- `.env.template`
- new `.env.pve` or equivalent local overlay
- guard scripts that currently assume `pve-test`

Deliverables:

- production env overlay documented and isolated from dev defaults
- explicit variable inventory for `LAB_IP_*`, `LAB_GW_*`, `LAB_SUBNET_*`
- explicit statement of which production address values are confirmed vs still
  operator-supplied placeholders
- clear load order rules for `.env`, `.env.<env>`, and secret injection

Practical blocker detail:

- Terraform stack rendering reads `TF_VAR_lab_*` values via `terraform/lxc/main.tf`
- active stack playbooks and helper renders also read raw `LAB_*` values directly
- because `./with-secrets-prod` sources `.env.pve` only, the production overlay
  must export both surfaces explicitly
- current repo state confirms the segmented production gateway/subnet/domain
  model, but does not yet confirm the full production `LAB_IP_*` service set

## Workstream 2: Production storage manifest

Create `terraform/lxc/storage/pve.yaml`.

Initial recommended mapping direction:

- `platform-default.rootfs_storage`: `infrastructure-containers`
- `platform-default.docker_storage`: `infrastructure-containers`
- `durable-default.storage`: choose deliberately between
  `infrastructure-containers` and `storage-containers`
- template storage: `storage-template`

Rationale:

- this matches the shape of how production is already using storage
- it avoids pretending `local-lvm` exists as the desired production runtime
  target
- it uses the location where the required Docker template already exists

This manifest should be validated against live production with
`terraform/lxc/validate-storage-contract.py`.

Deliverables:

- `terraform/lxc/storage/pve.yaml`
- storage profile mapping for rootfs, Docker, extra mounts, and templates
- production validation command set for live storage verification

## Workstream 3: Production network intent rewrite

Rewrite `terraform/lxc/network/pve.yaml` so it matches the active VLAN model.

The target file should:

- use zone names `build_seg`, `mgmt_seg`, `edge_seg`, `infra_seg`
- use `zone_type: vlan`
- declare VLAN IDs, subnets, and gateways
- attach to the selected production trunk bridge

Implementation decision:

- production VLAN trunking will use `vmbr0`
- `vmbr0` should be made VLAN-aware as part of the host preparation steps
- this is now assumed to have been done or to be under operator control
- we still validate it before the first migrated stack

Deliverables:

- rewritten `terraform/lxc/network/pve.yaml`
- documented production VLAN/IP mapping
- documented dependency on router ACLs and DNS forwarding behavior

## Workstream 4: SDN/VLAN automation gap

The docs already note that the current SDN automation handles `simple` zones
only.

Before production rollout, choose one of:

1. Extend the automation to support VLAN zones on `pve`
2. Treat SDN VLAN creation as a manual prerequisite for the first production
   cutover

Recommendation:

- automate it before production if possible
- if not, document the manual prerequisite exactly and validate it before any
  stack apply

Deliverables:

- clear decision: automate VLAN-zone creation or keep it manual
- if manual, exact operator runbook and validation commands
- if automated, code path verified against `pve`

## Workstream 4a: Early VLAN validation gate

Because the switch and `pve` VLAN setup is being handled incrementally outside
the repo, we should test it early instead of waiting until a full migration
attempt.

Recommended early validation sequence:

1. Confirm `vmbr0` is VLAN-aware on `pve`.
2. Confirm the expected VLAN-backed SDN zones/VNets exist or can be created.
3. Deploy one low-risk canary container on `pve` in a target zone.
4. Verify:
   - it gets the intended IP and gateway
   - it can reach its zone gateway
   - it can resolve DNS via the intended resolver
   - it can reach one dependency on another segment if required
   - it can reach the internet only where expected

Suggested first canary options:

- best infrastructure proof: a disposable test LXC on one production VLAN
- best first real service: `apt-cacher-stack`

Success criteria for the VLAN gate:

- tagged traffic passes through `vmbr0`
- the routed VLAN can talk to the MikroTik gateway
- DNS and basic north-south routing behave as expected
- a single migrated stack can still interoperate with services remaining on
  `pve-test`

Deliverables:

- canary validation runbook
- defined success/failure criteria
- first chosen canary stack or disposable validation target

## Workstream 5: Production credential controls

Goal:

- make production credential exposure to AI intentionally narrow, auditable, and
  non-default

Recommended design direction:

- keep `./with-secrets` as `pve-test`-oriented
- create a separate production wrapper rather than broadening the current one
- split production secrets from dev secrets
- distinguish read-only and mutating production operations

Recommended control layers:

1. Separate encrypted secret source for production.
2. Separate wrapper for production access.
3. Read-only by default for production AI access.
4. Extra approval token or approval packet for mutating production commands.
5. Logging/evidence capture for every production invocation.

Likely deliverables:

- production secret file design and naming
- production wrapper design
- command-class policy for read-only vs mutating use
- documented operator approval workflow

## Workstream 6: Stack target decoupling

Goal:

- allow active platform stacks to target `pve` or `pve-test` through
  environment selection instead of embedded node pins

Recommended direction:

- remove hardcoded `proxmox_node: pve-test` from active platform stacks
- keep stack-local zone, sizing, and service intent
- let environment-specific manifests resolve the physical target details

Deliverables:

- active stack YAML cleanup
- confirmation that generated inventories still reflect the intended target
- updated docs for target selection rules

## Workstream 7: Incremental migration sequencing

Goal:

- define how services move one-by-one from `pve-test` to `pve`

Recommended sequencing principle:

- move the least coupled services first
- avoid moving central dependency services first unless the network and control
  plane are already proven

Candidate early movers:

- disposable test LXC
- `apt-cacher-stack`
- `dns-stack`

Candidate later movers:

- `proxy-stack`
- `authentik-stack`
- `harbor-stack`
- `netbox-stack`

Deliverables:

- ranked migration order
- per-service cutover notes
- dependency-aware rollback plan

## Workstream 5: Stack environment decoupling

Update platform stack definitions so production targeting is not blocked by
hardcoded `proxmox_node: pve-test`.

Recommended direction:

- remove the per-stack `proxmox_node` pin from the active platform stacks
- let the effective target come from the environment
- keep stack-local network zone definitions in place

Files likely involved:

- `terraform/lxc/stacks/*/stack.yaml`

## Workstream 6: Collision-aware cutover planning

Build a service-by-service cutover sheet for the production host.

At minimum track:

- stack name
- existing production equivalent
- current production VMID/IP
- planned new VMID/IP
- whether the service will be replaced in place or deployed in parallel
- dependencies and cutover order

Initial notable collisions in role/name:

- `harbor-stack` already exists on production as CT `121`
- `netbox-stack` already exists on production as CT `119`
- `management-stack` likely overlaps with the future management-plane split

## Recommended Production Storage And Memory Sizing

These are homelab-oriented recommendations, not enterprise sizing targets.
The goal is "enough headroom to be boring" for one operator and light
background use, without wasting large amounts of RAM or premium storage.

### Storage layout recommendation

Recommended default policy for `pve`:

- put container root filesystems on `infrastructure-containers`
- put Docker writable layers on `infrastructure-containers` for normal
  platform services
- put large or fast-growing service data on explicit extra mounts
- put template artifacts on `storage-template`
- reserve `storage-containers` for bulky service data where growth matters more
  than keeping everything on the infrastructure pool

Reasoning:

- `infrastructure-containers` already hosts production-style service rootfs
  workloads today
- `storage-containers` has abundant free space and is a good candidate for
  larger data volumes
- `storage-template` already contains the required Debian Docker template
- the current live Harbor and NetBox datasets are still small, so we do not
  need oversized allocations just to get started

### Per-service recommendation

| Stack | Service type | Recommended rootfs storage | Recommended Docker/data storage | Recommended RAM | Notes |
|---|---|---|---|---|---|
| `portainer-stack` | Docker Compose | `infrastructure-containers`, `8G` rootfs | `infrastructure-containers`, `8-10G` Docker | `512M-1G` | Small service. `512M` is probably enough; `1G` if you want comfortable headroom. |
| `authentik-stack` | Docker Compose | `infrastructure-containers`, `8-12G` rootfs | `infrastructure-containers`, `15-20G` Docker | `2G` | Keep `2G` as the baseline. For a lightly used homelab there is little reason to exceed it initially. |
| `step-ca-stack` | systemd | `infrastructure-containers`, `6-8G` rootfs | none if schema is fixed; otherwise current default mount is wasted | `512M` | Very light service. Could run in `256M`, but `512M` is the safer no-drama size. |
| `monitoring-stack` | Docker Compose | `infrastructure-containers`, `8-12G` rootfs | `monitoring-containers` or `storage-containers`, `30-50G` Docker/data | `2G` | Time-series retention is the main growth driver. Put the write-heavy data on a larger pool if you expect long retention. |
| `dns-stack` | systemd | `infrastructure-containers`, `6-8G` rootfs | none if schema is fixed; otherwise current default mount is wasted | `256M-512M` | CoreDNS is tiny. `512M` is generous. |
| `proxy-stack` | Docker Compose | `infrastructure-containers`, `8G` rootfs | `infrastructure-containers`, `5G` Docker | `512M-1G` | Current cert mount is fine. No need for large disk unless you add logs or many cert stores. |
| `harbor-stack` | Docker Compose | `infrastructure-containers`, `16G` rootfs | Docker on `infrastructure-containers`, `20G`; Harbor data on `storage-containers`, `100G` to start | `4G` | This is the heaviest platform service. `6G` appears overprovisioned for current idle use; `4G` is a better homelab starting point. |
| `apt-cacher-stack` | systemd | `infrastructure-containers`, `8G` rootfs | if cache remains on rootfs, keep `20-40G` total capacity; otherwise add explicit data mount on `storage-containers` | `512M` | Current stack still declares Docker storage even though the service is systemd. Better modeled as rootfs + optional cache mount. |
| `netbox-stack` | Docker Compose | `infrastructure-containers`, `8G` rootfs | `infrastructure-containers`, `16-32G` Docker | `2G` | Live production NetBox is using about `1.3G` RAM and less than `1G` Docker disk, so `2G` is a good baseline. |
| `ci-runner-01` | runner + Docker workload host | `infrastructure-containers`, `16-20G` rootfs | `storage-containers` or `infrastructure-containers`, `20-40G` Docker work area | `4G` | This depends on the jobs you run. `4G` is a sensible floor; bump only if actual jobs prove it tight. |

### Live production evidence that informed the recommendations

Observed on `pve`:

- existing `harbor-stack` CT `121` has `16G` rootfs, `20G` Docker storage,
  and `100G` Harbor data
- current Harbor usage is still small:
  - rootfs about `1.1G`
  - `/var/lib/docker` about `2.6G`
  - `/var/lib/harbor` about `647M`
- existing `netbox-stack` CT `119` has `8G` rootfs and `32G` Docker storage
- current NetBox usage is also small:
  - rootfs about `1.1G`
  - `/var/lib/docker` about `910M`
  - RAM in use around `1.3G` out of `3G`

This suggests:

- the current production Harbor disk shape is reasonable, but its RAM can
  likely be reduced
- NetBox can be comfortably smaller than its current production allocation
- the expensive part of production sizing is not today's actual dataset size,
  but allowing enough room for growth without needless fragmentation

### Recommended storage manifest policy for `pve`

Suggested first pass for `terraform/lxc/storage/pve.yaml`:

- `platform-default.rootfs_storage: infrastructure-containers`
- `platform-default.docker_storage: infrastructure-containers`
- `durable-default.storage: storage-containers`
- `local-template.storage: storage-template`

This yields a useful split:

- OS and normal app layers stay on the infrastructure pool
- larger persistent service data goes to the roomier storage pool
- templates come from the template pool already used on production

### Recommended follow-up refactor

The current Terraform module always creates a `/var/lib/docker` mount for every
stack, even when the service is not Docker-based.

That is reasonable for:

- `portainer-stack`
- `authentik-stack`
- `monitoring-stack`
- `proxy-stack`
- `harbor-stack`
- `netbox-stack`
- `ci-runner-01`

It is wasteful for:

- `step-ca-stack`
- `dns-stack`
- `apt-cacher-stack`

Recommendation:

- add an explicit stack capability flag so non-Docker platform stacks can skip
  the Docker mount entirely
- if that refactor is deferred, keep the allocated Docker disk for those
  systemd services small on production

## Proposed Execution Order

1. Create a working branch for infrastructure planning and parameterization.
2. Add `terraform/lxc/storage/pve.yaml`.
3. Rewrite `terraform/lxc/network/pve.yaml` to the VLAN model.
4. Add a production env overlay with `pve` address and gateway values.
5. Design and implement production credential control guardrails.
6. Remove stack-level `pve-test` node pins from the active platform stacks.
7. Validate `vmbr0` VLAN readiness and upstream switch/router behavior early.
8. Create or validate Proxmox SDN VLAN zones/VNets on `pve`.
9. Run storage and network preflight checks only.
10. Deploy a disposable or low-risk canary on `pve` and verify connectivity.
11. Build a per-service migration sheet for existing production workloads.
12. Choose a first real service for production trial deployment.

## Phase Plan

### Phase 0: Documentation And Control Design

Objective:

- establish the program structure and production safety posture before code
  changes broaden access

Outputs:

- this refactor directory
- branching model
- production credential control design

### Phase 1: Environment Modeling

Objective:

- make production a first-class environment in tracked manifests

Outputs:

- `storage/pve.yaml`
- rewritten `network/pve.yaml`
- production env overlay design

### Phase 2: Execution Guardrails

Objective:

- ensure production access cannot happen casually through existing dev paths

Outputs:

- separate production wrapper design or implementation
- approval rules
- read-only vs mutating command policy

### Phase 3: Stack Decoupling

Objective:

- remove `pve-test` hardcoding from stack definitions

Outputs:

- cleaned stack YAML files
- target-selection documentation

### Phase 4: Canary Validation

Objective:

- prove production networking and environment modeling on one low-risk target

Outputs:

- validated canary
- evidence of gateway, DNS, and cross-segment reachability

### Phase 5: Incremental Service Migration

Objective:

- move real services deliberately and one at a time

Outputs:

- migration order
- cutover checklist per service
- rollback rules

## Validation Gates Before First Production Apply

- `terraform/lxc/storage/pve.yaml` exists and passes storage contract checks
- `terraform/lxc/network/pve.yaml` matches the active stack zone names
- production bridge/VLAN setup is in place and validated
- switch trunk and MikroTik VLAN gateway config are in place and validated
- SDN zones/VNets exist and match the manifest
- chosen IP ranges are routable and not in use
- chosen VMIDs are free
- service cutover ownership is decided for existing `harbor-stack`,
  `netbox-stack`, and management-plane workloads
- production credential controls are in place and tested in read-only mode first
- the chosen canary path has been validated before any higher-value service move

## Documentation Locations

Current documentation is split across a few files:

- Primary production migration plan:
  [docs/plan/pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/plan/pve-production-readiness.md:1)
- Canonical logical network design:
  [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)
- Current active dev network intent and VLAN details:
  [terraform/lxc/network/pve-test.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/network/pve-test.yaml:1)
- Future production network intent to be rewritten:
  [terraform/lxc/network/pve.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/network/pve.yaml:1)

Recommended source-of-truth split:

- keep migration strategy and rollout sequencing in
  `docs/plan/pve-production-readiness.md`
- keep the environment-agnostic network model in `docs/design/network.md`
- keep environment-specific attachment details in `terraform/lxc/network/*.yaml`

## Recommended Next Changes In Repo

The first repo changes to make next are:

1. Move productionization docs under `docs/productionize-refactor/`
2. Define the production credential control design
3. Add `terraform/lxc/storage/pve.yaml`
4. Replace the current `terraform/lxc/network/pve.yaml` with a VLAN-based
   production intent aligned to the active design
5. Introduce a production env overlay for the `LAB_IP_*`, `LAB_GW_*`, and
   `LAB_SUBNET_*` variables
6. Remove hardcoded `proxmox_node: pve-test` from the active platform stacks

## Open Decisions

- Should production use the same segmented addressing model as the current dev
  design, or a different VLAN/IP plan?
- How should production secrets be separated from the current `with-secrets`
  flow?
- What should the approval mechanism be for production mutations initiated from
  an AI-operated environment?
- Should existing production services like `harbor-stack` and `netbox-stack`
  be replaced in parallel or adopted/rebuilt in place?
- Do we want to close the SDN VLAN automation gap before any production trial,
  or explicitly accept a manual prerequisite for the first pass?
