# Storage Refactor Execution Plan

## Goal

Refactor the `terraform/lxc` platform so stack-declared LXC storage layout
changes for Docker-on-LXC are modeled safely and explicitly.

The refactor must allow us to:

- grow the `/var/lib/docker` mount safely through the approved backend-specific
  mutation engine
- grow an existing persistent extra mount safely through the approved
  backend-specific mutation engine
- attach an additional persistent filesystem safely for stacks that do not
  already consume the module's optional extra mount
- make persistent mount intent explicit and reviewable
- make backup inclusion explicit for persistent mounts
- detect and classify replacement-sensitive storage edits before apply

This is not a backup/restore program and not a data-migration program.

## Non-Negotiable Constraints

1. This is infrastructure work and must be implemented on a `work/*` branch.
2. Validation happens on disposable `pve-test`.
3. The resulting contract must stay environment-scoped so it can later be
   applied to `pve` without redesign.
4. The project must not expand into PBS restore testing without explicit
   approval.
5. The project must not expand into service-by-service data migration without
   explicit approval.
6. The project must keep Docker-managed volume semantics supported.
7. Mutation development and mutation applies happen first on a dedicated
   disposable test LXC that uses the same general module shape as normal
   stacks.
   That test LXC should be the tracked stack `test-storage` under
   `terraform/lxc/stacks/test-storage/` or a clearly equivalent normal-stack
   path.
8. Actual infrastructure stacks are for representative non-destructive
   validation unless explicit approval expands scope later.
9. Unchanged real stacks should remain on compatibility/default storage
   declarations unless a phase explicitly needs them for representative
   validation or an intentional storage change.
10. Every phase must have a test gate before the next phase starts.
11. The final implementation must satisfy repo merge requirements, including the
   standard preflight and security scans.

## Current Technical Facts

### Storage behavior in the repo

- the LXC module provisions:
  - one root filesystem disk
  - one `mount_point` at `/var/lib/docker`
  - zero or one optional extra `mount_point`
- the root module resolves storage backends from
  `terraform/lxc/storage/<node>.yaml`
- current `pve-test` defaults resolve runtime storage to `local-lvm` and
  template storage to `local`
- only `terraform/lxc/storage/pve-test.yaml` exists today; the new contract
  must still leave room for a future `terraform/lxc/storage/pve.yaml`

### Provider behavior that matters here

- the repo currently constrains the `bpg/proxmox` provider with `~> 0.78`, and
  the OpenTofu lockfile currently resolves that provider to `0.106.0`
- root disk growth is supported in place
- CPU and memory changes are in-place or reboot-type mutations
- LXC `mount_point` edits remain replacement-sensitive in the provider
- on the ZFS-backed `infrastructure-containers` pool, Proxmox-native
  `pct resize` for the Docker mount works live and the guest sees the new size
  immediately
- after that operational resize, a normal `terragrunt plan` returns no changes
  once `stack.yaml` is updated to the same desired size
- if `stack.yaml` is changed first and Terraform/OpenTofu reconciles before the
  operational resize happens, the provider still plans the
  replacement-sensitive path

That last point is the main reason this refactor exists.

### Current stack shapes that matter

| Stack shape | Examples | Why it matters |
| --- | --- | --- |
| Docker mount only | `authentik-stack`, `netbox-stack`, `monitoring-stack`, `portainer-stack`, `apt-cacher-stack` | proves grow-only Docker mount workflow |
| Docker mount plus extra mount | `harbor-stack`, `proxy-stack` | proves additive mount workflow and backup intent |
| Mostly direct/rootfs service | `step-ca-stack`, `dns-stack` | should not force unnecessary redesign, but still needs clear storage safety rules |

## Design Rules

The implementation should follow these rules:

1. Focus on persistent mount safety, not on redesigning application data layout.
2. Persistent mounts must have explicit logical identity in manifests,
   validation output, and operator docs.
3. Logical identity does not have to mean same-volume reattachment across every
   replacement event.
4. Docker-managed volumes remain supported; `/var/lib/docker` is a first-class
   persistent mount in this project.
5. Persistent mount growth is grow-only unless later work explicitly adds a safe
   shrink workflow.
6. Under the current module shape, additive mount support means transitioning a
   stack from no `extra_mount_*` to one `extra_mount_*`.
