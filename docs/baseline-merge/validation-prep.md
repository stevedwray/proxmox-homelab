# Empty pve-test Validation Prep

Date: 2026-05-25
Prepared by: GitHub Copilot
Target branch: `work/baseline-convergence-01`
Target environment: `pve-test` only

## Purpose

This runbook prepares a real rebuild-gate validation from an empty `pve-test`
environment without executing the destructive flow in this planning pass.

It is branch-specific to the reviewed convergence state on
`work/baseline-convergence-01`.

## Reviewed Slice Summary

The branch now includes the reviewed convergence work needed for an empty
`pve-test` rebuild attempt:

- slice 1 stack target de-hardcoding
- slice 2 runtime fixes
- slice 2 SDN regression relaxation for deferred producer hints
- wrapper plus env overlay handling for `pve-test`
- env template layering fix
- producer contract updates in `terraform/lxc/main.tf` and `inventory.tpl`
- zone-members consumer fix
- refreshed `pve-test` network manifest commentary aligned with the current
  `192.168.x` lab contract

## Readiness Summary

The branch is not yet ready for an actual empty-`pve-test` rebuild gate.

The current runbook cannot be executed truthfully from a clean sibling worktree
at plain `HEAD` because the reviewed convergence state is still uncommitted and
`.env.pve-test.template` is still untracked in the current workspace.

The exact prerequisite checkpoint is:

- capture the reviewed `work/baseline-convergence-01` convergence state in a
  reproducible git checkpoint that contains the reviewed tracked changes
- add `.env.pve-test.template` to that same checkpoint so the gate worktree can
  materialize `.env.pve-test` locally from repository content

Until that checkpoint exists, this branch state should be treated as validation
planning only, not gate-runnable.

Once that checkpoint exists, all of the following must still be true before the
real run:

- the run is executed from a clean worktree at that checkpoint
- operator-local `.env` and `.env.pve-test` exist in that worktree
- the SOPS age key and `terraform/secrets.enc.yaml` are available
- the MikroTik side of the `pve-test` SDN contract already exists
  VLAN interfaces, gateway IPs, DNS behavior, and firewall policy are still an
  out-of-band prerequisite for direct routed access
- `pve-test` is truly disposable/empty; otherwise use the approval-packet path
  instead of `--disposable`

The current workspace remains unsuitable for the real gate because
`scripts/teardown-deploy-test.sh` requires a clean tree for mutating phases and
this worktree is already dirty.

## Required Checkpoint Before Any Clean Worktree

Do not create the gate worktree from plain `HEAD` in the current branch state.
First create or obtain the checkpoint commit that captures the reviewed dirty
worktree, including `.env.pve-test.template`.

Record that commit as `CHECKPOINT_COMMIT`, then materialize the clean gate
worktree from that exact commit.

```bash
cd /home/steve/git/proxmox-homelab
CHECKPOINT_COMMIT="<commit-containing-reviewed-convergence-state>"
git worktree add ../proxmox-homelab-empty-gate "$CHECKPOINT_COMMIT"
cd ../proxmox-homelab-empty-gate
```

Only after that checkpoint-backed worktree exists should you create the
required operator-local non-secret overlays there.

```bash
cp .env.template .env
cp .env.pve-test.template .env.pve-test
```

Adjust only non-secret values in `.env` and `.env.pve-test` as needed for the
operator environment.

If `CHECKPOINT_COMMIT` does not exist yet, stop here. The remaining sections
describe the executable flow only after that prerequisite is satisfied.

## Exact Preflight Checks

Run these checks in order from the clean checkpoint-backed worktree.

### 1. Repo And Overlay Presence

```bash
cd /home/steve/git/proxmox-homelab-empty-gate

test -f .env
test -f .env.pve-test
test -f .env.pve-test.template
test -f terraform/secrets.enc.yaml
test -f ~/.config/sops/age/keys.txt
bash scripts/check-required-sops-keys.sh
```

### 2. Wrapper Target Guard

```bash
./with-secrets bash -c 'echo "PVE_ENV=$PVE_ENV node=$TF_VAR_proxmox_node host=$TF_VAR_proxmox_host workspace=$TF_WORKSPACE"'
./with-secrets bash -c '[[ "$PVE_ENV" == "pve-test" ]]'
./with-secrets bash -c '[[ "$TF_VAR_proxmox_node" == "pve-test" ]]'
```

