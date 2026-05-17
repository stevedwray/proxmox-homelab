# Copilot Refactor Kickoff Prompt

You are working in `/home/steve/git/proxmox-homelab` on the storage refactor
documented in:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`

Start by reading those two files and then inspect the current implementation in:

- `terraform/lxc/main.tf`
- `terraform/lxc/variables.tf`
- `terraform/lxc/modules/lxc-docker-host/*`
- `terraform/lxc/stacks/*/stack.yaml`
- `terraform/lxc/README.md`
- `terraform/lxc/PLATFORM_CONTRACT.md`

Your job is to implement the refactor with as little supervision as possible.

Primary objective:

- make storage backend selection an environment-level configuration concern
  instead of a stack-file, Terraform-default, or template-string concern

Required end state:

- stacks express storage intent rather than physical Proxmox pool names
- one `pve-test` storage manifest or equivalent env-scoped config resolves that
  intent to concrete backends
- Terraform root resolves storage before calling the LXC module
- template identity is separated from template storage location
- validation fails early when referenced storage backends or template artifacts
  do not exist or do not support required content types

Important constraints:

- treat `pve-test` as a live but rebuildable environment, not a greenfield host
- keep implementation work on a short-lived `work/*` branch
- do not rely on undocumented host-only knowledge
- do not leave long-term storage policy in module defaults
- do not assume every stack is a Docker stack just because the current module
  always provisions `/var/lib/docker`

Expected working style:

- make reasonable decisions and keep moving without asking for confirmation on
  routine implementation details
- use small, coherent commits as milestones when a piece is validated
- update docs as the implementation changes the contract
- surface only real decision points or blockers

Decisions you should make deliberately and document if they matter:

- whether this branch uses a hard cutover or short transitional compatibility
- whether `/var/lib/docker` remains always-on or becomes explicitly optional
- the exact storage manifest schema, as long as it preserves the plan’s design
  rules

Suggested execution order:

1. Audit and document every current storage decision point, including
   `infrastructure-containers`, `storage-containers`, `storage-template`,
   template references, and stack-specific docs that still teach physical pool
   names.
2. Introduce the canonical `pve-test` storage manifest.
3. Move storage resolution into the Terraform root layer.
4. Simplify the LXC module so it consumes resolved values.
5. Split template identity from template storage.
6. Refactor stack files to the new storage-intent model.
7. Add storage validation and wire it into preflight/gate flows.
8. Update README, platform contract, examples, and related docs.
9. Run formatting, targeted validation, required scans, and then the full
   teardown + redeploy gate when the branch is ready.

When you report progress, focus on:

- what changed
- what remains
- any real risks or blocking choices

Do not stop after analysis. Continue through implementation and validation until
you hit a genuine blocker or the refactor is complete.
