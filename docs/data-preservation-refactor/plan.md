# Data Preservation Execution Plan

## Goal

Make selected stacks capable of preserving their durable data across teardown
and redeploy by remodeling storage so the data lifecycle can survive LXC
replacement.

This plan is intentionally optional-path oriented:

- scratch rebuild must remain possible
- preserved rebuild must be opt-in
- `pve-test` must prove the pattern before `pve` uses it

## Preconditions

Start this work only after baseline convergence is complete enough that
`pve-test` is a trustworthy proving ground for stack lifecycle work.

See [docs/baseline-merge/plan.md](/home/steve/git/proxmox-homelab/docs/baseline-merge/plan.md:1).

## Current Constraints

Today, most durable stack data is destroyed with the LXC because:

- the LXC rootfs is Terraform-owned
- the Docker storage disk is Terraform-owned
- any extra mount is currently attached as part of the same container lifecycle

That means "storage already lives on a separate path" is not enough by itself.
The mount must also be made lifecycle-independent.

## Phase 0: Preservation Contract

Before touching any stack, define the contract for what "preserve on rebuild"
means.

### Required contract questions

- what exact path is durable for this stack?
- does the path live on rootfs, Docker storage, or an extra mount today?
- can that data be reattached to a replacement container without mutation?
- does the stack still support a full scratch rebuild?
- what operator input chooses between scratch rebuild and preserved rebuild?

### Required outputs

- a documented preserved-data contract for each candidate stack
- one implementation pattern for "existing extra mount"
- one implementation pattern for "data currently trapped inside Docker volumes"

## Phase 1: Candidate Inventory

Use the current repo layout to classify stacks by preservation difficulty.

### Tier 1: Best first targets

| Stack | Current durable path | Current state | Proposed remodel | Why first |
|---|---|---|---|---|
| `harbor-stack` | `/var/lib/harbor` | Already on `extra_mount_path`, but mount dies with CT | Decouple Harbor extra mount lifecycle from LXC lifecycle | Highest value, cleanest shape |
| `proxy-stack` | `/opt/proxy-stack/certs` | Already on `extra_mount_path`, but mount dies with CT | Decouple cert mount lifecycle from LXC lifecycle | Small blast radius, proves pattern |
| `portainer-stack` | `/var/lib/portainer` | Lives on LXC filesystem and is bind-mounted into container | Add dedicated durable mount and bind it to `/data` | Small bounded dataset |

### Tier 2: Solvable after the first pattern

| Stack | Current durable path | Main challenge | Proposed direction |
|---|---|---|---|
| `authentik-stack` | Docker volumes on `docker_storage` | Postgres and media are not isolated onto a preserved host path | Externalize key volumes onto explicit durable paths |
| `monitoring-stack` | `vm-data`, `grafana-data`, `loki-data` Docker volumes | Multiple services and volumes share the Docker disk | Move each durable volume to an explicit mounted path |
| `netbox-stack` | DB, Redis, NetBox data in Docker volumes | Multiple interdependent services and data types | Split database, Redis, and app data onto preserved mounts |

### Tier 3: Low-value or special

| Stack | Status |
|---|---|
| `apt-cacher-stack` | Easy but low-value; preserve later if desired |
| `ci-runner-01` | Easy but low-value; preserve only if Docker cache matters |
| `step-ca-stack` | Special case because preserving data means preserving CA identity |
| `dns-stack` | Not worth leading with; mostly regenerate-from-source state |

## Phase 2: Implementation Pattern A

Build the first preservation pattern around stacks that already have an extra
mount in `stack.yaml`.

### Candidate stacks

- `harbor-stack`
- `proxy-stack`

### Pattern requirements

- the durable mount has its own lifecycle identity
- LXC replacement can reattach the preserved mount
- Terraform and/or wrapper logic can distinguish:
  - scratch destroy
  - preserve-and-rebuild
- mount ownership and permissions are restored predictably

### Validation target

Start with `harbor-stack`, then repeat on `proxy-stack`.

## Phase 3: Implementation Pattern B

Add the second pattern for stacks whose durable state currently lives on the
LXC filesystem and is bind-mounted into a container.

### Candidate stack

- `portainer-stack`

### Proposed remodel

- add a dedicated durable mount for `/var/lib/portainer`
- keep compose config under `/opt/portainer`
- preserve only the Portainer data directory, not the whole LXC rootfs

### Why this is separate from Pattern A

The path is already cleanly bounded, but there is no existing extra mount to
reuse. That makes this the best "introduce a durable mount" exercise after the
existing-extra-mount pattern is proven.

## Phase 4: Implementation Pattern C

Design the later pattern for Docker-volume-heavy stacks.

### Candidate stacks

- `authentik-stack`
- `monitoring-stack`
- `netbox-stack`

### Common design problem

The durable data is inside Docker-managed volumes on the Terraform-managed
Docker storage disk. Preserving it requires one of these choices:

1. move each important volume to a bind-mounted host path on a durable mount
2. preserve the Docker storage disk itself independently of the LXC

The first option is likely cleaner and more explicit.

### Design questions to answer before implementation

- which service volumes are actually worth preserving?
- should DB and app data live on one preserved mount or multiple?
- what initialization logic must detect and adopt existing data?
- what permissions or UID/GID assumptions must be preserved across rebuilds?

## Phase 5: Special Case Decision For `step-ca`

Do not treat `step-ca-stack` as an early implementation target.

If we later support preservation there, the design must explicitly cover:

- preservation of `/etc/step-ca`
- trust continuity implications
- backup of CA material before any remodel test
- a documented recovery procedure if the reattached CA state fails to start

This should be treated as PKI lifecycle work, not just storage remodeling.

## Validation Model

Every preservation-capable stack must pass two modes on `pve-test`.

### Mode 1: Scratch rebuild

- destroy stack resources normally
- redeploy from source
- confirm service is healthy with fresh state

### Mode 2: Preserve-and-rebuild

- snapshot or otherwise protect the durable data first
- destroy only the disposable LXC lifecycle
- reattach the preserved data mount
- redeploy the stack
- confirm the expected user data or service state is still present

### Minimum evidence to capture

- mount inventory before destroy
- mount inventory after reattach
- service health after redeploy
- application-specific proof of preserved state

## Rollback Model

Each implementation phase must define how to recover if the preserved-data path
fails:

- fall back to scratch rebuild
- restore from backup or snapshot
- detach the preserved mount from the failed replacement CT

If recovery depends on undocumented operator memory, the stack is not ready for
promotion.

## Suggested Execution Order

1. finish baseline convergence
2. implement preservation contract and operator-facing mode selection
3. prove Pattern A on `harbor-stack`
4. reuse Pattern A on `proxy-stack`
5. prove Pattern B on `portainer-stack`
6. then decide whether Authentik, Monitoring, and NetBox share one Pattern C
   implementation or need separate designs

## Acceptance Criteria

This plan is successful when:

- the repo has an explicit preserved-data contract
- at least one stack can rebuild with preserved data on `pve-test`
- the operator can choose scratch rebuild versus preserved rebuild
- durable and disposable storage lifecycles are clearly separated in code
- the proven `pve-test` pattern can be used as the basis for later `pve`
  rollout
