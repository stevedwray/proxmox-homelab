# Baseline Merge Checkpoint Readiness

Date: 2026-05-25
Prepared by: GitHub Copilot
Target branch: `work/baseline-convergence-01`

## Purpose

This document defines the exact reproducible checkpoint content required before
the real empty-`pve-test` rebuild gate can run from a clean worktree.

It is grounded in the live branch state from:

```bash
git status --short --branch
git diff --name-only
git ls-files --others --exclude-standard -- docs/baseline-merge .env.pve-test.template
```

## Current Branch-State Assessment

The branch still appears to match the reviewed convergence slice history at the
file-set level.

Evidence:

- the modified tracked files align with the reviewed slice summary already
  captured in `docs/baseline-merge/validation-prep.md`
- the non-ignored untracked files relevant to checkpoint portability are
  `.env.pve-test.template`, `docs/baseline-merge/validation-prep.md`, and this
  checkpoint manifest
- `docs/**/handoffs/` are ignored by `.gitignore`, so handbacks and prompts do
  not provide checkpoint portability

This pass did not re-review every hunk in every changed file. If any listed file
contains changes outside the reviewed convergence slices, the checkpoint is not
safe until that drift is resolved.

## Files That Belong In The Checkpoint

The checkpoint should contain exactly these tracked files.

### Runtime And Wrapper Files

- `.env.template`
- `.env.pve-test.template`
- `.gitignore`
- `with-secrets`
- `scripts/provision.sh`
- `scripts/teardown-deploy-test.sh`

### Terraform Core And Helper Files

- `terraform/lxc/generate-zone-members-index.py`
- `terraform/lxc/main.tf`
- `terraform/lxc/reconcile-edge.py`
- `terraform/lxc/templates/inventory.tpl`
- `terraform/lxc/variables.tf`
- `terraform/lxc/network/pve-test.yaml`

### Shared Ansible Runtime Files