7. Requests that would require a second optional extra mount must be blocked or
   called out as out of scope under the current module shape.
8. Adding a new mount over a path that already contains data must be blocked or
   require an explicit safety override.
9. Backup inclusion for persistent mounts must be explicit.
10. Mutation classification must use machine-readable Terraform plan output for
    the targeted stack as the authoritative source of provider action class.
11. The first classifier version only needs to cover the current storage fields
    and transitions used by this project:
    - rootfs size increase
    - Docker mount size increase
    - existing extra mount size increase
    - first extra mount introduction
    - mount path change
    - mount backend/profile change
    - mount removal
    - second extra mount request
12. Classifier inputs must be narrow enough that storage changes can be judged
    without unrelated stack edits obscuring the result. Mixed-purpose plans
    should be isolated or blocked.
13. If the plan classifier cannot determine storage mutation safety confidently,
    the change is blocked.
14. Validation must distinguish:
   - safe in-place mutation
   - reboot-required mutation
   - replacement-sensitive mutation
   - blocked mutation
15. The classifier mapping must be explicit:
    - plan JSON showing container replacement for a storage-driven diff maps to
      `replacement-sensitive`
    - path change, backend/profile change, mount removal, or second extra mount
      request maps to `blocked` unless a later approved phase changes scope
    - grow-only size changes and first extra-mount introduction map to the class
      proven for that exact field transition in the Phase 0 capability matrix
    - ambiguous or unclassified storage diffs map to `blocked`
16. Backend capability differences must stay visible in docs and validation.
17. Backup policy must resolve to one of:
    - explicit Terraform-managed behavior
    - explicit documented unsupported exception with reason
18. Direct/rootfs service stacks must remain no-op safe under the new contract.
19. This plan does not require PBS restore drills, stack-by-stack restore
    proofs, or broad data migration waves.
20. `stack.yaml` remains the source of truth for desired mount sizes, even when
    Terraform/OpenTofu is not the day-2 mutation engine for that field.
21. For supported non-rootfs mounts, the approved grow-only day-2 workflow is:
    update desired size in `stack.yaml`, execute the resize operationally on
    the Proxmox host, verify the live result, then confirm a no-op
    `terragrunt plan`.
22. Direct Terraform/OpenTofu apply of non-rootfs mount-size growth remains
    blocked under the current provider unless a later validated provider change
    proves an in-place path.
23. The same operational grow-only pattern should remain extensible to multiple
    non-rootfs mounts later, provided the contract gives each mount a stable
    logical identity, mutation policy, and backend-specific support rules.

### Phase 0 implementation status

The initial implementation slice started on `test-storage` and now has live
representative proof for Docker-mount growth across the current `pve-test`
fleet.

- stack intent is declared in `docker_mount`
- the storage contract validator blocks invalid or unsupported operational
  declarations for this slice and keeps backend-specific support explicit
- the operational mutation engine is
  `terraform/lxc/ansible/playbooks/resize-lxc-mount.yml`
- the repo-native entrypoint is `scripts/resize-lxc-mount.sh`
- the dedicated proof target remains `terraform/lxc/stacks/test-storage/`
- representative Docker-mount proof now exists on:
  - `proxy-stack`
  - `harbor-stack`
  - `authentik-stack`
  - `monitoring-stack`
  - `netbox-stack`
  - `portainer-stack`

This does not yet complete the full refactor plan. The current proven slice is
the Docker mount at `/var/lib/docker`, the ZFS-backed first-extra-mount attach
workflow on `test-storage`, and the already-documented ZFS-backed
existing-extra-mount workflow. Remaining planned work still includes
backup-intent completion and final guardrail integration.

### Current phase position

- Phase 0 capability work is materially complete for the currently tested
  backends and workflows captured in the capability matrix.
- Phase 1 contract work is partially implemented in live code and stack
  authoring, but the broader refactor is not complete just because the Docker
  operational path is proved.
- Phase 2 is partially complete:
  - Docker mount growth is proved through the operational workflow.
  - First extra-mount introduction is now proved as an operational attach
    workflow on the dedicated `test-storage` target.
  - Existing extra-mount growth is proved for the current ZFS-backed path.
