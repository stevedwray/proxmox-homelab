# Teardown/Deploy Harness Roadmap

This document is the development handoff for turning the teardown/deploy
rehearsal into a reusable test harness/playbook.

The current working direction is sound: preserve the safety model from the
one-off rehearsal, make non-destructive checks cheap to run during development,
and keep destructive operations behind explicit approval gates. The remaining
work is to make the harness less hard-coded, more observable, and easier to run
repeatably without inventing procedure during each cycle.

## Target Shape

The finished harness should provide three layers:

1. **Development preflight**
   - Non-destructive.
   - Runs against in-progress work.
   - Validates source, manifests, renderers, generated artifacts, and dry-runs.
   - Produces evidence without requiring a clean tree unless requested.

2. **Read-only live validation**
   - Non-mutating checks against the current `pve-test` platform.
   - Verifies VMID/IP inventory, DNS, HTTPS routes, direct service health, auth
     behavior, and final reconciler no-op status.
   - Safe to run while normal development is happening.

3. **Approved destructive cycle**
   - Destroys and rebuilds the platform in the documented order.
   - Re-runs the `pve-test` target guard before every live operation.
   - Requires backup evidence, outage/rollback window approval, clean source,
     and explicit operator approval.
   - Can stop and resume from phase boundaries using the same evidence stamp.

## Current Prototype

The prototype harness lives at:

```text
scripts/teardown-deploy-test.sh
```

The operator-facing description lives at:

```text
docs/teardown-test/repeatable-test.md
```

Known good checks from the current harness baseline:

- `bash -n scripts/teardown-deploy-test.sh`
- `shellcheck scripts/teardown-deploy-test.sh`
- `scripts/teardown-deploy-test.sh --help`
- `scripts/teardown-deploy-test.sh plan`
- `scripts/teardown-deploy-test.sh status --stamp <stamp>`
- mutating phase refusal without `--execute`
- `source-preflight` passed without network access to `pve-test`
- `live-preflight` passed with network access to `pve-test`
- `final-validation` passed against the current rebuilt platform

The first sandboxed live dry-run failed at Authentik discovery with
`Operation not permitted`; rerunning with network access passed. That means the
split design is fine, but future agents should remember that live dry-runs need
network permission in this execution environment.

## Work Needed

### 1. Completed: Separate Offline, Live Read-Only, And Mutating Checks

Status:

- `source-preflight`, `live-preflight`, and `approval-preflight` should remain
  the default structure for future work.
- `preflight` remains a backwards-compatible alias for source plus live
  preflight.

Keep:

- Keep `source-preflight` fully offline and source-only.
- Keep `live-preflight` strictly read-only and explicit about environment
  reachability failures.
- Keep `approval-preflight` as the go/no-go check before a destructive approval
  packet.

Acceptance:

- A developer can run a fully offline/source-only check.
- A live check failure is clearly categorized as environment/service reachability,
  not source validation failure.
- The destructive cycle requires the stronger approval preflight.

### 2. Completed: Replace Hard-Coded Inventory With A Source Of Truth

Status:

- The harness resolves foundation, edge, platform, and destroy orders from
  `docs/teardown-test/inventory.md`.
- The special non-Terraform edge activation step remains explicit as
  `activate-edge`.
- Inventory VMID/IP values are checked against each stack's `stack.yaml` before
  a resolved plan is returned.
- `scripts/teardown-deploy-test.sh plan` displays the resolved order without
  running any live mutating command.

Keep:

- Treat `docs/teardown-test/inventory.md` as the human-readable execution order.
- Treat `stack.yaml` VMID/IP values as the source metadata that inventory must
  match.
- Fail fast if the inventory and source metadata drift.

Acceptance:

- Adding/changing a stack requires updating source inventory only once.
- The harness reports the resolved order before any destructive phase.
- A mismatch between docs and `stack.yaml` blocks destructive execution.

### 3. Completed: Make Resume State Explicit

Status:

- The harness now writes `docs/teardown-test/evidence/<stamp>/state.json`.
- Each tracked phase records `pending`, `running`, `passed`, or `failed`
  checkpoint state with timestamps, exit status, evidence directory, log paths,
  branch, commit, dirty-tree context, and resolved stack specs where relevant.
- `scripts/teardown-deploy-test.sh status --stamp <stamp>` provides a read-only
  summary view with failed command/log details and a suggested next phase.

Keep:

- Preserve `state.json` as the machine-readable checkpoint source of truth for a
  run stamp.
- Keep `status --stamp <stamp>` read-only.
- Keep phase wrappers responsible for writing failed state before exiting.

Acceptance:

- A later session can answer "what is done, what failed, what is next?"
  without reading every log.
- Resume suggestions are generated from the state file.

### 4. Active Next Step: Encode Backup And Approval Gates

The script currently checks for an approval phrase, but it does not verify backup
evidence or operator window metadata.

Next step:

