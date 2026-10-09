# 11 — gaming-stack-lab Terraform drift

**When:** following weeks · **Effort:** 30 min · **Value:** Low-Med (removes
a "don't ever apply this stack" warning that no longer matches reality)
**Approval name:** `catchup-11-gaming-tags`

## What changed since the warning was written

`docs/gaming-stack-lab/README.md` (gap 1) says the stack's Terraform state
"doesn't resolve from its working directory", with `plan` showing a spurious
"6 to add", and says never to apply it. On **2026-09-28** a read-only
`terragrunt plan` from the per-environment directory resolved the real state
(workspace `pve`, CT 60010):

```
local_file.ansible_inventory will be created
module.lxc.proxmox_virtual_environment_container.docker_host will be updated in-place
  ~ tags: reorder, plus "pterodactyl-wings" (in stack.yaml, not yet on the live CT)
Plan: 1 to add, 1 to change, 0 to destroy.
```

The "6 to add" almost certainly came from running Terragrunt in the legacy
`terraform/lxc/stacks/gaming-stack-lab/` directory. That's the old
stack-level entry point, and its `terraform.tfstate.d/` is empty. The state
lives in `terraform/lxc/environments/pve/gaming-stack-lab/`.

## Operator: re-confirm, then apply the tag change (approval `catchup-11-gaming-tags`)

```bash
cd terraform/lxc/environments/pve/gaming-stack-lab
../../../../../with-secrets-prod terragrunt plan -lock=false -out=catchup-11.tfplan
../../../../../with-secrets-prod terragrunt show -json catchup-11.tfplan > ../../../../../docs/catch-up/artifacts/11-plan.json
python3 - <<'PY'
import json
p = json.load(open('../../../../../docs/catch-up/artifacts/11-plan.json'))
changes = [(r['address'], r['change']['actions']) for r in p['resource_changes'] if r['change']['actions'] != ['no-op']]
print(changes)
assert changes == [('local_file.ansible_inventory', ['create']), ('module.lxc.proxmox_virtual_environment_container.docker_host', ['update'])], 'unexpected plan -- stop'
PY
python3 ../../../check-plan-safety.py --plan-json ../../../../../docs/catch-up/artifacts/11-plan.json
```

Both checks must pass. Then:

```bash
TASK_APPROVAL=catchup-11-gaming-tags ../../../../../with-secrets-prod terragrunt apply catchup-11.tfplan
../../../../../with-secrets-prod terragrunt plan -lock=false -detailed-exitcode; echo "exit=$?"   # expect exit=0 (no changes)
rm -f catchup-11.tfplan
cd -
```

The container isn't restarted by a tag change. Verify ARK/Minecraft/AzerothCore
are untouched: Pterodactyl Panel still shows the servers' states as before.

**Note on `local_file.ansible_inventory`:** the apply regenerates
`environments/pve/gaming-stack-lab/inventory.yml` from `stack.yaml`. The old
workaround hand-patched `ansible_playbook` in that file. `stack.yaml` now
carries `ansible_playbook: deploy-gaming-stack-lab`, so the regenerated file
matches. Compare `git diff --no-index` of a pre-apply copy if in doubt.

## Step (repo, after the apply)

### catchup-11-close-gap

```yaml
id: catchup-11-close-gap
title: Close gap (1) in the gaming-stack-lab README
depends_on: []

change: |
  In docs/gaming-stack-lab/README.md, in the "Known, flagged-not-fixed gaps"
  table row, replace the text that starts "(1) `gaming-stack-lab`'s own
  Terraform state doesn't resolve from its working directory" and ends
  "as a workaround." with this LITERAL text:

  (1) ~~Terraform state doesn't resolve~~ — **resolved 2026-09-28**: state lives in `terraform/lxc/environments/pve/gaming-stack-lab/` (workspace `pve`); the "6 to add" came from running Terragrunt in the legacy `stacks/gaming-stack-lab/` directory. A clean plan/apply from the environment directory is verified (docs/catch-up/11).

  Change nothing else.

scope:
  allowed_paths:
    - docs/gaming-stack-lab/README.md
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: gap-closed
    cmd: "grep -c 'Terraform state doesn.t resolve~~ — \\*\\*resolved 2026-09-28' docs/gaming-stack-lab/README.md"
    expect: "prints 1"
    critical: true
```

Also update the memory note `project_gaming_stack_lab_pterodactyl_status`
(remove the "do not apply" warning).