- `terraform/lxc/ansible/playbooks/configure-keyctl.yml`
- `terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml`
- `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`
- `terraform/lxc/ansible/playbooks/deploy-coredns.yml`
- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`
- `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`
- `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`
- `terraform/lxc/ansible/playbooks/deploy-step-ca.yml`
- `terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml`
- `terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml`

### Stack Metadata Files

- `terraform/lxc/stacks/apt-cacher-stack/stack.yaml`
- `terraform/lxc/stacks/apt-cacher-stack/terragrunt.hcl`
- `terraform/lxc/stacks/authentik-stack/stack.yaml`
- `terraform/lxc/stacks/authentik-stack/terragrunt.hcl`
- `terraform/lxc/stacks/ci-runner-01/stack.yaml`
- `terraform/lxc/stacks/ci-runner-01/terragrunt.hcl`
- `terraform/lxc/stacks/dns-stack/stack.yaml`
- `terraform/lxc/stacks/dns-stack/terragrunt.hcl`
- `terraform/lxc/stacks/harbor-stack/stack.yaml`
- `terraform/lxc/stacks/harbor-stack/terragrunt.hcl`
- `terraform/lxc/stacks/monitoring-stack/stack.yaml`
- `terraform/lxc/stacks/monitoring-stack/terragrunt.hcl`
- `terraform/lxc/stacks/portainer-stack/stack.yaml`
- `terraform/lxc/stacks/portainer-stack/terragrunt.hcl`
- `terraform/lxc/stacks/proxy-stack/stack.yaml`
- `terraform/lxc/stacks/proxy-stack/terragrunt.hcl`
- `terraform/lxc/stacks/step-ca-stack/stack.yaml`
- `terraform/lxc/stacks/step-ca-stack/terragrunt.hcl`

### Checkpoint-portability Docs

- `docs/baseline-merge/validation-prep.md`
- `docs/baseline-merge/checkpoint-readiness.md`

## Explicit Decisions On Key Files

### `.env.pve-test.template`

Include it in the checkpoint.

Reason:

- the validation runbook now depends on it being present in the checkpointed
  worktree so operators can materialize `.env.pve-test` locally
- omitting it recreates the portability failure already documented in the
  validation-portability review

### `docs/baseline-merge/validation-prep.md`

Include it in the checkpoint.

Reason:

- it is the executable runbook for the first clean gate worktree created from
  the checkpoint
- it is not ignored by `.gitignore`
- keeping it out would force operators to rely on ignored handoffs or local
  workspace context, which defeats reproducibility

## Files That Must Stay Out Of The Checkpoint

The checkpoint should explicitly exclude these classes of content.

### Ignored Handoffs And Prompts

- `docs/**/handoffs/**`

Reason:

- `.gitignore` ignores this tree
- these files do not travel with the checkpoint commit
- the checkpoint must remain understandable without any handoff or prompt file

### Local Overlay Files

- `.env`
- `.env.pve-test`
- `.env.local`
- any other `.env.*` file except `.env.template` and `.env.pve-test.template`

Reason:

- these are operator-local non-secret overlays, not repository state

### Generated And Runtime Artifact Files

- `terraform/lxc/.generated/**`
- stack inventory render outputs
- evidence snapshots and log files

Reason:

- these are regenerated or local runtime outputs, not source of truth

### Planning-only Baseline Merge Material

- `docs/baseline-merge/backport-checklist.md`

Reason:

- it is a planning inventory with pending bucket annotations, not a checkpoint
  portability requirement
- the real gate runbook does not depend on it

## Exact Pre-commit Verification Steps

Use these steps immediately before creating the checkpoint commit.

### 1. Confirm Branch And Dirty State

```bash
cd /home/steve/git/proxmox-homelab
git status --short --branch
```

Expected result:

- branch is `work/baseline-convergence-01`
- tracked dirty files match the manifest below
- untracked non-ignored files are limited to `.env.pve-test.template`,
  `docs/baseline-merge/validation-prep.md`,
  `docs/baseline-merge/checkpoint-readiness.md`, and any intentionally excluded
  local planning file such as `docs/baseline-merge/backport-checklist.md`

### 2. Confirm The Tracked Candidate Set Is Exact

```bash
git diff --name-only
```

Expected result:

- output matches the tracked file list in `Files That Belong In The Checkpoint`
- if any additional tracked file appears, stop and review that drift before
  creating the checkpoint

### 3. Confirm Which Untracked Files Need To Be Added

```bash
git ls-files --others --exclude-standard -- docs/baseline-merge .env.pve-test.template
git check-ignore -v docs/baseline-merge/handoffs/12-empty-pve-test-validation-prep-handback.md
```

Expected result:

- `.env.pve-test.template`
- `docs/baseline-merge/validation-prep.md`
- `docs/baseline-merge/checkpoint-readiness.md`
- optional local planning material that is intentionally excluded, such as
  `docs/baseline-merge/backport-checklist.md`
- the handoff path reports `.gitignore` coverage from `docs/**/handoffs/`

### 4. Stage Only The Checkpoint Manifest Set

When the operator is ready to create the checkpoint commit, add only the files
listed in `Files That Belong In The Checkpoint`.

Do not add:

- `docs/**/handoffs/**`
- `docs/baseline-merge/backport-checklist.md`
- local `.env` overlays
- generated artifacts

### 5. Verify The Staged Set Before Commit

```bash
git diff --cached --name-only
git diff --cached --check
```

Expected result:

- staged file list matches the manifest exactly
- no whitespace or patch-format errors are reported

### 6. Confirm The Checkpoint Commit Is Sufficient For A Clean Gate Worktree

After the commit exists, verify:

```bash
CHECKPOINT_COMMIT="<new-checkpoint-commit>"
git worktree add ../proxmox-homelab-empty-gate "$CHECKPOINT_COMMIT"
cd ../proxmox-homelab-empty-gate
test -f .env.pve-test.template
test -f docs/baseline-merge/validation-prep.md
git status --short
```

Expected result:

- `.env.pve-test.template` exists in the clean worktree
- `docs/baseline-merge/validation-prep.md` exists in the clean worktree
- `git status --short` returns no output

## Ambiguities That Make The Checkpoint Unsafe

Stop and do not create the checkpoint if any of these are true.

1. `git diff --name-only` includes tracked files outside the manifest in this
   document.
2. `.env.pve-test.template` is omitted or still absent from the checkpointed
   worktree.
3. `docs/baseline-merge/validation-prep.md` is omitted, forcing the clean
   worktree to depend on ignored handoffs for validation instructions.
4. Any listed tracked file contains unreviewed drift beyond the convergence
   slices summarized in `docs/baseline-merge/validation-prep.md`.
5. The operator expects a clean current worktree after commit while leaving
   `docs/baseline-merge/backport-checklist.md` as a non-ignored untracked file.
   That file is intentionally outside the checkpoint and must be treated as
   local planning material.

## Checkpoint-ready Conclusion

The branch is checkpoint-ready at the file-set level, with one condition:

- the checkpoint commit must include exactly the tracked source files above,
  plus `.env.pve-test.template`, `docs/baseline-merge/validation-prep.md`, and
  `docs/baseline-merge/checkpoint-readiness.md`

If that exact set is used, the resulting commit is a trustworthy prerequisite
checkpoint for the real empty-`pve-test` rebuild gate.