- Phases 3 through 5 remain open as written: backup intent, full guardrail
  integration, and final validation/promotion are not finished.

### Current next target

The next substantive storage-refactor target should be explicit backup intent
for persistent mounts, followed by the remaining guardrail consolidation.

That next pass should complete all of the following:

- each persistent mount resolves to an explicit backup answer
- the now-proved operational attach and grow workflows are reflected honestly in
  validator output and operator docs
- plan-classifier and preflight integration distinguish storage risk from
  unrelated stack drift cleanly enough for normal workflow use

## Target Contract

The refactor should evolve the current contract so persistent mounts are
explicitly described, even if the underlying module still centers on one Docker
mount plus one optional extra mount.

Candidate stack-level direction:

```yaml
storage_profile: platform-default

docker_mount:
  logical_name: docker-data
  size: 32G
  backup_policy: include
  resize_control_plane: operational

extra_mount:
  logical_name: harbor-data
  path: /var/lib/harbor
  size: 100G
  profile: durable-default
  backup_policy: include
  resize_control_plane: operational
```

Backup-policy semantics for the current implementation are explicit:

- `backup_policy: include` maps to Terraform-rendered `mount_point.backup = true`
- `backup_policy: exclude` maps to Terraform-rendered `mount_point.backup = false`
- the currently supported values are exactly `include` and `exclude`
- if a backend or workflow later cannot support explicit Terraform-managed
  backup behavior, that case must be represented as an explicit documented
  exception rather than falling back to an implicit default

The exact schema can change during implementation, but the design rules should
hold:

- the stack declares mount intent explicitly
- the environment decides how that intent maps to concrete backends
- validation can reason about identity, size, backup intent, and mutation class
- the contract can distinguish desired state from the approved day-2 resize
  control plane for that mount
- the contract stays honest about the current module limit of one optional extra
  mount
- compatibility/default paths remain available for unchanged real stacks during
  this refactor

## Execution Workflow

Use the storage-refactor docs as a manager-controlled phase workflow rather than
as an invitation for broad free-form implementation.

### Session roles

- one session may act as architect / planner / manager for the refactor
- implementation passes may be delegated to GitHub Copilot or another coding
  agent
- the manager session decides whether the next pass is implementation,
  validation, final gate, or promotion work

### Prompt sequence

1. Start a new implementation branch/session with
   `docs/storage-refactor/copilot-init-prompt.md`.
2. Delegate only the earliest unfinished phase.
3. If that phase is incomplete but still the right next target, continue with
   `docs/storage-refactor/copilot-followup-prompt.md`.
4. Before accepting a phase as complete, run a separate validation pass with
   `docs/storage-refactor/copilot-validation-prompt.md`.
5. If delegated passes start churning without new material evidence, reset with
   `docs/storage-refactor/copilot-execution-recovery-prompt.md`.
6. Use `docs/storage-refactor/copilot-gate-prompt.md` only after implementation
   phases are complete and the branch is ready for final gate work.
7. Use `docs/storage-refactor/copilot-promotion-prompt.md` only after the final
   gate succeeds or is explicitly accepted.

### Delegation rule

- delegate one phase-sized task at a time
- do not ask an implementation pass to span multiple unfinished phases
- do not advance the branch to the next phase until the current phase satisfies
  its exit criteria and the phase completion checklist

### Process Churn Guardrails

- The purpose of delegated passes is to produce material execution progress,
  not repeated prompt refinement, branch-state summaries, or manager-facing
  option lists.
- Every delegated pass must do at least one of the following before handing
  back:
  - run a required validator, scan, or proof command from the current phase
  - make a durable code or document change required by the current phase
  - run a targeted provider-backed plan/apply/proof step on the current phase's
    disposable validation target
- A pass must not stop only because there are multiple reasonable next actions.
  If the plan already makes one path the default, take that path.
- A pass must not hand back "use follow-up next" unless it also reports a
  concrete blocker or a concrete newly completed phase deliverable from this
  pass.
- If a validator fails because of an obvious repo-local deficiency that can be
  repaired safely from repo context, repair it and rerun the validator in the
  same pass rather than asking the manager to choose between repair options.
