# Storage Refactor

## Purpose

Improve the `terraform/lxc` storage model so stack-declared storage layout
changes for Docker-on-LXC are explicit, predictable, and low-risk, even when
Terraform is not the day-2 mutation engine for every backend.

This project is about the gap between what Proxmox LXC can safely do and what
the current Terraform/provider contract safely models.

The main operator workflows in scope are:

- grow the `/var/lib/docker` mount on an existing LXC
- grow an existing persistent extra mount on an LXC that already uses the
  module's one optional extra mount
- attach one more persistent filesystem to an existing LXC that does not
  already consume the module's optional extra mount
- detect and classify storage edits that remain replacement-sensitive before
  apply

## Scope

### In scope

- the current LXC module shape:
  - one root filesystem disk
  - one `/var/lib/docker` LXC `mount_point`
  - one optional extra LXC `mount_point`
- provider-aware guardrails for grow-only and additive mount changes
- explicit logical identity and backup policy for persistent mounts
- detection of path masking, shrink attempts, and replacement-sensitive edits
- development and mutation testing on a tracked dedicated test LXC stack named
  `test-storage` that uses the same module path, storage manifest resolution,
  inventory path, and normal stack fields as the general case
- representative non-destructive validation against actual infrastructure stack
  shapes after the dedicated test LXC proves the primitive
- source and live validation for storage safety
- operator docs for safe storage mutation workflows

### Out of scope

- PBS restore drills or restore testing
- moving application data to different datasets just because it exists today
- redesigning every stack around per-app datasets
- preserving or reattaching the same live volume through every replacement event
- broad service-by-service data migration waves
- adding a second optional extra mount to stacks that already use
  `extra_mount_*` under the current module shape
- repo-wide conversion of unchanged real stacks to a new storage declaration
  format when compatibility support is sufficient

## Why The Current Model Is Risky

The risk is mostly in the Terraform/provider modeling layer, not in Proxmox LXC
itself.

Relevant current facts:

- Proxmox LXC and Docker-on-LXC can support "grow this disk" and "attach one
  more filesystem" as normal lifecycle operations.
- In this repo, `/var/lib/docker` is an LXC `mount_point`, and optional app
  mounts are also `mount_point` entries.
- With the currently locked provider version, root disk growth is supported in
  place, and CPU/memory changes are generally in-place or reboot-type changes.
- LXC `mount_point` edits are still the dangerous class because they remain
  replacement-sensitive in the provider.

That means the primary problem to solve is not "can Proxmox do this?" It is
"how do we model and validate these storage changes so Terraform does not turn
normal lifecycle edits into surprising replacement risk?"

## Required Outcomes

The refactor is done only when all of the following are true:

- growing the Docker data mount is a documented, tested, grow-only workflow
  through the approved backend-specific control plane
- growing an existing persistent extra mount is a documented, tested, grow-only
  workflow through the approved backend-specific control plane
- attaching an additional persistent filesystem is a documented, tested
  workflow for the current module shape
- every persistent mount has explicit:
  - logical identity
  - mount path
  - backend selection intent
  - size intent
  - backup intent
  - backup handling status:
    - explicit in Terraform
    - explicit unsupported exception with reason
- validation distinguishes:
  - safe in-place mutation
  - reboot-required mutation
  - replacement-sensitive mutation
  - blocked mutation
- mutation classification comes from targeted machine-readable Terraform plan
  output for the stack under test, plus a field-to-class mapping proven in the
  capability phase, with manifest validation as a supporting input rather than
  the source of truth for provider actions
- shrink attempts and path-masking changes are caught before apply
- backup handling for persistent mounts is explicit in code, docs, and
  validation
- the primitive is proven on a dedicated test LXC before representative checks
  are run against interconnected infrastructure stacks
- unchanged real stacks can stay on compatibility paths unless they are needed
  for representative validation or an intentional storage change
- the contract remains environment-scoped so `pve-test` is first without
  hard-coding the design to that one environment

## Design Position

The storage refactor should follow these positions unless explicitly changed
later with approval:

- Do not expand this into a backup/restore project.
- Do not expand this into a storage migration project.
- Keep Docker-managed volumes supported.
- Keep the current module shape unless a small targeted change is needed for
  safety.
- Under the current module shape, the additive mount workflow means
  "no extra mount" to "one extra mount". Adding a second extra mount is out of
  scope unless explicitly approved later.
- Existing Docker mounts and existing extra mounts are both in scope for
  grow-only resize workflows.
- Prefer grow-only mutation rules for persistent mounts.
- Make replacement-sensitive storage edits loud, explicit, and reviewable.
- Treat stable volume identity as manifest and validation clarity; this project
  does not require same-volume reattachment across every replacement event.
- Use a dedicated test LXC as the primary mutation-development target. Do not
  use interconnected infrastructure stacks as the first place to prove storage
  mutation behavior.
