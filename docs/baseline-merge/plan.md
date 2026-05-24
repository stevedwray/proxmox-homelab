# Baseline Merge Execution Plan

## Goal

Backport the productionization changes that materially affect lifecycle
behavior from `prod/pve-infra` into `baseline/teardown-validated`, while
keeping branch differences mostly in environment inputs, production-only
wrappers, and approval handling.

This plan exists so later credential-management and data-preservation work can
be developed on `pve-test` with confidence that the same core code paths will
hold on `pve`.

## Non-Goals

- blindly merging `prod/pve-infra` into `baseline/teardown-validated`
- carrying evidence snapshots or session handoffs into the baseline branch
- making `baseline/teardown-validated` production-targeting by default
- rewriting the repo branch model again as part of the backport

## Working Branches

### Production Branch

- source of truth for validated production behavior:
  `prod/pve-infra`

### Backport Branch

Start from baseline and do the convergence there:

```bash
git checkout baseline/teardown-validated
git pull --ff-only origin baseline/teardown-validated
git checkout -b work/baseline-convergence-01
```

## Preconditions

Before backport work starts:

- `prod/pve-infra` is clean and pushed
- `baseline/teardown-validated` is up to date locally
- no evidence or handoff material is intended for merge
- the operator is willing to run a full teardown/redeploy gate on `pve-test`
  before promotion

## Phase 0: Diff Freeze

Generate and save a working diff inventory before selecting changes:

```bash
git diff --name-status baseline/teardown-validated..prod/pve-infra
git diff --stat baseline/teardown-validated..prod/pve-infra
```

Also generate a review set that excludes evidence and handoffs:

```bash
git diff --name-only baseline/teardown-validated..prod/pve-infra \
  | rg -v '^docs/productionize-refactor/(evidence|handoffs)/'
```

## Phase 1: Delta Classification

Every changed path between the branches should land in one of four buckets:

| Bucket | Meaning | Merge intent |
|---|---|---|
| `must-backport` | Needed for lifecycle parity, targeting correctness, or teardown/redeploy success on `pve-test` | Backport now |
| `should-backport` | Useful for future work or operational clarity, but not strictly required for the first teardown gate | Backport if low-risk |
| `prod-only` | Specific to production wrappers, production-only evidence planners, or `pve` operations | Keep out of baseline |
| `ignore-artifact` | Evidence, handoffs, local-only material | Never merge |

### Initial Review Inventory

These path groups should be reviewed first.

#### `must-backport` candidates

- `scripts/provision.sh`
- `scripts/teardown-deploy-test.sh`
- `terraform/lxc/main.tf`
- `terraform/lxc/variables.tf`
- `terraform/lxc/templates/inventory.tpl`
- `terraform/lxc/PLATFORM_CONTRACT.md`
- `terraform/lxc/reconcile-edge.py`
- `terraform/lxc/generate-zone-members-index.py`
- `terraform/lxc/ansible/playbooks/deploy-*`
- `terraform/lxc/ansible/roles/harbor_postconfigure/*`
- `terraform/lxc/stacks/*/stack.yaml`
- `terraform/lxc/stacks/*/terragrunt.hcl`
- `terraform/lxc/stacks/*/STACK_CONTRACT.md`
- `terraform/lxc/network/pve-test.yaml`
- `.github/workflows/validate.yml`
- `.github/workflows/security-scan.yml`

#### `should-backport` candidates

- `AGENTS.md`
- `.github/copilot-instructions.md`
- `docs/stack-lifecycle-refactor/README.md`
- `docs/stack-lifecycle-refactor/day-2-credential-rotation.md`
- `docs/productionize-refactor/README.md`
- `docs/productionize-refactor/pve-production-readiness.md`
- `docs/reference/production-credentials.md`
- `terraform/README.md`

#### `prod-only` candidates

