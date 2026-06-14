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

Known good checks from the current harness baseline (last verified 2026-06-13,
`pve-test-vm`, commit `f4d1f25`):

- `bash -n scripts/teardown-deploy-test.sh`
- `shellcheck scripts/teardown-deploy-test.sh`
- `scripts/teardown-deploy-test.sh --help`
- `scripts/teardown-deploy-test.sh plan`
- `scripts/teardown-deploy-test.sh status --stamp <stamp>`
- mutating phase refusal without `--execute`
- `source-preflight` passed without network access to `pve-test-vm`
- `live-preflight` passed with network access to `pve-test-vm`
- `approval-preflight` passed (clean tree, branch/commit capture, source + live)
- `platform-status` passed (read-only inventory + container state snapshot)
- `final-validation` passed against the rebuilt platform
- full `cycle --execute` passed end-to-end on `pve-test-vm`

Live dry-runs need network access to resolve `authentik-int.${LAB_DOMAIN}:9443`.
Sandboxed environments that block outbound network access will fail at the
`authentik-direct-health` and `reconcile-edge-dry-run` steps.

## Work Needed

### 1. Implemented: Backup And Approval Gates (schema formalization pending)

Approval packet gates are implemented and proved in the 2026-05-17 cycle.

Current implementation:

- `scripts/teardown-deploy-test.sh` requires `--approval-packet PATH` for
  `destroy` and `cycle`.
- The harness validates structured approval packet fields before any Terragrunt
  destroy: `stamp`, `target`, `approved commit SHA`, outage/rollback fields,
  scope fields, and explicit `backup evidence path` entries for required
  non-loss services (plus recreatable-service evidence or explicit approval).
- The harness records approval packet SHA256 under the evidence stamp.

Remaining open item:

- Consider promoting the packet format to a tracked template or machine-readable
  schema once operators agree on long-term field names. Until then, packet
  structure is validated by heuristic field checks in the harness.

Acceptance criteria (already met):

- Destructive runs cannot start from an ad hoc command alone.
- The approval packet and harness evidence share the same stamp.
- Missing step-ca/Auth/Harbor/NetBox backup evidence blocks destroy.

### 2. Strengthen Validation Semantics

Some current checks only prove that a command returned success, not that the
observed behavior is the expected behavior.

Next step:

- Parse and assert important outputs:
  - DNS answers equal `${lab_ip_proxy}` for browser hosts.
  - Harbor `/v2/` returns native registry auth behavior, not an Authentik redirect.
  - Grafana uses native login/OIDC rather than Traefik forward-auth.
  - Portainer direct API uses `http://${lab_ip_portainer}:9000/api/system/status`.
  - Final reconciler dry-run reports no issues and no writes.
- Add per-service validation functions with clear expected status codes.

Acceptance:

- A wrong HTTP status or DNS answer fails the phase.
- Failure messages identify expected and observed values.
- OP-28 false positives from the first rehearsal cannot recur silently.

### 3. Improve Evidence And Reporting

The harness writes logs, but it should also produce a concise tracked-safe
summary.

Next step:

- Generate `summary.md` under the evidence stamp.
- Generate an optional tracked report skeleton under
  `docs/teardown-test/artifacts/reports/<stamp>.md`.
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

### 4. Add A Test Layer For The Harness Itself

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

### 5. Add Concurrency And Target Locks

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

### 6. Decide CI Integration Boundaries

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

1. Refine approval packet validation (item 1 above) so checks are structural
   rather than heuristic.
2. Add harness self-tests for approval and no-execute safety gates (item 4).
3. Re-run source-only validation, live validation, and plan resolution to
   confirm baseline is still green.
4. Only after those are stable, consider another approved destructive cycle.

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