- `test-storage` should stay on a normal SDN/VLAN-backed zone, preferably
  `build_seg`, rather than the legacy `lan` bridge path. Independence should
  come from avoiding infrastructure-service dependencies, not from bypassing
  the normal zone/VLAN attachment model.
- Keep unchanged real stacks on compatibility/default paths unless the plan
  explicitly needs them for representative validation.
- Keep backend capability differences visible in the contract and docs.
- Keep backup intent explicit and operator-controlled for every persistent
  mount. `backup_policy` is not informational metadata; it is part of the
  desired storage contract.
- Avoid redesigning non-Docker stacks solely to remove an otherwise-unused
  `/var/lib/docker` mount unless that directly improves safety.
- Use disposable `pve-test` validation to prove the workflows; preserving
  current `pve-test` state or proving PBS restore is not part of this project.

## Backup Policy Contract

Persistent mounts now use an explicit `backup_policy` field in stack intent.

Supported values:

- `include`: the mount should be included in container backup handling, and the
  Terraform path renders `mount_point.backup = true`
- `exclude`: the mount should be excluded from container backup handling, and
  the Terraform path renders `mount_point.backup = false`

This applies independently to both supported persistent mount types:

- `docker_mount.backup_policy`
- `extra_mount.backup_policy`

Current rules:

- `backup_policy` is required logically for every persistent mount, even when
  older stack authoring still relies on validator defaults for compatibility
- the allowed values are only `include` and `exclude`
- backup intent is about Proxmox mount-point inclusion policy only; it is not a
  restore guarantee and does not expand this refactor into PBS restore testing
- when the repo uses an operational first-attach workflow for an extra mount,
  the host-side `pct set` command must honor the same `backup_policy` value so
  live state and Terraform intent remain aligned

## Approved Day-2 Resize Model

The current provider results mean the repo has to separate desired state from
the mutation engine for some storage edits.

- `stack.yaml` remains the source of truth for desired mount sizes and other
  storage intent.
- Rootfs growth can stay Terraform/OpenTofu-managed where the provider proves
  in-place behavior.
- Non-rootfs mounts are created by Terraform, but grow-only day-2 size
  changes may be performed operationally through Proxmox-native resize
  commands executed by Ansible or an equivalent host-side workflow when that
  backend/profile combination is explicitly supported by the repo contract.
- The approved sequence for an operational non-rootfs grow is:
  1. update the desired size in `stack.yaml`
  2. run the operational resize on the Proxmox host
  3. verify the new size in Proxmox and in the guest
  4. run a fresh `terragrunt plan` and expect a no-op
- Direct Terraform/OpenTofu apply of a non-rootfs mount-size increase remains
  unsafe under the current provider because the provider still models that
  change as replacement-sensitive.
- Sequencing matters. If Terraform/OpenTofu reconciles after `stack.yaml` is
  changed but before the operational resize happens, it will still plan the
  unsafe replacement-sensitive path.
- This pattern generalizes to supported non-rootfs mounts later, as long as
  the contract gives each mount a stable logical identity, keeps the workflow
  grow-only, and records backend-specific limits honestly.

### Current implementation status

The repo now contains a supported operational workflow for the current
non-rootfs mount cases under the existing module shape:

- Docker mount growth at `/var/lib/docker`
- first extra-mount attachment from a Docker-only baseline to one declared
  `extra_mount`
- growth of an already-existing extra mount

The dedicated proof targets remain `test-storage` for Docker-only to
first-extra-mount transition work and `test-storage-extra` for existing
extra-mount regression.

- `terraform/lxc/stacks/test-storage/stack.yaml` declares Docker mount intent
  in `docker_mount`
- `terraform/lxc/validate-storage-contract.py` enforces the current Docker
  policy: operational control plane, grow-only mutation policy,
  `/var/lib/docker`, and only backend/profile combinations the repo currently
  supports for that operational path
- `scripts/resize-lxc-mount.sh` is the narrow repo-native entrypoint for both
  supported non-rootfs growth and first-extra-mount attachment
- `terraform/lxc/ansible/playbooks/resize-lxc-mount.yml` performs the host-side
  `pct` mutation, verifies `pct config`, and verifies guest-visible size inside
  the guest
- `terraform/lxc/modules/lxc-docker-host/main.tf` now renders explicit Proxmox
  mount-point `backup` fields for both Docker and extra mounts from stack
  `backup_policy` intent

Dedicated additive-attach validation is now established for:

- `test-storage` on `infrastructure-containers` (`zfs`) for the transition from
  Docker-only to one declared extra mount at `/srv/test-extra-attach`

That live proof showed all of the following:

- direct Terraform/OpenTofu reconciliation of the new `extra_mount` still plans
  the provider's replacement-sensitive path and must not be applied for this
  transition
- the approved operational attach path can allocate and attach the first extra
  mount live through `pct set`
- the attach workflow blocks mount-over-existing-data by default unless the
  operator explicitly overrides that safety check