- `with-secrets-prod`
- `terraform/secrets.pve.enc.yaml`
- `.env.pve`
- `.env.pve.template`
- `terraform/lxc/network/pve.yaml`
- `terraform/lxc/storage/pve.yaml`
- `docs/productionize-refactor/pve-infra-teardown-inventory.md`
- `docs/productionize-refactor/15-pve-infra-only-teardown-planner.md`
- `scripts/plan-pve-infra-teardown.sh`
- `scripts/preflight-production-mikrotik.py`
- `scripts/preflight-production-mikrotik.sh`

#### `ignore-artifact`

- `docs/productionize-refactor/evidence/**`
- `docs/productionize-refactor/handoffs/**`

## Phase 2: Backport Selection

Create a tracked checklist in the convergence branch and record each selected
path with:

- source commit or branch comparison note
- bucket
- rationale
- merge status
- validation impact

Recommended format:

| Path | Bucket | Why it matters on `pve-test` | Status |
|---|---|---|---|
| `scripts/provision.sh` | `must-backport` | Shared stack reconcile path | pending |

The key discipline here is to backport behavior, not noise.

## Phase 3: Implementation Order

Apply backports in this order so failures are easier to reason about.

### 1. Guardrails and shared wrappers

- `with-secrets`
- `.env` / `.env.template` / `.env.pve-test*` changes that affect targeting
- CI workflow updates that reflect the new branch model

### 2. Shared Terraform and generated artifact logic

- `terraform/lxc/main.tf`
- `terraform/lxc/variables.tf`
- `terraform/lxc/templates/inventory.tpl`
- stack manifest schema changes
- network manifest updates required for pve-test parity

### 3. Shared stack deployment behavior

- `scripts/provision.sh`
- `terraform/lxc/ansible/playbooks/*`
- shared roles and reconcilers

### 4. Stack-specific bug fixes

Prioritize the services that were actively fixed during productionization:

- `portainer-stack`
- `harbor-stack`
- `netbox-stack`
- `monitoring-stack`
- `authentik-stack`
- `step-ca-stack`

### 5. Operator-facing docs

Backport only the docs that help future work on baseline:

- branch model / workflow instructions
- stack lifecycle credential notes
- concise productionization summaries that explain shared code behavior

## Phase 4: Validation On `pve-test`

The convergence branch is not promotable until the teardown/redeploy gate
passes on `pve-test`.

Minimum validation sequence:

1. Confirm targeting guard:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
```

Expected result: `pve-test`

2. Run the validation harness preflight:

```bash
./scripts/teardown-deploy-test.sh approval-preflight --require-clean
```

3. Run the teardown/redeploy cycle from the convergence branch.

4. Re-run stack health checks for the current baseline inventory.

5. If any stack needs manual recovery, stop and treat the backport as failed.

## Phase 5: Promotion

Merge `work/baseline-convergence-01` into
`baseline/teardown-validated` only if:

- the teardown/redeploy cycle passed
- the post-redeploy stack set is healthy
- branch differences are reduced to environment-specific handling and
  production-only safety layers

After merge:

- cut new work branches for credential-management and data-preservation from
  the refreshed baseline head

## Acceptance Criteria

The convergence work is complete when all of the following are true:

- `baseline/teardown-validated` and `prod/pve-infra` share the same core
  lifecycle logic for stack deploy and reconcile
- the known productionization fixes that affect runtime behavior are present on
  baseline
- `pve-test` teardown/redeploy succeeds from the convergence branch
- future refactor work can use `baseline/teardown-validated` as a realistic
  proving ground instead of testing first on `pve`

## Rollback Criteria

Stop the convergence stream and reassess if any of these happen:

- the backport requires production-only secrets or wrappers to behave on
  `pve-test`
- the teardown harness starts targeting anything other than `pve-test`
- stack behavior diverges in a way that cannot be explained by variables or
  environment manifests
- the backport introduces more branch-specific logic instead of reducing drift

## Outputs

This workstream should produce:

- a backport checklist committed on the convergence branch
- the validated code changes on `work/baseline-convergence-01`
- evidence of a successful `pve-test` teardown/redeploy gate
- a merge into `baseline/teardown-validated`