- If two consecutive delegated passes produce only review churn, prompt edits,
  or hand-back wording changes without new phase evidence, live validation, or
  durable implementation changes, the next pass must be execution-only:
  either perform the pending commands/tests/applies or stop with an exact
  blocker after attempting them.
- The manager session should treat repeated "partial, continue" loops without
  new material evidence as a process failure and reset the next pass to a
  narrow execution brief.

### Required hand-back

Every delegated pass should end with a structured hand-back that includes:

- current phase and whether it is complete, partial, or blocked
- files changed
- tests and validations run
- tests not run, if any
- blockers, deviations, or assumptions
- the exact recommended next pass:
  - follow-up
  - validation
  - gate
  - promotion

### Manager rule

- the manager session is responsible for checking the hand-back against this
  plan before delegating the next pass
- if a delegated pass broadens scope beyond this plan, the manager session
  should stop and realign before work continues
- if a delegated pass returns only narration, option lists, or prompt/policy
  edits without new material phase evidence, the manager session should not
  request another generic follow-up; it should issue a narrow execution-only
  brief or stop the loop

## Phase Plan

## Phase 0: Capability Check And Storage Audit

### Objective

Confirm exactly which storage mutations are safe, which are risky, and which
need explicit blocking in the current provider/module combination.

### Work

1. Create a storage mutation matrix for the current provider and host:
   - grow rootfs
   - change CPU
   - change memory
   - grow Docker mount
   - add an extra mount
   - edit an existing mount path
   - edit an existing mount size
   - change an existing mount backend/profile
2. Confirm how the current provider/module handles persistent mount backup
   behavior and what must be set explicitly in code.
3. Audit current stack usage:
   - which stacks use only `/var/lib/docker`
   - which stacks also use `extra_mount_*`
   - which paths already contain important data
   - which stacks are representative validation targets for each storage shape
4. Document path-masking risk cases for the current stacks.
5. Establish one dedicated storage-validation LXC as the primary mutation test
   target.
   - It must be the tracked stack `test-storage`.
   - It must live under `terraform/lxc/stacks/test-storage/` or an equivalent
     normal-stack path.
   - It must use the same module path, storage manifest resolution, inventory
     generation path, and Docker mount pattern as the general case.
   - It must not gain special-case code paths that the real stacks do not use.
   - It should use ordinary stack fields such as `storage_profile`,
     `docker_storage_size`, and optional `extra_mount_*`, rather than hidden
     test-only module inputs.
   - It should use a normal SDN/VLAN-backed `network.zone`, preferably
     `build_seg`, rather than the legacy `lan` bridge path, so storage work does
     not drift away from the general stack shape.
   - It must remain operationally independent of the infrastructure stacks:
     no required Harbor, apt-cacher, Portainer, Authentik, or other
     platform-stack dependency should be necessary for its storage mutation
     exercises.
   - It should be excluded from broad teardown/redeploy gates by default so it
     does not lengthen normal infrastructure validation runs unnecessarily.
   - It should start in the Docker-only shape and then be mutated into the
     Docker-plus-extra-mount shape during testing.
6. Define the authoritative mutation classifier design:
   - targeted `terragrunt plan`
   - saved plan artifact
   - `terraform show -json` or equivalent machine-readable plan output
   - a stable extraction of the storage-relevant changed fields for the targeted
     stack
   - mapping from provider actions to:
     - safe in-place
     - reboot-required
     - replacement-sensitive
     - blocked
   - explicit rules for when the classifier blocks because the plan also mixes
     in unrelated stack changes
7. Before any live `apply`, require the repo target guard:
   - `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'`
   - expected output: `pve-test`

### Suggested implementation targets

- `docs/storage-refactor/` capability note or mutation matrix
- `terraform/lxc/stacks/*/STACK_CONTRACT.md` review notes where useful
- dedicated storage-validation LXC note
- plan-classifier design note

### Tests

- `./scripts/teardown-deploy-test.sh source-preflight`
- `python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test --offline`
- targeted `terragrunt plan` and `apply` exercises for the mutation matrix on
  the dedicated storage-validation LXC
- written evidence showing which mutations are in-place, reboot-type,
  replacement-sensitive, or blocked

### Exit criteria

- we have a written mutation matrix
- we know the dangerous `mount_point` mutation cases precisely
- we know what backup behavior must become explicit
- we have a dedicated storage-validation LXC plan that preserves the general
  case shape