Expected result:

- `PVE_ENV=pve-test`
- `TF_VAR_proxmox_node=pve-test`
- `TF_WORKSPACE=pve-test`

### 3. Worktree Cleanliness

```bash
git status --short
```

Expected result: no output.

If this worktree is not clean, or if `.env.pve-test.template` is absent, the
checkpoint is not the reviewed convergence state and the gate run must not
continue.

### 4. Empty-Environment Reality Check

Use the harness inventory and status view before any mutating action.

```bash
STAMP="$(date -u +%Y%m%d-%H%M%S)-empty-pve-test"
scripts/teardown-deploy-test.sh plan --stamp "$STAMP"
scripts/teardown-deploy-test.sh platform-status --stamp "$STAMP"
./scripts/rebuild-gate-destroy.sh --dry-run
```

Expected result:

- `plan` shows the approved deploy and destroy stack sets from
  `docs/teardown-test/inventory.md`
- `platform-status` shows stacks absent or otherwise not serving
- `rebuild-gate-destroy.sh --dry-run` reports only no-op/absent actions for the
  target VMIDs

Stop if any active stack/container is still present and the environment is not
actually disposable.

### 5. Source-Only Harness Preflight

For an empty environment, use `source-preflight` rather than `live-preflight`
or `approval-preflight`.

```bash
scripts/teardown-deploy-test.sh source-preflight --stamp "$STAMP" --require-clean
```

Reason:

- `live-preflight` and `approval-preflight` currently expect deployed DNS,
  routed ingress, and active services, so they are not valid first checks for
  an empty `pve-test`

## Exact `.generated/` Regeneration Steps

There are three generated surfaces relevant to the rebuild gate.

### 1. Zone Members Index

Regenerate before the real run if any active `pve-test` stack networking changed
since the last generated file update. This is recommended even for a clean empty
rebuild because the branch now intentionally consumes the generated file via the
fixed template-aware path.

```bash
python3 terraform/lxc/generate-zone-members-index.py \
  --network-intent terraform/lxc/network/pve-test.yaml \
  --output terraform/lxc/network/pve-test.zone-members.yaml
```

### 2. Generated Traefik Config

```bash
rm -rf terraform/lxc/.generated/traefik
python3 terraform/lxc/render-edge-traefik.py --json
```

### 3. Generated CoreDNS Zone

```bash
rm -rf terraform/lxc/.generated/coredns
python3 terraform/lxc/render-edge-coredns.py --json
```

Notes:

- `source-preflight` already removes and regenerates `.generated/traefik` and
  `.generated/coredns`
- `deploy-edge` and `activate-edge` also regenerate those edge artifacts inside
  the harness
- the current harness does not regenerate `network/pve-test.zone-members.yaml`
  for you, so keep that step explicit in the operator runbook

## Exact Empty-Environment Rebuild Gate Sequence

Use disposable mode only if `pve-test` is confirmed empty and no backup/approval
packet flow is required.

### Phase 0. Optional Manual Generation Snapshot

```bash
python3 terraform/lxc/generate-zone-members-index.py \
  --network-intent terraform/lxc/network/pve-test.yaml \
  --output terraform/lxc/network/pve-test.zone-members.yaml
rm -rf terraform/lxc/.generated/traefik terraform/lxc/.generated/coredns
python3 terraform/lxc/render-edge-traefik.py --json
python3 terraform/lxc/render-edge-coredns.py --json
```

### Phase 1. Read-Only Gate Prep

```bash
scripts/teardown-deploy-test.sh source-preflight --stamp "$STAMP" --require-clean
scripts/teardown-deploy-test.sh plan --stamp "$STAMP"
scripts/teardown-deploy-test.sh platform-status --stamp "$STAMP"
./scripts/rebuild-gate-destroy.sh --dry-run
```

### Phase 2. Execute The Disposable Empty-Environment Cycle

```bash
APPROVAL_TEXT="${TEARDOWN_REQUIRED_APPROVAL_PHRASE}"
scripts/teardown-deploy-test.sh cycle \
  --execute \
  --disposable \
  --approval-text "$APPROVAL_TEXT" \
  --stamp "$STAMP"
```

