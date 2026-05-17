# Storage Refactor Execution Plan

## Goal

Refactor the LXC provisioning path so that storage usage is controlled by
environment configuration rather than by hardcoded storage pool names embedded
in stack definitions, Terraform defaults, or template references.

The target design is:

- stacks declare storage intent
- environment configuration resolves that intent to concrete Proxmox backends
- Terraform modules receive already-resolved storage values
- validation checks the configured storage backends exist before apply

## Non-Negotiable Constraints

1. `pve-test` currently has deployed containers on the active storage layout.
   The refactor plan must treat the environment as live and rebuildable, not as
   empty.
2. This is infrastructure work and must be implemented on a `work/*` branch cut
   from `baseline/teardown-validated`.
3. The merge gate is a full teardown + redeploy validation from the refactor
   branch.
4. The refactor must not depend on undocumented host-only knowledge. The
   storage contract has to become explicit in tracked configuration.

## Current Technical State

### Repo state

- stack files commonly set `rootfs_storage: infrastructure-containers`
- multiple stack files also set `rootfs_storage: storage-containers`
- Terraform also defaults `default_storage` to `infrastructure-containers`
- the LXC module always provisions:
  - a root filesystem disk
  - a `/var/lib/docker` mount point
  - an optional extra mount point
- stack `ostemplate` values encode a Proxmox storage name directly, for example
  `storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz`

### Live `pve-test` state

- `local` and `local-lvm` exist on the internal SSD
- `infrastructure-containers` is active and currently backs the deployed LXC
  stack set
- `storage-template` is active and is used by the current template reference
  model
- the active `infrastructure-containers` and `storage-template` pools are on
  the external Samsung T7 USB drive

## Refactor End State

After the refactor:

- no stack should need to name `infrastructure-containers`, `local-lvm`,
  `storage-template`, or any other physical backend directly
- storage policy for `pve-test` should be configurable from a single storage
  manifest or equivalent environment-scoped config
- changing from USB-backed pools to SSD-backed pools should be a configuration
  change plus validation, not a repo-wide stack edit
- template storage should be resolved through the same configuration model as
  runtime storage

## Proposed Configuration Model

Use logical storage profiles rather than physical pool names in stack files.

Example intent model:

```yaml
storage_profile: platform-default
rootfs_size: 8
docker_storage_size: "20G"
extra_mounts:
  - id: certs
    path: /opt/proxy-stack/certs
    size: "5G"
    profile: durable-small
```

Environment configuration then resolves profiles to physical Proxmox storage:

```yaml
profiles:
  platform-default:
    rootfs_storage: local-lvm
    docker_storage: local-lvm
    template_storage: local

  durable-small:
    mount_storage: local-lvm
```

The exact schema may differ, but the design rule should hold:

- stack files express intent
- environment config names concrete backends

## Step-By-Step Plan

### Step 1: Freeze the design goal in documentation

Author the planning documents on a short-lived branch, then merge them into
`baseline/teardown-validated` before implementation starts.