- we have a concrete plan-classifier design for provider action classification
- we know the exact field-transition mapping the classifier will use for the
  supported storage edits

## Phase 1: Define The Persistent Mount Contract

### Objective

Make persistent mount intent explicit without expanding scope into a full
storage-migration redesign.

### Work

1. Redesign the `terraform/lxc/storage/<env>.yaml` contract, starting with
   `pve-test.yaml`, so the schema can express:
   - runtime storage intent
   - Docker mount intent
   - extra mount intent
   - logical mount identity
   - resize control plane / mutation engine metadata
   - backup policy metadata
   - backup exception metadata when explicit Terraform control is unsupported
   - mutation policy metadata
2. Redesign stack authoring so persistent mounts are described explicitly.
3. Make the current module limit explicit in the contract:
   - Docker mount is always supported
   - zero or one optional extra mount is supported
   - requesting a second extra mount is invalid under this phase's scope
4. Decide and document transitional compatibility:
   - whether legacy `docker_storage_size`, `extra_mount_*`, and related fields
     remain temporarily supported
   - how warnings or validation errors are surfaced
   - that unchanged real stacks may remain on compatibility/default paths during
     this refactor
   - that `test-storage` is the first tracked stack to adopt the new
     declaration shape
5. Keep the contract environment-scoped:
   - `pve-test` is the first implementation target
   - a future `pve` manifest must not require schema redesign
6. Update `terraform/lxc/README.md` and `PLATFORM_CONTRACT.md` after the schema
   is frozen.

### Tests

- schema validation of the new manifest
- schema validation of a second fixture/example manifest to prove the contract
  is not hard-coded to `pve-test`
- unit tests for storage resolution logic
- fixture coverage for:
  - Docker-only shape
  - Docker-plus-one-extra-mount shape
  - already-has-extra-mount growth shape
  - direct/rootfs no-op shape
- no-op or deliberately equivalent plan for stacks that have not opted into any
  risky storage change
- negative tests for invalid mount identity, missing backup policy, and invalid
  mount references
- negative test for an attempted second extra mount request under the current
  module shape

### Exit criteria

- one environment-scoped contract can describe persistent mount identity,
  placement, backup intent, and mutation intent
- the contract is explicit about supporting at most one optional extra mount in
  this phase
- unchanged real stacks are not forced into repo-wide authoring churn just to
  complete this phase
- stack storage intent is no longer just an implicit by-product of anonymous
  mount requests

## Phase 2: Implement Safe Mutation Workflows

### Objective

Make the two core operator workflows low-risk and repeatable using the
approved backend-specific control plane:

- grow the Docker mount
- grow an existing extra mount
- attach an additional mount on the dedicated test LXC, starting from a shape
  that does not already define `extra_mount_*`

### Work

1. Implement grow-only resizing rules for the Docker mount and any supported
   extra mount workflow.
   - Existing extra mounts that already occupy the one optional extra-mount slot
     are in scope for grow-only resize.
   - Rootfs growth may remain Terraform/OpenTofu-managed where the provider
     proves an in-place path.
   - ZFS-backed non-rootfs growth must use the approved operational workflow:
     update desired size in `stack.yaml`, perform the host-side resize, verify
     the live result, then confirm Terraform/OpenTofu returns to no drift.
2. Implement additive extra-mount attachment rules for the supported
   "zero extra mounts" to "one extra mount" transition without silent path
   masking or surprise replacement behavior.
3. Block or explicitly flag any request that would require a second optional
   extra mount under the current module shape.
4. Add operator-visible mutation classification for storage changes using
   machine-readable Terraform plan output from the targeted stack as the
   authoritative source:
   - safe in place
   - reboot required
   - replacement-sensitive
   - blocked
5. Define the classifier behavior explicitly:
   - provider-reported in-place update for a known safe storage field
     transition maps to `safe in place` or `reboot required` based on the Phase
     0 capability matrix
   - provider-reported replacement or delete/create of the container after a
     storage edit maps to `replacement-sensitive`
   - first extra-mount introduction is judged separately from existing
     extra-mount resize
   - ambiguous, unsupported, or unclassified storage edits map to `blocked`