What `cycle` runs, in order:

1. `destroy`
2. `deploy-foundation`
3. `deploy-edge`
4. `activate-edge`
5. `deploy-platform`
6. `final-validation`

### Phase 3. Post-Run Read-Only Confirmation

```bash
scripts/teardown-deploy-test.sh status --stamp "$STAMP"
scripts/teardown-deploy-test.sh platform-status --stamp "$STAMP"
```

## Expected Stack Order

The tracked harness inventory currently resolves the approved deploy order as:

1. `apt-cacher-stack`
2. `ci-runner-01`
3. `dns-stack`
4. `step-ca-stack`
5. `proxy-stack`
6. `authentik-stack`
7. edge reconciliation activation
8. `harbor-stack`
9. `monitoring-stack`
10. `netbox-stack`
11. `portainer-stack`

The tracked destroy order is:

1. `portainer-stack`
2. `netbox-stack`
3. `monitoring-stack`
4. `harbor-stack`
5. `authentik-stack`
6. `step-ca-stack`
7. `proxy-stack`
8. `dns-stack`
9. `ci-runner-01`
10. `apt-cacher-stack`

## Evidence To Capture

All gate evidence is expected under:

`docs/teardown-test/evidence/$STAMP/`

Required evidence artifacts:

- `state.json`
- `logs/teardown-deploy-test-$STAMP.log`
- `logs/git-status-short.log`
- `logs/render-edge-traefik.log`
- `logs/render-edge-coredns.log`
- `logs/platform-status.log`
- `logs/platform-status.tsv`
- `logs/platform-status.json`
- `logs/backup-gating.log`

Recommended operator notes to add alongside the scripted evidence:

- exact clean-worktree path used for the live run
- commit SHA used for the run
- whether `--disposable` was used because `pve-test` was empty
- any manual MikroTik or DNS prerequisites verified before the run

## Pass Criteria

The empty-`pve-test` rebuild gate passes only if all of the following are true:

- wrapper target guard resolves to `pve-test`
- `source-preflight` passes
- pre-run `platform-status` shows the environment empty or otherwise clearly
  disposable
- `cycle` completes with all contained phases marked `passed` in `state.json`
- `final-validation` passes its DNS, HTTPS route, Harbor, Portainer, Authentik,
  and edge-reconcile dry-run checks
- post-run `platform-status` shows every in-scope stack present and healthy
  enough for its expected smoke check
- no unexpected target drift appears in any guarded phase

## Fail Or Stop Conditions

Stop immediately if any of these occur:

- `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` returns anything other
  than `pve-test`
- `.env` or `.env.pve-test` is missing in the gate worktree
- the SOPS age key or `terraform/secrets.enc.yaml` is unavailable
- the gate worktree is dirty before a mutating phase
- `platform-status` shows surviving state that means `pve-test` is not actually
  empty/disposable
- `source-preflight` fails any offline validation, render assertion, unit test,
  or ansible syntax check
- `cycle` fails any contained phase
- `final-validation` fails DNS, HTTPS route, Harbor registry, Portainer API,
  Authentik health, or reconcile-edge dry-run checks

## Known Blockers And Assumptions Before A Real Run

1. The current workspace is dirty, so the actual gate must run from a clean
   sibling worktree or another clean checkout at the same commit.

2. The harness task metadata in the workspace references
   `scripts/validate-environment.sh`, but that file is not present in the repo.
   This is not a blocker for the rebuild gate because the current harness does
   not depend on it.

3. `live-preflight` and `approval-preflight` are currently shaped for an already
   deployed environment. For an empty `pve-test`, they should not be treated as
   go/no-go gates before the first rebuild cycle.

4. The `pve-test` network manifest now documents the `192.168.10/20/30/40`
   VLAN contract, but successful routed service access still assumes the
   MikroTik-side VLAN interfaces, gateway IPs, DNS delegation behavior, and
   firewall policy already exist.

5. `with-secrets` is worktree-root sensitive. If the real gate uses a sibling
   worktree, that worktree must contain the operator-local `.env` and
   `.env.pve-test` files in its own repo root.

6. Use `--disposable` only if the operator confirms the environment is truly
   empty and there is no backup-preservation requirement. If that assumption is
   false, switch to the non-disposable path and provide a real approval packet.