- Require an approval packet file for `destroy` and `cycle`.
- Validate that the packet contains:
  - evidence stamp
  - approved commit SHA
  - target guard result
  - stack scope
  - outage window
  - rollback deadline
  - backup evidence paths for non-loss services
  - explicit data-loss approval for recreatable services
- Refuse destructive phases if the packet is missing or stale.

Acceptance:

- Destructive runs cannot start from an ad hoc command alone.
- The approval packet and harness evidence share the same stamp.
- Missing step-ca/Auth/Harbor/NetBox backup evidence blocks destroy.

### 5. Strengthen Validation Semantics

Some current checks only prove that a command returned success, not that the
observed behavior is the expected behavior.

Next step:

- Parse and assert important outputs:
  - DNS answers equal `10.57.2.10` for browser hosts.
  - Harbor `/v2/` returns native registry auth behavior, not an Authentik redirect.
  - Grafana uses native login/OIDC rather than Traefik forward-auth.
  - Portainer direct API uses `http://10.57.1.20:9000/api/system/status`.
  - Final reconciler dry-run reports no issues and no writes.
- Add per-service validation functions with clear expected status codes.

Acceptance:

- A wrong HTTP status or DNS answer fails the phase.
- Failure messages identify expected and observed values.
- OP-28 false positives from the first rehearsal cannot recur silently.

### 6. Improve Evidence And Reporting

The harness writes logs, but it should also produce a concise tracked-safe
summary.

Next step:

- Generate `summary.md` under the evidence stamp.
- Generate an optional tracked report skeleton under
  `docs/teardown-test/reports/<stamp>.md`.
- Include:
  - branch and commit
  - phase results
  - evidence paths
  - deviations
  - follow-up items
  - dirty tree note for development preflights
- Scrub secrets and avoid committing raw runtime logs.

Acceptance:

- The operator can review one summary after a run.
- The final report can be copied into tracked docs without secrets.
- Evidence remains ignored by default.

### 7. Add A Test Layer For The Harness Itself

Shell parsing and safety gates should be tested without touching `pve-test`.

Next step:

- Add shell tests with Bats or a lightweight repo-standard alternative.
- Test:
  - help output is side-effect free
  - missing approval text fails before live commands
  - mutating phase without `--execute` fails before target guard
  - approval phrase matching is case-insensitive
  - `--stamp` routes logs to the intended directory
  - inventory parsing detects mismatches
- Mock `with-secrets`, `terragrunt`, `ssh`, `curl`, and `dig`.

Acceptance:

- Harness safety behavior is covered in CI/local validation.
- Tests do not require network access or a running Proxmox host.
- A regression that would accidentally run a mutating command is caught.

### 8. Add Concurrency And Target Locks

The harness should prevent overlapping destructive runs.

Next step:

- Add a local lock file under the evidence root.
- Optionally add a remote `pve-test` lock marker for live destructive cycles.
- Include the evidence stamp, operator, PID, branch, and commit in the lock.
- Provide explicit unlock guidance for stale locks.

Acceptance:

- Starting a second destructive cycle while one is active fails immediately.
- Read-only validation can still run unless a destructive phase declares the
  platform unstable.

### 9. Decide CI Integration Boundaries

The full teardown/deploy cycle should not run in normal CI, but parts of the
harness can.

Next step:

- Add source-only preflight to local/CI validation if runtime is acceptable.
- Keep live read-only validation as a manual operator command.
- Keep destructive cycle manual only unless a future dedicated test environment
  and approval mechanism exists.

Acceptance:

- Pull requests can run source-only checks without pve-test access.
- Manual live checks are documented and easy to run before merging
  infrastructure-sensitive changes.
- Destructive actions are never triggered by an ordinary push.

## Suggested Next Session Plan

1. Keep the current prototype as the starting point.
2. Build on the split `source-preflight` / `live-preflight` /
  `approval-preflight` structure rather than adding new mixed preflight modes.
3. Build on inventory-derived plans rather than adding new hard-coded stack
   arrays.
4. Encode backup and approval packet validation.
5. Add harness self-tests for approval and no-execute safety gates.
6. Re-run source-only validation, live validation, plan resolution, and at least one mocked
   mutating phase test.
7. Only after those are stable, consider another approved destructive cycle.

## Non-Goals For The Next Session

- Do not automate backup creation until the backup evidence contract is clearer.
- Do not schedule periodic destructive tests.
- Do not run `cycle` automatically from CI.
- Do not change production `pve` behavior.
- Do not commit raw evidence logs or secret-bearing output.

## Open Decisions

- Whether `docs/teardown-test/inventory.md` should remain the primary execution
  order file long term, or whether a future machine-readable manifest should
  replace the markdown parser.
- Whether backup evidence should be validated by file presence, explicit
  operator attestations, or machine-readable backup metadata.
- Whether to use Bats for shell tests or keep tests as plain shell scripts.
- Whether read-only live validation should be allowed during an active
  destructive window.
- Whether public `certs/homelab-root.crt` drift should be tracked, ignored, or
  restored before the next cycle.