6. Add guardrails for:
   - shrink attempts
   - mount-over-existing-data cases
   - backend/profile changes that remain replacement-sensitive
7. Make persistent mount identity stable enough that plans and validation output
   refer to the same logical object consistently.
8. Document approved operator workflows for:
   - expand `/var/lib/docker`
   - attach one extra mount
   - expand an existing extra mount
   - sequence `stack.yaml` updates vs operational resize steps
   - stop conditions when a requested change remains replacement-sensitive

### Tests

- targeted resize exercise on the dedicated storage-validation LXC:
  - write sentinel data under Docker-managed state
  - change desired size in `stack.yaml`
  - grow the Docker mount with the approved operational workflow
  - verify sentinel data remains
  - verify a fresh `terragrunt plan` returns no drift
- targeted additive-mount exercise on the same dedicated storage-validation LXC:
  - attach a new filesystem
  - write sentinel data
  - reapply
  - verify data remains and the path is stable
- targeted existing-extra-mount resize exercise on the same dedicated
  storage-validation LXC after the first extra mount exists:
  - write sentinel data to the extra mount
  - change desired size in `stack.yaml`
  - grow the extra mount with the approved operational workflow
  - verify sentinel data remains and the mount path is unchanged
  - verify a fresh `terragrunt plan` returns no drift
- targeted negative plan for a stack shape that already uses `extra_mount_*`,
  proving a second-extra-mount request is blocked or surfaced as out of scope
- reapply without changes and prove the rendered mount intent remains stable
- negative test for attempted shrink
- negative test for mount-over-existing-data without an explicit safety rule
- negative test for a replacement-sensitive mount edit that should be blocked or
  surfaced clearly

### Exit criteria

- both primary operator workflows are documented and validated on `pve-test`
- existing extra-mount growth is documented and validated on the dedicated
  storage-validation LXC
- failure modes are surfaced before destructive apply
- the contract clearly distinguishes safe storage edits from risky ones

## Phase 3: Make Backup Intent Explicit

### Objective

Ensure persistent mounts are not implicitly omitted from backup policy.

### Work

1. Add backup policy metadata for persistent mounts.
2. Require every persistent mount to resolve to one of:
   - explicit Terraform-managed backup behavior
   - explicit unsupported exception with reason and operator note
3. Set and validate mount-point backup behavior explicitly where the provider
   supports it.
  - For the current Proxmox LXC mount-point path, this means:
    `backup_policy: include` -> `mount_point.backup = true`
    `backup_policy: exclude` -> `mount_point.backup = false`
  - The validator should reject unsupported values rather than silently
    defaulting to provider behavior.
4. Document backend-specific backup caveats where they affect operator
   expectations.
5. Document clearly that this phase is about backup inclusion policy, not
   restore testing.
6. Update validation and docs so each persistent mount has an explicit backup
   answer.

### Tests

- verify backup metadata in manifests and rendered configuration
- verify mount-point backup settings are explicit in the Terraform path where
  supported
- negative test where a persistent mount is missing backup policy
- negative test where a mount claims an unsupported backup path but omits the
  required exception reason
- live read-only validation that the intended backup behavior is visible for
  representative stacks

### Exit criteria

- every persistent mount has explicit backup intent
- every persistent mount resolves either to explicit Terraform behavior or to an
  explicit documented unsupported exception
- backup behavior is no longer left implicit for Docker or extra mounts
- the meaning of `include` vs `exclude` is documented in operator-facing terms
  and matches rendered Terraform fields
- docs clearly describe what is and is not covered by the backup policy work

## Phase 4: Validation Tooling And Guardrails

### Objective

Make storage safety machine-checkable in normal repo workflows.

### Work

1. Extend `validate-storage-contract.py` or replace it with a validator that
   understands:
   - logical mount identity
   - Docker mount intent
   - extra mount intent
   - backup policy
   - backup exceptions
   - mutation policy
2. Add a separate plan classifier or extend the validator so it can consume
   machine-readable Terraform plan output from a targeted stack plan and classify
   provider actions for storage changes.
   - The classifier must persist the extracted storage-relevant changed fields
     alongside the final mutation class so the result is auditable.