Required outputs:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`

Acceptance criteria:

- the branch strategy is explicit
- the current live `pve-test` storage state is acknowledged
- the target architecture is described clearly enough to implement without
  re-deciding the goal mid-stream

### Step 2: Cut the implementation branch from `baseline/teardown-validated`

Start implementation from the current baseline branch using the infrastructure
workflow model.

Command sequence:

```bash
git checkout baseline/teardown-validated
git pull --ff-only origin baseline/teardown-validated
git checkout -b work/storage-refactor-01
```

Acceptance criteria:

- implementation does not proceed directly on
  `baseline/teardown-validated`
- all subsequent code and validation work happens on the `work/*` branch

### Step 3: Audit every current storage decision point

Identify every place where storage policy is currently encoded.

Audit targets:

- `terraform/lxc/stacks/*/stack.yaml`
- `terraform/lxc/stacks/*/README.md`
- `terraform/lxc/main.tf`
- `terraform/lxc/variables.tf`
- `terraform/lxc/modules/lxc-docker-host/*`
- template-related docs and stack references
- host bootstrap and validation docs

Questions to answer:

- which stacks override `rootfs_storage`
- which stacks still reference `storage-containers` versus
  `infrastructure-containers`
- which stacks rely on default storage
- which stacks use `extra_mount_storage`
- which stacks rely on `docker_storage_size`
- which stacks are non-Docker but still inherit Docker storage behavior
- where template storage names are embedded directly

Required output:

- a short tracked audit note or checklist in this directory, if needed during
  implementation

Acceptance criteria:

- no storage backend coupling remains unidentified before schema changes begin

### Step 4: Define the canonical storage manifest

Introduce one environment-scoped source of truth for physical storage backends.

Recommended location:

- `terraform/lxc/storage/pve-test.yaml`

Required contents:

- logical storage profile definitions
- rootfs backend mapping
- Docker backend mapping
- template backend mapping
- optional extra-mount backend mapping
- any content-type expectations needed for validation

Example concerns the manifest must represent:

- SSD-backed runtime storage
- template storage
- durable extra mounts
- future alternative backends without stack-file rewrites

Acceptance criteria:

- `pve-test` storage policy is representable in one file
- the file can describe both current USB-backed and future SSD-backed mappings

### Step 5: Refactor stack schema from physical backends to storage intent

Replace direct pool naming in stack files with logical intent.

Recommended changes:

- remove direct reliance on `rootfs_storage` in stack files where possible
- replace `extra_mount_storage` with profile-driven or class-driven mapping
- decide whether `docker_storage_size` remains size-only or becomes part of a
  richer mount object

Preferred rule:

- stack files may still declare sizes and paths
- stack files should not name physical Proxmox pools

Acceptance criteria:

- stack files stop hardcoding `infrastructure-containers` and similar backend
  names for the refactored path

### Step 6: Move storage resolution into the Terraform root layer

The Terraform root module should resolve storage intent before calling the LXC
module.

Implementation goals:

- load the environment storage manifest
- determine the effective storage profile for the stack
- derive:
  - rootfs storage
  - Docker storage
  - extra mount storage
  - template storage
- pass only resolved values into the LXC module

Why this matters:

- the module should provision resources
- the root layer should apply environment policy

Acceptance criteria:

- no environment policy remains embedded as a fallback in generic module code

### Step 7: Simplify the LXC module contract

Refactor `terraform/lxc/modules/lxc-docker-host` so the module consumes resolved
inputs instead of deciding storage policy itself.

Required changes:

- remove or sharply reduce environment-specific defaults such as
  `default_storage = "infrastructure-containers"`
- make the module’s storage inputs explicit and resolved
- preserve support for:
  - root disk
  - Docker mount
  - optional extra mount

Design note:

If a stack does not need Docker storage, the refactor should decide whether:

- the Docker mount remains always-on for all current LXC stacks, or
- the model now supports Docker mount omission explicitly

That decision should be made deliberately and documented.

Acceptance criteria:

- the module no longer encodes `pve-test` storage policy internally

### Step 8: Split template identity from template storage

This is required for a proper refactor.

Today, template references combine:

- where the template is stored
- which template artifact is used

The refactor should separate those concerns.

Recommended model:

- `template_name`: for example `debian-13.1-2-docker-template.tar.gz`
- `template_profile` or resolved `template_storage`

This allows moving templates from `storage-template` on USB to an SSD-backed
directory store without rewriting every stack as a special case.

Acceptance criteria:

- template location is driven by environment storage configuration
- stacks no longer embed physical template storage names directly

### Step 9: Add storage validation as a first-class gate

Introduce validation that checks environment storage config against live Proxmox
capabilities before apply-like operations.

Recommended validation scope:

- referenced storage pools exist
- required content types are supported:
  - `rootdir` for LXC rootfs and mount points
  - `vztmpl` for templates
- configured template artifact exists in the resolved template store
- requested storage profiles resolve completely

Recommended implementation:

- a repo-local validation script
- optional Ansible validation for host-side checks
- a harness/preflight entry that can be run before teardown + redeploy

Acceptance criteria:

- misconfigured storage manifests fail before container apply starts

### Step 10: Decide and document the transitional compatibility policy

Do not mix old and new storage modeling by accident.

Choose one explicit migration strategy:

1. Hard cutover:
   - all stack files migrate to the new storage model in one branch
   - old fields become unsupported

2. Transitional compatibility:
   - old storage fields still work temporarily
   - new profile model is preferred
   - validation warns when legacy fields are used

Recommended choice:

- transitional compatibility only if needed to keep the branch manageable
- otherwise prefer a hard cutover during the same refactor branch

Acceptance criteria:

- the branch contains one clear storage contract, not two competing long-term
  models

### Step 11: Update docs and examples everywhere storage is taught

Once the implementation exists, update the documentation so the canonical
storage model matches the code.

Required targets:

- `terraform/lxc/README.md`
- `terraform/lxc/PLATFORM_CONTRACT.md`
- stack creation examples
- host bootstrap docs that refer to active storage expectations
- teardown/rebuild docs where storage assumptions matter

Acceptance criteria:

- the documented stack authoring path no longer teaches physical storage pool
  names as part of normal stack configuration

### Step 12: Prepare the live cutover strategy for `pve-test`

Because `pve-test` already has deployed LXCs on the current storage model, the
implementation branch must choose a cutover approach explicitly.

Recommended cutover method:

- do not perform piecemeal in-place storage migration for the refactor itself
- treat the refactor as a rebuild-path change
- validate it through the normal teardown + redeploy gate

Why:

- this repo already treats `pve-test` as rebuildable
- a clean rebuild validates both configuration resolution and host storage
  assumptions together
- in-place migration would add risk and complexity unrelated to the storage
  contract refactor

Pre-cutover checklist:

- confirm target guard is still `pve-test`
- confirm chosen SSD-backed storage backends exist and are healthy
- confirm the resolved template location contains the expected LXC template
- confirm the validation script passes
- capture current evidence for the running environment before teardown

Acceptance criteria:

- the branch has an explicit live-environment cutover plan
- the refactor does not rely on ad hoc manual pool switching under live LXCs

### Step 13: Run full teardown + redeploy validation on the refactor branch

This is the promotion gate for infrastructure work.

Minimum expected validation:

- source preflight and live preflight pass
- storage validation passes
- teardown succeeds
- infrastructure redeploy succeeds
- platform stacks come back on the refactored storage model
- post-cycle health and platform status evidence are captured

If the storage refactor also changes template placement, validation must prove:

- template resolution works on a fresh pass
- no stack still depends on the old USB-backed template location by accident

Acceptance criteria:

- a complete evidence-backed cycle succeeds from the refactor branch

### Step 14: Run required scans before merge

Because this work is likely to touch Terraform, shell, Python, and YAML:

- Terraform changes: `/home/steve/.local/bin/snyk iac test terraform/`
- Code changes: `./with-secrets /home/steve/.local/bin/sonar-scanner`

If either scan introduces new issues:

- stop
- review the findings
- resolve or explicitly accept them before merge

### Step 15: Merge back to `baseline/teardown-validated`

After validation passes on the `work/*` branch:

- commit the verified refactor work
- merge into `baseline/teardown-validated`
- preserve evidence that the baseline rebuild gate passed under the new storage
  model

Recommended merge condition:

- only merge once both the storage contract and the teardown/redeploy gate are
  proven together

## Suggested File-Level Implementation Sequence

The implementation branch should roughly change files in this order:

1. Add storage manifest support.
2. Add resolution logic in `terraform/lxc/main.tf`.
3. Refactor `terraform/lxc/modules/lxc-docker-host/*` inputs.
4. Update stack schema and stack files.
5. Refactor template resolution.
6. Add validation tooling.
7. Update docs and examples.
8. Run full environment validation.

This order keeps the refactor understandable and reduces the chance of changing
all stacks before the resolution model exists.

## Risks To Manage

### Risk 1: Half-centralized storage policy

If stack files lose backend names but Terraform defaults still embed
environment-specific storage choices, the refactor will look cleaner without
actually solving the problem.

Mitigation:

- remove policy from module defaults
- resolve policy only in environment config

### Risk 2: Template path remains a hidden coupling

If runtime storage is centralized but `ostemplate` still hardcodes
`storage-template:...`, the environment is still tied to the old backend.

Mitigation:

- refactor template resolution in the same work branch

### Risk 3: Live `pve-test` state is ignored

If the implementation plan assumes a clean host, the branch may validate
incorrectly or hide operational cutover risk.

Mitigation:

- explicitly record the current deployed state
- validate through full teardown + redeploy

### Risk 4: Host bootstrap and Terraform drift apart

If Terraform expects SSD-backed pools but host bootstrap still teaches or
creates only the old USB-backed arrangement, the repo becomes inconsistent.

Mitigation:

- update storage validation and host-facing docs in the same branch

## Done Definition

This refactor is done when all of the following are true:

- stack definitions express storage intent rather than physical pool names
- one environment config controls physical backend selection for `pve-test`
- Terraform resolves storage through that config
- template storage is resolved through the same model
- validation proves required pools and templates exist before apply
- the refactor branch passes a full teardown + redeploy cycle
- the validated branch is merged back to `baseline/teardown-validated`
