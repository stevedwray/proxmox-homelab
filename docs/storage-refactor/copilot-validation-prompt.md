# Copilot Storage Refactor Validation Prompt

Continue the storage refactor from the current branch state in
`/home/steve/git/proxmox-homelab`.

Start by reading:

- `docs/storage-refactor/README.md`
- `docs/storage-refactor/plan.md`
- `docs/storage-refactor/phase-0-audit-notes.md`
- `docs/storage-refactor/capability-matrix.md`
- `docs/storage-refactor/classifier-design.md`

Treat the branch as a candidate for Phase 0 validation.

Your job for this pass is to validate whether Phase 0 is actually complete and
ready to accept. Do not start Phase 1 work.

Persist within this single pass until you either:

- complete the full Phase 0 validation scope and can recommend whether Phase 0
  should be accepted, or
- hit a concrete blocker that prevents the remaining validation steps from
  running or being concluded

Do not stop after intermediate checks or partial findings just to ask the
operator to tell you to proceed. If the next step is already defined by this
prompt and no blocker exists, continue automatically in the same pass.

This pass must produce material validation progress:

- run the required validation commands, or
- repair an obvious repo-local validation blocker and rerun, or
- stop with the exact blocker after attempting the required validation path

Do not spend this pass primarily rewriting prompts, restating branch state, or
recommending another generic follow-up unless a concrete blocker prevents the
validation work itself.

1. Reconstruct the exact Phase 0 validation scope from `plan.md`.
   - Validate only Phase 0.
   - Do not broaden this into gate or promotion work.

2. Verify the target guard first.
   - Run:
     `./with-secrets bash -lc 'echo $TF_VAR_proxmox_node'`
   - Expected: `pve-test`
   - If not `pve-test`, stop and report targeting failure.

3. Re-run the required Phase 0 checks.
   - Run:
     - `./scripts/teardown-deploy-test.sh source-preflight`
     - `python3 terraform/lxc/validate-storage-contract.py --manifest terraform/lxc/storage/pve-test.yaml --stacks-dir terraform/lxc/stacks --proxmox-node pve-test --offline`
   - Report exact results.
   - If either fails, stop and report the exact failure.

4. Re-validate the key Phase 0 storage conclusions.
   - Confirm the current documented conclusions are internally consistent:
     - Docker mount growth on current `pve-test` backend/profile is `replacement-sensitive`
     - first extra-mount introduction is `blocked`
     - path changes, backend/profile changes, mount removal, and second-extra-mount requests are blocked by Phase 0 policy
   - Re-run safe source-level checks for:
     - `terraform/lxc/classify-storage-plan.py`
     - `terraform/lxc/check-plan-safety.py`
   - If feasible in this validation pass, re-run the targeted provider-backed
     mutation checks for the authoritative conclusions above.
   - If live re-validation is not feasible, state exactly why and validate the
     source-evidence path instead.

5. Validate implementation/doc alignment.
   - Confirm these agree:
     - `docs/storage-refactor/phase-0-audit-notes.md`
     - `docs/storage-refactor/capability-matrix.md`
     - `docs/storage-refactor/classifier-design.md`
     - `terraform/lxc/classify-storage-plan.py`
     - `terraform/lxc/check-plan-safety.py`
   - Confirm tracked fixtures are clearly documented as non-authoritative
     classifier test vectors only.

6. Resolve the remaining acceptance question around `rootfs_size`.
   - Decide whether `rootfs_size: increase` is acceptable as `safe-in-place`
     based on existing repo technical facts and current Phase 0 scope, even
     without new provider-backed proof in this branch.
   - If yes, say that explicitly in the validation hand-back.
   - If no, mark Phase 0 partial/blocked and explain the missing proof
     requirement.

7. Run required repo scans for merge-relevant validation.
   - Run:
     - `/home/steve/.local/bin/snyk iac test terraform/`
     - `./with-secrets /home/steve/.local/bin/sonar-scanner`
   - If scan failures are environmental or pre-existing, say so clearly.

8. Fix only validation failures caused by the storage refactor.
   - Avoid unrelated cleanup.
   - Do not add Phase 1 schema or contract work.
   - Keep `terraform/lxc/storage/pve-test.phase1.yaml` isolated.
   - Do not touch unrelated local edits.

9. Write the durable Phase 0 validation hand-back into the tracked audit note.
   - Update `docs/storage-refactor/phase-0-audit-notes.md` in the same pass.
   - Do not leave the file as a stale proof/audit note that still recommends a
     generic follow-up once validation has actually been attempted.
   - The file must clearly record:
     - validation date/pass scope
     - validation status: passed, partial, or blocked
     - commands run
     - key results
     - files changed in this pass
     - blockers or environmental failures, if any
     - whether Phase 0 should now be accepted as complete
     - exact recommended next pass
   - If the file already contains earlier Phase 0 audit material, update or
     replace the stale "Recommended Next Copilot Pass" and adjacent hand-back
     sections so the durable tracked note matches the latest validation reality.

Working rules:

- do not create sibling worktrees under `..`
- work in the current checkout unless a clean worktree is strictly required for
  a gate or proof flow
- if a clean worktree is strictly required, place it under
  `/tmp/proxmox-homelab-worktrees/` and remove it when finished
- do not create tracked temporary documents, evidence files, handoff notes, or
  handback notes unless they are durable artifacts that truly need to survive
  across branches or sessions
- prefer inline validation hand-back in the response and ignored or `/tmp`
  locations for transient notes or evidence
- keep the response hand-back concise and high-signal; do not restate large
  sections of tracked docs verbatim when the durable detail already lives in
  `docs/storage-refactor/`
- do not pause for confirmation between prompt steps when the next required
  step is already clear from this prompt
- if one validation step passes, continue automatically to the next required
  step in the same pass
- if a validation step fails because of an obvious repo-local deficiency that
  can be repaired safely from repo context, repair it and rerun in the same
  pass
- only stop early for a concrete blocker, targeting failure, validation
  failure that prevents further progress, environmental failure, or an explicit
  user instruction

End with a review-ready hand-back in the response itself that includes:

- phase validated
- validation status: passed, partial, or blocked
- files changed, if any
- validations and tests run
- validations not run, if any
- blockers, deviations, environmental failures, or assumptions
- whether Phase 0 should now be accepted as complete
- whether `rootfs_size: increase` was accepted as a valid Phase 0
  `safe-in-place` row or remains a blocker
- the exact recommended next pass:
  - follow-up
  - gate
  - promotion

The hand-back must be review-ready in the response itself, not only written to
files. Prefer a compact response that summarizes status, commands run,
blockers, and next pass, while pointing to tracked docs for durable detail.
The same hand-back outcome must also be reflected durably in
`docs/storage-refactor/phase-0-audit-notes.md`.
