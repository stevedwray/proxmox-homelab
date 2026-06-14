# Repeatable Teardown/Deploy Test

This document describes the reusable harness for running the `pve-test`
teardown/deploy rehearsal during active development.

The harness is intentionally conservative. It makes the non-destructive checks
easy to run often, while keeping destroy, apply, and publish steps behind an
explicit execution flag and approval phrase.

## Harness

Use:

```bash
scripts/teardown-deploy-test.sh <phase> [options]
```

Evidence is written under:

```text
docs/teardown-test/artifacts/evidence/<stamp>/logs/
```

Machine-readable checkpoint state is written to:

```text
docs/teardown-test/artifacts/evidence/<stamp>/state.json
```

The script reuses the current workspace patterns:

- secrets and secret-bearing commands go through `./with-secrets`
- `pve-test` target guard is checked before live operations
- deploy/destroy stack order is resolved from `docs/teardown-test/inventory.md`
  and checked against each stack's `stack.yaml`
- generated edge artifacts are regenerated before publish
- logs and runtime evidence stay under ignored evidence directories
- full edge reconciler dry-runs use the direct Authentik URL
  `http://${lab_ip_authentik}:9000`

## Development Loop

During normal development, run the source-only preflight first:

```bash
scripts/teardown-deploy-test.sh source-preflight
```

This phase has no network or live `pve-test` dependency. It validates source,
removes and regenerates ignored edge artifacts, and records working tree state
without requiring a clean tree by default. Add `--require-clean` when you want
to use it as a stricter local gate:

```bash
scripts/teardown-deploy-test.sh source-preflight --require-clean
```

`source-preflight` checks:

- working tree state, with optional clean-tree enforcement
- edge manifest validation
- edge unit tests
- `git diff --check`
- fresh Traefik/CoreDNS render output
- generated artifact assertions for Traefik/CoreDNS output

Run the live read-only preflight when `pve-test` is up and reachable:

```bash
scripts/teardown-deploy-test.sh live-preflight
```

`live-preflight` checks:

- working tree state, with optional clean-tree enforcement
- `pve-test` target guard through `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'`
- lightweight DNS and routed HTTPS sanity for the edge entrypoint
- direct Authentik health
- full edge reconciler dry-run

If the execution environment blocks network access to `pve-test`, treat a
`live-preflight` failure as an environment/access blocker and do not weaken the
checks.

Use the read-only platform status phase when you need a current inventory-based
view of the in-scope containers:

```bash
scripts/teardown-deploy-test.sh platform-status
```

`platform-status` checks the approved inventory from
`docs/teardown-test/inventory.md` against each stack's `stack.yaml`, verifies
the `pve-test` target guard, captures `pct status`, Docker container snapshots,
listener snapshots, and a stack-specific direct health probe where one is
defined. It writes both a human table and machine-readable reports under the
evidence stamp:

- `logs/platform-status.log`
- `logs/platform-status.tsv`
- `logs/platform-status.json`

This phase is read-only. A degraded or missing stack is reported in the table;
the phase itself is an observation pass, not a repair action.

Socket-proxy disposable test: opt-in and proof expectations

The `docker-socket-proxy-test` disposable target is excluded by default. To run the proxy proof as part of a repeatable teardown-test cycle follow the opt-in steps described in `variables.md` (create a temporary inventory and run the harness via `TEARDOWN_INVENTORY_FILE`). The expected, repeatable proof covers the following checks and evidence capture:

- Target creation/deploy path: the harness deploy phase will run `terragrunt apply` for the test stack; expected evidence: `docs/teardown-test/evidence/<stamp>/logs/deploy-docker-socket-proxy-test.log` (contains terragrunt/apply output).
- Workload containers present: verify via Ansible raw/curl against the test LXC inventory. Example (ip resolved from stack.yaml):

```bash
IP=$(grep -E 'ip_address:' terraform/lxc/stacks/docker-socket-proxy-test/stack.yaml | sed -E 's/.*ip_address: ?"?([^" ]+)"?.*/\1/' | cut -d'/' -f1)
ansible -i terraform/lxc/stacks/docker-socket-proxy-test/inventory.yml docker-socket-proxy-test -m raw -u root -a "curl -sS 'http://$IP:2375/containers/json?all=1'" | tee docs/teardown-test/evidence/<stamp>/logs/proxy-probe.log
```

- Proxy reachable: the `proxy-probe.log` above should contain JSON output listing deployed containers (nginx/whoami/redis/docker-socket-proxy, etc.).
- `GET /containers/json?all=1` succeeds: the probe should return HTTP 200 and valid JSON; record `proxy-probe.log` under the evidence stamp.
- Mutating request is blocked: example check (expect HTTP 403):

```bash
ansible -i terraform/lxc/stacks/docker-socket-proxy-test/inventory.yml docker-socket-proxy-test -m raw -u root -a \
  "curl -sS -o /dev/null -w '%{http_code}' -XPOST -H 'Content-Type: application/json' -d '{\"Image\":\"alpine\"}' 'http://$IP:2375/containers/create'" \
  | tee docs/teardown-test/evidence/<stamp>/logs/proxy-mutating-test.log
# Expected result: 403
```

- Optional cleanup/removal: when running `cycle` (with `--disposable`) the destroy phase should remove the test LXC; expected evidence: `docs/teardown-test/evidence/<stamp>/logs/destroy-docker-socket-proxy-test.log` and the harness VMID verification logs.

Keep raw evidence under the standard evidence stamp (`docs/teardown-test/evidence/<stamp>/logs/`) and avoid committing raw evidence files. The temporary inventory remains local and reversible.