3. Add an offline plan-safety check that flags:
   - shrink attempts
   - path masking
   - replacement-sensitive mount edits
   - direct Terraform/OpenTofu apply attempts for mount-size changes whose
     declared resize control plane is operational
   - missing backup policy
   - missing required backup exception detail
4. Add a live validator that checks:
   - required storage backends exist
   - required templates exist
   - backup-relevant mount settings are explicit
   - environment-scoped rules do not hard-code `pve-test`
5. Add representative no-op validation for direct/rootfs service stacks so the
   refactor does not silently regress them.
6. Wire the new checks into:
   - `source-preflight`
   - `live-preflight`
   - any storage mutation validation helper added by this refactor

### Tests

- unit tests for validator logic
- offline negative tests for unsafe mount mutations
- tests for plan-classifier mapping from plan JSON to the four mutation classes
- tests for the field-transition mapping that separates:
  - Docker growth
  - existing extra-mount growth
  - first extra-mount introduction
  - blocked path/backend/removal changes
- live read-only validation against `pve-test`
- tests or fixtures that prove the validator can consume more than one
  environment manifest shape
- representative no-op checks for direct/rootfs stacks such as `step-ca-stack`
  or `dns-stack`
- rerun:
  - `./scripts/teardown-deploy-test.sh source-preflight`
  - `./scripts/teardown-deploy-test.sh live-preflight`

### Exit criteria

- unsafe storage mutations are detected before apply
- preflight remains split cleanly into source-only and live checks
- the contract and validator path are not coupled to `pve-test`-only naming

## Phase 5: Final Validation, Scans, And Promotion

### Objective

Prove the refactor branch is operationally sound and ready for merge.

### Work

1. Re-run the targeted storage mutation validations for the two primary
   workflows plus existing-extra-mount growth on the dedicated
   storage-validation LXC.
2. Run representative checks against all relevant storage shapes:
   - Docker-mount-only stacks
   - Docker-plus-extra-mount stacks
   - direct/rootfs no-op stacks
   The storage primitive itself is proven on `test-storage`; representative
   checks on real infrastructure stacks remain non-destructive.
3. Confirm the second-extra-mount case remains explicitly blocked or out of
   scope under the current module shape.
4. Run the standard repo non-destructive validations.
5. Run required security scans:
   - `/home/steve/.local/bin/snyk iac test terraform/`
   - `./with-secrets /home/steve/.local/bin/sonar-scanner`
6. Review any new findings before merge.
7. Run the required infrastructure promotion gate for the repo branch model.
8. Record any follow-on work that is intentionally out of scope for this
   project.

### Tests

- `terraform fmt -recursive terraform/lxc`
- targeted `terragrunt plan` on representative stacks
- `./scripts/teardown-deploy-test.sh source-preflight`
- `./scripts/teardown-deploy-test.sh live-preflight`
- targeted mutation validation for:
  - Docker mount growth
  - existing extra-mount growth
  - additive extra mount attachment
- representative no-op validation for direct/rootfs stacks
- explicit negative validation for a second-extra-mount request
- required scans listed above

### Exit criteria

- the primary storage mutation workflows are validated
- storage guardrails pass
- the dedicated storage-validation LXC proved the primitive without requiring
  interconnected infrastructure-stack mutation testing
- required scans pass or are explicitly accepted
- the branch is ready for promotion back to `baseline/teardown-validated`
- any intentional out-of-scope follow-up is written down clearly

## Phase Completion Checklist

Do not advance a phase until all of the following are true:

- the code and docs for the phase are committed in a coherent state
- the phase test list ran successfully
- known deviations are written down
- the next phase does not depend on undocumented operator knowledge

## Done Definition

This refactor is complete when:

- persistent mount intent is modeled explicitly
- grow-only Docker mount updates are supported and tested through the approved
  backend-specific workflow
- grow-only existing extra-mount updates are supported and tested through the
  approved backend-specific workflow
- additive extra-mount attachment is supported and tested
- the supported additive workflow is clearly limited to the current module shape
  of zero or one optional extra mount
- backup intent is explicit for persistent mounts
- validation can identify shrink attempts, path masking, and
  replacement-sensitive storage edits before apply
- mutation classification is driven by machine-readable Terraform plan output
- operator docs explain the safe workflows and the stop conditions
- the resulting contract is ready for later `pve` adoption without schema
  redesign
