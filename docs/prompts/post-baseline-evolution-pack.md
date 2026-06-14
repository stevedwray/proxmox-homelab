# Post-Baseline Evolution Prompt Pack

This pack now serves two purposes:

1. record the already-completed post-baseline follow-up work
2. provide the next Copilot handoff for the highest-value remaining hardening
   slice

`baseline/teardown-validated` now includes:

- teardown harness hardening slice
- `dns_server` stack-contract cleanup
- Phase 06 replanning
- `step-ca` CA compromise/rotation runbook
- simplified homelab teardown approval flow
- successful teardown/redeploy closeout
  `docs/teardown-test/reports/20260516-235620.md`

Historical prompt status:

- Prompt 01: completed
- Prompt 02: completed
- Prompt 03: completed
- Prompt 04: completed
- Prompt 05: completed

The next useful work is not another broad post-baseline sweep. It is targeted
hardening of `platform-status`, then real Phase 06 execution planning.

## Next Prompt: Platform-Status Hardening

```text
You are working in /home/steve/git/proxmox-homelab.

Branch workflow:
1. Verify your current checkout is an active development branch or other
   non-promotion working HEAD.
2. Create a fresh short-lived branch for this work from the current working
   HEAD:
   - git checkout -b task/platform-status-hardening-01
3. Do not use baseline/teardown-validated or baseline/teardown-validated as the base for this
   branch. They are promotion targets only.
4. If your current checkout is baseline/teardown-validated or baseline/teardown-validated,
   stop and report a branch-base blocker instead of branching from it.
5. Do not work directly on a promotion target branch.
6. Do not merge anything at the end. Stop only after implementation,
   validation, issue workflow, commit, and a clear summary.

Workspace handling:
- If unrelated pre-existing working tree changes are present, leave them
  untouched and continue.
- Do not stop just to report unrelated modified files.
- Only stop if an existing uncommitted change directly conflicts with a file you
  must edit for this task.
- In the final report, distinguish clearly between:
  - files changed for this task
  - unrelated pre-existing modified files left untouched

Goal:
Harden `scripts/teardown-deploy-test.sh platform-status` so it remains
trustworthy after a successful rehearsal and does not falsely report the entire
platform as stopped when the operator host cannot resolve the Proxmox SSH
hostname.

Context:
- The latest successful teardown/redeploy cycle is:
  - docs/teardown-test/reports/20260516-235620.md
- The cycle itself passed, including final validation.
- A later `platform-status` rerun under the same stamp falsely reported all
  stacks as stopped because SSH to `pve-test.gibbsgreatly.xyz` failed local name
  resolution on the operator workstation.
- Relevant evidence:
  - docs/teardown-test/evidence/20260516-235620/logs/platform-status-*.log
  - docs/teardown-test/evidence/20260516-235620/logs/platform-status.json
  - docs/teardown-test/evidence/20260516-235620/logs/pct-status-*.log
  - docs/teardown-test/evidence/20260516-235620/logs/teardown-deploy-test-20260516-235620.log

Primary references:
- scripts/teardown-deploy-test.sh
- docs/teardown-test/repeatable-test.md
- docs/teardown-test/runbook.md
- docs/teardown-test/reports/20260516-235620.md
- docs/teardown-test/evidence/20260516-235620/logs/platform-status.json

Task:
1. Read the current platform-status implementation and the latest successful
   cycle evidence.
2. Diagnose exactly why platform-status produced a false `stopped` summary after
   a successful cycle.
3. Implement the smallest safe fix so platform-status either:
   - uses a more reliable host/address path for `pct status` checks, or
   - reports an explicit status-collection blocker instead of converting SSH
     name-resolution failure into `stopped`
4. Preserve the useful direct health checks and evidence output.
5. Update the teardown docs only where needed so the behavior and fallback are
   clear.
6. Finish the repo workflow completely:
   - use an existing suitable GitHub issue only if it exactly fits this slice
   - otherwise create a new narrow issue specifically for platform-status
     hardening
   - commit only this task’s files
   - use a commit message with Closes #N
   - run gh issue close N --comment "Fixed in commit <sha>"

Autonomy rules:
- Do not stop to ask whether the successful cycle or the later platform-status
  output is more authoritative; the cycle and direct final-validation logs are
  authoritative, and platform-status is the thing to harden.
- Do not stop to ask whether to update a small adjacent doc if it is needed for
  consistency; just do it.
- Prefer a coherent finished hardening slice over a minimal patch that still
  allows false “everything stopped” summaries.

Decision rule:
- Prefer the smallest implementation-grounded fix that improves operator trust.
- If there are multiple viable fixes, prefer one that makes failure mode
  explicit over silently guessing wrong state.
- Do not broaden into unrelated teardown-harness refactors in this prompt.

Validation:
- bash -n scripts/teardown-deploy-test.sh
- shellcheck scripts/teardown-deploy-test.sh
- run any relevant unit/source-only tests you add
- run safe non-mutating commands only, such as:
  - bash -lc 'source .env && ./scripts/teardown-deploy-test.sh --help'
  - bash -lc 'source .env && ./scripts/teardown-deploy-test.sh status --stamp 20260516-235620'
  - bash -lc 'source .env && ./scripts/teardown-deploy-test.sh platform-status --stamp 20260516-235620'
- run ./with-secrets /home/steve/.local/bin/sonar-scanner because shell code is touched
- do not run a destructive teardown cycle in this prompt

Stop only if:
- there is a direct uncommitted-file conflict in files you must edit
- required validation fails and you cannot resolve it safely within this slice
- GitHub issue creation/closure is impossible due to auth or network failure
- the current code path is so entangled that platform-status cannot be hardened
  safely without a broader redesign
If you stop, explain the exact blocker and the narrowest safe next step.

Done means done:
- the false stopped-summary behavior is fixed or safely reclassified as an
  explicit collection blocker
- relevant docs are updated if needed
- validations have been run
- issue workflow is completed
- commit is created
- branch remains unmerged

Deliver:
- the exact failure mode you found
- the fix you chose and why
- issue number
- commit sha
- files changed for this task
- validations/checks performed and outcomes
- whether the branch is clean except for any unrelated pre-existing modified
  files
- what the next harness hardening slice should be after this one
```

## After That

Once `platform-status` is trustworthy again, the next practical work should be:

1. real Phase 06 workload discovery and inventory capture
2. confirming or creating `app_seg` / `game_seg`
3. choosing the first application migration slice
