# Next Session Handoff

## Goal
Run the first full teardown/deploy rehearsal for the in-progress
`work/storage-refactor-rewrite-01` branch so the storage-refactor changes are
proved through the normal destructive gate, not just through source-only and
targeted plan validation.

## Current State
- The storage-refactor status docs are up to date in
  `docs/storage-refactor/README.md` and `docs/storage-refactor/plan.md`.
- The branch has already passed the non-destructive proof points needed before a
  destructive run:
  - `source-preflight` passes with offline storage validation and classifier
    regression checks
  - `plan` passes with targeted storage plan classification and
    `check-plan-safety.py` gating for explicit-contract stacks
- The explicit Docker mount rollout is complete for active stacks:
  every active non-`.hold` stack manifest that still carries
  `docker_storage_size` now also declares `docker_mount` (`19/19` active
  manifests).
- Prior cycle attempts under stamp `20260527-215251` are stale. Do not reuse
  that stamp or approval packet now that the branch contents and docs have
  changed.

## What The Next Session Should Prove
- the updated storage contract survives the full destroy/redeploy flow on
  `pve-test`
- no unexpected storage replacement or blocked storage drift appears during the
  normal harness cycle
- the current storage guardrails behave correctly in the same workflow the
  branch will use for promotion
- any remaining backup/restore exception is recorded only if the real cycle
  exposes it

## Start From Here
Stay on the current branch unless the operator explicitly asks for a different
branching move. The work to validate is still in the dirty tree on
`work/storage-refactor-rewrite-01`.

Recommended first commands:

```bash
git branch --show-current
git status --short
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
./scripts/teardown-deploy-test.sh approval-preflight
```

Expected outcomes:
- branch remains `work/storage-refactor-rewrite-01`
- target guard prints exactly `pve-test`
- `approval-preflight` creates a fresh evidence stamp under
  `docs/teardown-test/evidence/<stamp>/`
- the working tree must be clean before `approval-preflight` can pass, so either
  commit the validated source changes first or stop and resolve that explicitly

## Approval Packet Step
`approval-preflight` does not create the approval packet. After it succeeds,
create a fresh packet at:

`docs/teardown-test/evidence/<stamp>/approval-packet-op06.md`

Use these as references only:
- `docs/teardown-test/packets/20260521-155452.md`
- `docs/teardown-test/evidence/20260527-215251/approval-packet-op06.md`

Update the fresh packet so all of the following match the new run:
- `stamp`
- `target: pve-test`
- `approved commit SHA`
- outage window
- rollback deadline
- scope approval and exclusions
- service evidence references
- recreatable services evidence references or explicit recreatable approval

Do not point the new cycle at the old `20260527-215251` packet.

## Destructive Run Command
Once `approval-preflight` has passed and the fresh approval packet is in place,
the destructive gate command should be:

```bash
./scripts/teardown-deploy-test.sh cycle --execute \
  --approval-text "approve pve-test teardown deploy test" \
  --approval-packet docs/teardown-test/evidence/<stamp>/approval-packet-op06.md \
  --stamp <stamp>
```

Useful follow-up checks during or after the cycle:

```bash
./scripts/teardown-deploy-test.sh status --stamp <stamp>
./scripts/teardown-deploy-test.sh platform-status --stamp <stamp>
```

## Key Files To Review First
- `scripts/teardown-deploy-test.sh`
- `docs/teardown-test/README.md`
- `docs/teardown-test/runbook.md`
- `docs/teardown-test/variables.md`
- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `terraform/lxc/classify-storage-plan.py`

## Guardrails
- Do not reuse an old stamp or approval packet; generate a fresh one for the
  current commit.
- Do not start `cycle --execute` until the working tree is clean and
  `approval-preflight` has passed.
- Do not treat the old `Exit Code 143` cycle attempts as current results; they
  are interrupted runs, not the proof artifact for this branch.
- If the cycle exposes a real source bug, stop the destructive sequence,
  capture the evidence, fix it in source, rerun non-destructive gates, and only
  then attempt another full cycle.
- Run the required post-change scan before merge if the next session changes
  code or YAML further:
  `./with-secrets /home/steve/.local/bin/sonar-scanner`

## Acceptance Criteria
- `approval-preflight` passes on a clean tree for the branch being tested
- a fresh approval packet is present and accepted for the same stamp/commit
- the full `cycle --execute` run completes or fails with a precise evidence
  trail under the fresh stamp
- storage-refactor docs can be updated from that evidence without hand-waving
