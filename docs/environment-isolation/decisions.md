# Environment Isolation — Decisions

Durable design decisions for the per-environment Terragrunt migration, in
the format used by other workspaces in this repo: one `## Decision N:
Title` per settled choice, with context and the actual decision.

## Decision 1: Migrate `technitium-stack` only, not all 11 unmigrated stacks

Context: 11 of 36 stacks lack the per-environment Terragrunt layout. It
would be easy to assume all 11 need the same migration.

Decision: only `technitium-stack` gets migrated under this workspace.

Rationale: checked each of the 11 for an SDN `network:` zone in
`stack.yaml` (the signal that a stack genuinely runs a separate instance
per environment). 9 have none — they are physical/`pve`-only LXCs
(`gaming-stack`, `media-stack`, etc.) with no test-environment counterpart
to conflict with; migrating them would add Terragrunt scaffolding with no
corresponding risk to close. `dhcp-test-client-01` has a zone but is Stage
A's disposable DHCP-refactor test fixture, inherently `pve-test-vm`-only by
design — already safely handled by the `scripts/provision.sh` guardrail,
which correctly blocks any attempt to provision it against `pve`. Only
`technitium-stack` is both SDN-VLAN-attached (`mgmt_seg`) and genuinely
deployed twice — the exact shape that produced the 2026-07-06 incident.

## Decision 2: Relocate existing Terraform state, don't reconstruct it

Context: before planning the migration, it would have been reasonable to
assume `technitium-stack`'s Terraform state doesn't cleanly track both
environments (given the inventory-level confusion the incident exposed),
requiring `terraform import` to reconstruct tracking for whichever
environment's resource isn't represented.

Decision: verified this assumption against the actual state files first,
rather than planning around a guess. Both environments' containers **are**
already cleanly tracked — `pve-test-vm`'s container in the `default`
Terraform workspace, production's in the `pve` workspace, distinguished
concretely by their `network_interface.mac_address` attributes
(`BC:24:11:16:6C:8C` vs `BC:24:11:CB:74:A2`), both `vmid=20015`. The
migration is therefore a **state relocation** (copy each workspace's
existing state to its own new isolated directory, verify with a zero-diff
`plan`) — not a reconstruction. See `plan.md` Phase 2's explicit procedure
and safety gate.

Rationale: planning against the actual state shape rather than the
worst-case assumption avoids over-engineering the migration procedure (no
`import` blocks, no resource-address reconciliation needed) and correctly
identifies the real safety gate: a `plan` run against the new location
must show zero changes before anything is retired or applied.

## Decision 3: Pilot on `pve-test-vm` before touching production's state

Context: `technitium-stack`'s production container currently serves
cut-over production DNS. Any state operation that goes wrong risks
Terraform proposing to destroy/recreate it.

Decision: the full relocation procedure (init at new location, seed with
existing state, verify zero-diff plan, retire old location) is executed
and confirmed working against `pve-test-vm`'s `default`-workspace state
first. Only after that pilot succeeds is the same procedure repeated
against production's `pve`-workspace state, under explicit operator
approval per `CLAUDE.md`'s Production Credential Controls.

Rationale: `pve-test-vm`'s state, while still a real deployed resource, is
lower-stakes to get wrong than production's live DNS authority. Proving the
mechanism once before repeating it against production reduces the chance
of discovering a procedural mistake for the first time against the
higher-stakes target.

## Pending

- Whether the process-gap fix (Phase 5: prevent future stacks from being
  scaffolded without the per-environment layout) should also remove
  `scripts/provision.sh`'s shared-inventory fallback path entirely for
  `network:`-zoned stacks, or just document the requirement. Not yet
  decided — see plan.md's Open Questions.
- Whether physical/`pve`-only stacks should get an explicit
  `environment_scope: pve-only` marker in `stack.yaml` to make their
  exemption declared rather than inferred. Not yet decided.