- after the operational attach, the module-scoped
  `terragrunt plan -target=module.lxc -no-color` no longer shows storage drift
  for the new mount

Representative Docker-mount validation is now established for:

- `proxy-stack` on `infrastructure-containers` (`zfs`)
- `harbor-stack` on `infrastructure-containers` (`zfs`)
- `authentik-stack` on `local-lvm` (`lvm-thin`)
- `monitoring-stack` on `local-lvm` (`lvm-thin`)
- `netbox-stack` on `local-lvm` (`lvm-thin`)
- `portainer-stack` on `local-lvm` (`lvm-thin`)

### Current position

What is now proved:

- provider-managed non-rootfs mount-size growth remains
  `replacement-sensitive`
- operational Docker-mount growth at `/var/lib/docker` is a working day-2
  path when the stack uses a backend/profile combination the repo currently
  supports
- first-extra-mount attachment is proved as an operational workflow for the
  current `platform-zfs` + `durable-zfs` dedicated proof path
- operational existing-extra-mount growth is proved for the current
  ZFS-backed workflow

What is not yet proved:

- explicit backup-intent completion for every persistent mount
- final preflight and guardrail integration across the whole refactor plan

Current next target:

- explicit backup intent and backup exception handling for persistent mounts is
  the next substantive gap
- after that, the remaining work is guardrail and preflight consolidation
  around the now-proved operational workflows

Current approved operator sequence for Docker mount growth:

1. update `docker_mount.size` and the compatibility field
   `docker_storage_size` in `stack.yaml`
2. run `./with-secrets bash -lc './scripts/resize-lxc-mount.sh --stack test-storage'`
3. verify the playbook output for `pct config` and guest-visible size
4. run `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt plan -no-color'`
   and expect `No changes`

This does not mean the whole refactor is done. The primary remaining gaps are:

- explicit backup intent and backup exception handling
- final guardrail and preflight consolidation across the full plan

Current implementation note for existing live stacks:

- older LXCs created before explicit backup-field rendering can still have live
  mount-point `backup=0`; after this change, stacks that declare
  `backup_policy: include` will plan an in-place `backup = false -> true`
  update until they are reconciled
- `backup_policy: exclude` is now the explicit way to keep `mount_point.backup`
  at `false`

Current approved operator sequence for first extra-mount attachment:

1. update `stack.yaml` to declare the first `extra_mount` and keep the legacy
  compatibility fields aligned while both exist
2. run a targeted Terraform/OpenTofu plan only to classify the direct provider
  path; if it shows replacement-sensitive storage behavior, do not apply it
3. run
  `./with-secrets bash -lc './scripts/resize-lxc-mount.sh --stack test-storage --mount-path /srv/test-extra-attach'`
  or the equivalent target stack/mount path
4. verify the playbook output for `pct config` and guest-visible filesystem
  size, then write a sentinel file on the new mount
5. run a fresh module-scoped plan such as
  `./with-secrets bash -lc 'cd terraform/lxc/stacks/test-storage && terragrunt plan -target=module.lxc -no-color'`
  and confirm no storage-related drift remains for the attached mount

## Current Risk Map

These are the storage risks this project should address:

- `mount_point` edits are replacement-sensitive in the provider
- backup inclusion for persistent mounts is not explicit today
- requested storage is identified mostly by backend/profile intent rather than a
  stable logical volume identity
- adding a mount over a path that already has data can mask the old files
- one large `/var/lib/docker` mount gives each LXC a large shared blast radius
- backend behaviors differ across `local-lvm`, directory, ZFS, bind mounts, and
  similar backends
- unprivileged LXC recovery and host-side inspection can be awkward because of
  UID/GID mapping

## Delivery Rules

This remains infrastructure work and should follow the repo branch model:

1. Implementation work happens on a short-lived `work/*` branch cut from
   `baseline/teardown-validated`.
2. Mutation development and testing happen on a dedicated disposable test LXC
   in `pve-test`, not on interconnected infrastructure stacks.
   This test LXC should be the tracked stack `test-storage`, kept on a normal
   SDN/VLAN-backed zone, but excluded from broad teardown/redeploy gates unless
   explicitly enabled for a validation pass.
3. Promotion goes back to `baseline/teardown-validated` after the required repo
   gates pass.
4. The resulting contract must stay environment-scoped so a later `pve` rollout
   can use it without redesign.
5. Stack changes are in scope only when they are needed to make storage intent,
   backup intent, or mutation safety explicit.
6. Real infrastructure stacks should only be used for representative
   non-destructive validation unless a later explicitly approved phase expands
   that scope.

## Plan Document

- [Execution Plan](plan.md)
- [Capability Matrix](capability-matrix.md)
- [First Extra-Mount Attach Tests](extra-mount-attach-tests.md)
- [Docker Mount Resize Tests](docker-mount-resize-tests.md)
- [Phase 0 Audit Notes](phase-0-audit-notes.md)
