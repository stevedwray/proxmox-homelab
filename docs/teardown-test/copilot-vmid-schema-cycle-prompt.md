# Copilot Teardown Cycle Prompt

Continue from the current branch state in
`/home/steve/git/proxmox-homelab`.

This is a live infrastructure validation pass on `pve-test`. The environment is
currently deployed and is intended to be ready for a full teardown + redeploy
cycle.

Start by reading:

- `.github/copilot-instructions.md`
- `docs/teardown-test/README.md`
- `docs/teardown-test/repeatable-test.md`
- `docs/teardown-test/runbook.md`
- `docs/teardown-test/inventory.md`
- `docs/teardown-test/operations-plan.md`
- `docs/teardown-test/lessons-learned.md`

Current branch context

- Branch: `work/vmid-zone-schema`
- This branch changes the active platform VMID scheme to encode zone/VLAN and
  host identity.
- The active stack VMIDs on this branch are:
  - `ci-runner-01` -> `10063`
  - `portainer-stack` -> `20020`
  - `authentik-stack` -> `20010`
  - `step-ca-stack` -> `20011`
  - `monitoring-stack` -> `20012`
  - `dns-stack` -> `20013`
  - `proxy-stack` -> `30010`
  - `harbor-stack` -> `40010`
  - `apt-cacher-stack` -> `40011`
  - `netbox-stack` -> `40012`

Execution intent

- Treat the current branch changes as the intended source of truth for this
  validation pass.
- Do not redesign the VMID scheme.
- Do not stop after each successful checkpoint to ask whether to continue.
- Move straight through the practical sequence unless you hit a real blocker,
  a failing gate, or a destructive-action approval mismatch.
- If the working tree is clean, proceed.
- If the working tree is dirty only because of the VMID-schema changes on this
  branch, review them, commit them on the current `work/*` branch, and then
  continue so the approval-preflight clean-tree gate can pass.
- If you find unrelated dirty files, stop and report them instead of trying to
  guess.

Your job for this pass

1. Prepare the branch for the destructive gate.
   - Confirm the current branch and HEAD.
   - Confirm the target guard prints exactly `pve-test` using:
     - `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'`
   - Confirm the live stack inventory and stack metadata agree on the new VMIDs.
   - Use the current branch state; do not revert or discard intended changes.

2. Run the non-destructive validation path first.
   - Run:
     - `./scripts/teardown-deploy-test.sh source-preflight`
     - `./scripts/teardown-deploy-test.sh live-preflight`
     - `./scripts/teardown-deploy-test.sh platform-status`
     - `./scripts/teardown-deploy-test.sh approval-preflight`
   - If source files changed during this pass, also run the required scans for
     repo policy:
     - `/home/steve/.local/bin/snyk iac test terraform/`
     - `./with-secrets /home/steve/.local/bin/sonar-scanner`

3. Create the approval packet yourself instead of stopping to ask what format it
   should use.
   - Put it under:
     - `docs/teardown-test/packets/<stamp>.md`
   - It must satisfy the checks documented in
     `docs/teardown-test/repeatable-test.md`.
   - Include:
     - matching `stamp:`
     - `target: pve-test`
     - `approved commit SHA: <current HEAD>`
     - non-empty `outage window:`
     - non-empty `rollback deadline:`
     - non-empty `scope approval:`
     - non-empty `scope exclusions:`
     - `service evidence:` with explicit `backup evidence path:` entries for:
       `step-ca`, `authentik`, `harbor`, `netbox`, `monitoring`, `portainer`
     - `recreatable services evidence:` with explicit `backup evidence path:`
       entries for:
       `apt-cacher`, `ci-runner`, `dns`, `proxy`
   - If backup evidence is advisory or intentionally absent for `pve-test`,
     say so clearly in the packet rather than leaving placeholders.

4. Run the full destructive cycle through the harness.
   - Use the harness primary path, not an improvised manual sequence.
   - Use:
     - `./scripts/teardown-deploy-test.sh cycle --execute --approval-text "approve" --approval-packet <packet> --stamp <stamp>`
   - Let the harness drive destroy, foundation redeploy, edge redeploy, edge
     activation, platform redeploy, and final validation.

5. If the cycle fails, fix genuine source problems and continue intelligently.
   - Prioritize issues in:
     - stack `vmid` / IP / inventory drift
     - teardown harness assumptions tied to old VMIDs
     - active docs used by the harness
     - validation steps that still assume the previous VMID layout
   - Avoid unrelated cleanup.
   - If a failure is environmental or access-related, prove that with exact
     command output and evidence paths rather than masking it.
   - After a real fix, re-run the smallest necessary validation path and then
     re-run the full cycle if needed.

6. Finish with a clear closeout.
   - Summarize whether the full teardown + redeploy gate passed.
   - List the evidence stamp, approval packet path, and main evidence
     directory.
   - Summarize any fixes made during the run.
   - If the gate failed, leave a short exact blocker list with commands, files,
     and evidence paths.

Working rules

- Follow the repo workflow and target-guard rules exactly.
- Keep all live secret-bearing commands behind `./with-secrets`.
- Prefer the harness over manual destroy/apply commands.
- Do not broaden into unrelated refactors or doc sweeps.
- Do not stop for routine success confirmations.
- Stop only for:
  - a true validation failure
  - an environment/access blocker
  - unrelated dirty-tree risk
  - a new issue that would make destructive execution unsafe

Definition of done for this pass

- The branch has been validated through the intended teardown/deploy harness
  flow, or the exact blocker has been proven with evidence.
- The VMID-schema branch has either passed the full gate or has a short,
  concrete blocker list.
- Evidence and outcome are summarized clearly enough for the operator to decide
  whether to promote or keep iterating on `work/vmid-zone-schema`.