If `platform-status` cannot collect `pct status` because the operator host
cannot reach or resolve the Proxmox SSH host, that stack is reported as
`overall=blocked` with an explicit `status collection blocked` detail. This
prevents SSH collection failures from being misreported as container stop
states.

Use `approval-preflight` as the go/no-go check before preparing any destructive
approval packet:

```bash
scripts/teardown-deploy-test.sh approval-preflight
```

This phase always requires a clean working tree, records branch and commit, and
runs `source-preflight` plus `live-preflight` under the same evidence stamp.

`preflight` remains available as a backwards-compatible alias for
`source-preflight` followed by `live-preflight`. It preserves the historical
dirty-tree-by-default behavior while still honoring `--require-clean`.

Use the broader read-only live validation phase when the platform is expected to be up:

```bash
scripts/teardown-deploy-test.sh final-validation
```

This phase checks DNS, routed HTTPS behavior, direct Authentik/Portainer health,
Harbor `/v2/`, and a final full edge reconciler dry-run.

Use the plan phase to display the current inventory-derived execution order
without running any live mutating command:

```bash
scripts/teardown-deploy-test.sh plan
```

`plan` resolves foundation, edge, platform, and destroy orders from
`docs/teardown-test/inventory.md`. It fails if the inventory VMID/IP values drift
from the matching `terraform/lxc/stacks/<stack>/stack.yaml`.

Use the status phase to inspect checkpoint state for an existing evidence stamp:

```bash
scripts/teardown-deploy-test.sh status --stamp <stamp>
```

`status` is read-only. It summarizes:

- evidence stamp and evidence directory
- recorded branch and commit
- phase statuses from `state.json`
- failed command and log path when a phase failed
- suggested next phase based on the recorded checkpoint state

## Gated Live Phases

Mutating phases require both `--execute` and an approval phrase containing:

```text
approve
```

`destroy` and `cycle` also require an approval packet. The approval text itself
is intentionally simple; the approval packet is the detailed safety record:

```bash
scripts/teardown-deploy-test.sh destroy --execute \
  --approval-text "approve" \
  --approval-packet docs/teardown-test/artifacts/packets/20260423-010203.md \
  --stamp 20260423-010203
```

Minimum approval packet checks for destructive phases:

- packet file exists
- packet has a `stamp: <value>` field matching active `--stamp`
- packet has a `target: pve-test` field
- packet has `approved commit SHA: <sha>` and it matches current HEAD
- packet has non-empty `outage window:` and `rollback deadline:` fields
- packet has non-empty `scope approval:` and `scope exclusions:` fields
- packet includes `service evidence:` heading with explicit `backup evidence path:` entries for `step-ca`, `authentik`, `harbor`, `netbox`, `monitoring`, and `portainer`
- packet includes either:
  - `recreatable services evidence:` heading with explicit `backup evidence path:` entries for `apt-cacher`, `ci-runner`, `dns`, and `proxy`, or
  - `recreatable services approval:` text that explicitly accepts/acknowledges data loss or recreation

When accepted, the harness logs the packet path and records its SHA256 under the
evidence stamp (`logs/approval-packet.sha256`).

Example:

```bash
scripts/teardown-deploy-test.sh deploy-edge --execute \
  --approval-text "approve"
```

Available live phases:

| Phase | What it does |
| --- | --- |
| `destroy` | Destroys approved platform stacks in reverse inventory order. |
| `deploy-foundation` | Applies Portainer, apt-cacher, Harbor, and CI runner. |
| `deploy-edge` | Applies CoreDNS, Traefik, step-ca, and Authentik. |
| `activate-edge` | Regenerates edge artifacts, applies Authentik reconciliation, and publishes CoreDNS/Traefik. |
| `deploy-platform` | Applies monitoring and NetBox. |
| `cycle` | Runs destroy through final validation in order. |

The harness does not replace operator judgment. The packet gate blocks ad hoc
destructive commands, but operators should still review the packet before each
run.

## Resume Model

Each phase is independently runnable. If a phase fails:

1. Stop at the failed phase.
2. Run `scripts/teardown-deploy-test.sh status --stamp <stamp>` to inspect the
  machine-readable checkpoint summary.
3. Read the failing log under the active evidence stamp.
  The checkpoint state records relevant log paths under `state.json`.
3. If the failure is a source bug, fix it in a focused branch and rerun
  `source-preflight`.
4. Resume from the failed phase with the same `--stamp <stamp>` if continuing
   the same evidence packet.

Each tracked phase updates `state.json` from `pending` to `running`, then to
`passed` or `failed`, and records branch, commit, dirty-tree context, log paths,
and resolved stack specs where applicable.

Example:

```bash
scripts/teardown-deploy-test.sh deploy-edge --stamp 20260423-010203 --execute \
  --approval-text "approve"
```

## Relationship To The Runbook

The script is the commandable harness. The detailed policy remains in:

- `docs/teardown-test/decisions.md`
- `docs/teardown-test/inventory.md`
- `docs/teardown-test/backup-plan.md`
- `docs/teardown-test/operations-plan.md`
- `docs/teardown-test/runbook.md`

When those documents change, update the harness in the same branch so the
repeatable test continues to encode the current operating contract.

## Development Roadmap

The current harness is a working prototype, not the final reusable playbook.
Before treating it as the long-term test interface, complete the follow-up work
in [harness-roadmap.md](harness-roadmap.md). The next major implementation item
list there should be kept current.

Machine-readable resume state and checkpointing are already implemented through
per-stamp `state.json`. Do not leave roadmap prose behind when completed
features move into the harness.
