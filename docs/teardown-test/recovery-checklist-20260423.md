# pve-test Recovery Checklist (2026-04-23)

Status: Read-only planning checklist only

## Hard Safety Boundary

This document is a strict read-only recovery checklist for the accidental partial
teardown incident.

Do not run any mutating command from this checklist unless a later session has
explicit operator approval for destructive/rebuild actions.

Forbidden in this session:

- no `terragrunt apply`
- no `terragrunt destroy`
- no Ansible publish runs
- no `reconcile-edge.py --apply`
- no `scripts/teardown-deploy-test.sh cycle`
- no state mutation of `pve-test`

If any command here appears mutating, treat it as planning-only and do not run
until explicitly approved.

## Inputs And References

- Assessment baseline: [recovery-assessment-20260423.md](recovery-assessment-20260423.md)
- Inventory source of truth: [inventory.md](inventory.md)
- Execution decomposition: [operations-plan.md](operations-plan.md)
- Operator command flow: [runbook.md](runbook.md)
- Harness behavior and phases: [repeatable-test.md](repeatable-test.md)
- Harness follow-up work: [harness-roadmap.md](harness-roadmap.md)
- Incident evidence stamp: [20260423-010300-destroy-refuse](evidence/20260423-010300-destroy-refuse)

## Target Guard (Read-Only)

Command:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
```

Expected output:

```text
pve-test
```

If output is anything other than `pve-test`, stop and treat as a targeting
error.

## Read-Only State Verification Commands

### 1. Current container inventory on pve-test

```bash
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct list"
```

Record output to the recovery evidence location (see stamp pattern below).

### 2. Per-VMID status checks for in-scope stacks

Run each command read-only:

```bash
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct status 120"   # portainer-stack
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct status 142"   # apt-cacher-stack
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct status 121"   # harbor-stack
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct status 141"   # ci-runner-01
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct status 151"   # dns-stack
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct status 153"   # proxy-stack
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct status 152"   # step-ca-stack
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct status 150"   # authentik-stack
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct status 154"   # monitoring-stack
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct status 143"   # netbox-stack
```

### 3. Optional non-mutating service reachability checks

These checks are read-only and should not change state:

```bash
dig @10.57.1.13 +short traefik.lab.gibbsgreatly.xyz
dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz
curl -skI --resolve traefik.lab.gibbsgreatly.xyz:443:10.57.2.10 https://traefik.lab.gibbsgreatly.xyz/
curl -fsS http://10.57.1.10:9000/-/health/live/
```

## Approved Deploy Order (Recovery Reference)

Use the inventory-approved deploy order exactly:

1. `portainer-stack`
2. `apt-cacher-stack`
3. `harbor-stack`
4. `ci-runner-01`
5. `dns-stack`
6. `proxy-stack`
7. `step-ca-stack`
8. `authentik-stack`
9. edge reconciliation activation
10. `monitoring-stack`
11. `netbox-stack`

## Recovery Decision Point (Required Before Any Mutation)

Choose one explicit path and record decision + approver in evidence:

- Option A: rebuild from earliest missing required dependency.
- Option B: complete destroy under a new explicit approval, then rebuild cleanly.
- Option C: preserve partial state for manual investigation.

No mutating command may run until one option is explicitly approved.

## Recovery Evidence Stamp Pattern

Use a dedicated recovery stamp directory:

```text
docs/teardown-test/evidence/<stamp>/recovery/
```

Recommended contents:

- `target-guard.txt`
- `pct-list.txt`
- `pct-status-<vmid>.txt`
- `service-readonly-checks.txt`
- `decision-record.md`
- `approved-execution-window.md` (only if a future session approves mutation)

## Recovery Execution Outline (Planning-Only)

All mutating steps below are placeholders and must remain blocked until explicit
operator approval.

1. Run target guard and log output (`pve-test` expected).
2. Collect read-only state snapshot (`pct list`, per-VMID status, optional reachability checks).
3. Confirm and record decision path (A/B/C).
4. If Option A or B is approved in a future session:
   - rerun target guard before each mutating phase.
   - run ordered stack rebuild in approved deploy order.
   - perform service checks after each stack.
   - execute edge activation sequence.
   - run final validation checks.
5. If Option C is approved:
   - keep state unchanged and continue manual investigation with read-only checks.

Planning-only placeholders (do not run until approved):

- stack apply commands
- any destroy commands
- edge publication commands
- `reconcile-edge.py --apply`

## Expected Post-Recovery Validation (After Approved Recovery Only)

After approved mutation and rebuild are completed, execute and record:

```bash
scripts/teardown-deploy-test.sh plan
scripts/teardown-deploy-test.sh source-preflight
scripts/teardown-deploy-test.sh live-preflight
scripts/teardown-deploy-test.sh final-validation
scripts/teardown-deploy-test.sh status --stamp <stamp>
```

These are the minimum completion checks before declaring recovery complete.

## Exit Criteria For This Checklist

This checklist run is complete only when:

- read-only snapshot is recorded under the recovery evidence stamp,
- a decision (A/B/C) is documented,
- no mutating command was executed.
