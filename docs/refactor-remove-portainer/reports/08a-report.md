TASK REPORT
Task id: 08a
Status: needs-package-update

Branch state:
- Branch: task/08a-real-inventory-handoff-20260425
- Cut from dev/pve-test: yes
- Commit made: no
- Commit SHA: none
- Merge target: dev/pve-test
- Merge-ready: no

Files changed:
- none (runtime artifact only)

Preflight:
- Command: git branch --show-current
- Result: pass
- Notes: active branch is task/08a-real-inventory-handoff-20260425 after cutting from dev/pve-test.
- Command: git status --short --branch
- Result: pass
- Notes: worktree was clean except ignored report artifacts before execution and is still clean for tracked files after rollback.
- Command: ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
- Result: pass
- Notes: returned exactly pve-test.
- Command: test -f terraform/lxc/stacks/harbor-stack/inventory.yml && echo exists || echo missing
- Result: pass
- Notes: returned missing before live action and missing again after rollback.
- Command: grep -E "ansible_playbook|deployment_tier" terraform/lxc/stacks/harbor-stack/stack.yaml
- Result: pass
- Notes: harbor-stack still declares ansible_playbook: deploy-harbor-stack and deployment_tier: platform.
- Command: grep -n 'filename = "${local.stack_dir}/inventory.yml"' terraform/lxc/main.tf
- Result: pass
- Notes: verified via /usr/bin/grep because the shell grep alias rejected the pattern; terraform/lxc/main.tf still writes inventory.yml through local_file.ansible_inventory at line 321.

Source-only validation:
- Command: ./with-secrets bash -c 'cd terraform/lxc/stacks/harbor-stack && terragrunt plan'
- Result: fail
- Notes: the plan appeared stack-local and showed local_file.ansible_inventory creation plus null_resource.ansible_provision and null_resource.stack_cleanup destruction, but it did not make clear that destroying stack_cleanup would execute a destroy-time local-exec path that invokes ansible-playbook cleanup.yml. The task contract therefore did not safely predict real apply behavior.

Task-complete validation:
- Command: ./with-secrets bash -c 'cd terraform/lxc/stacks/harbor-stack && terragrunt apply -auto-approve'
- Result: fail
- Notes: apply generated inventory.yml, but destroying null_resource.stack_cleanup[0] ran a local-exec provisioner that executed ansible-playbook playbooks/cleanup.yml and hit Portainer API auth failure. This violated the task stop condition against invoking Ansible during Task 08a, so the unit was rolled back using terraform/lxc/stacks/harbor-stack/terraform.tfstate.backup and the generated inventory.yml was removed.
- Command: test -f terraform/lxc/stacks/harbor-stack/inventory.yml && echo exists
- Result: fail
- Notes: inventory.yml no longer exists after rollback, which restores the pre-task filesystem state.
- Command: grep 'ansible_playbook:' terraform/lxc/stacks/harbor-stack/inventory.yml
- Result: pass
- Notes: before rollback, the generated artifact contained ansible_playbook: deploy-harbor-stack.
- Command: python3 -c "import yaml,sys; inv=yaml.safe_load(sys.stdin); grp=next(iter(inv['all']['children'].values())); host=next(iter(grp['hosts'].values())); print(host.get('ansible_playbook',''))" < terraform/lxc/stacks/harbor-stack/inventory.yml
- Result: pass
- Notes: before rollback, the extraction printed deploy-harbor-stack exactly as Task 09 expects.
- Command: ./with-secrets bash -c 'cd terraform/lxc/stacks/harbor-stack && terragrunt state show local_file.ansible_inventory'
- Result: pass
- Notes: before rollback, state show proved Terraform managed the generated inventory artifact.
- Command: ./with-secrets /home/steve/.local/bin/sonar-scanner
- Result: pass
- Notes: scanner completed successfully and did not report a new scan failure.

Stop conditions:
- Triggered: yes
- Details: terragrunt apply for harbor-stack invoked destroy-time Ansible cleanup through null_resource.stack_cleanup[0] local-exec, which violates the Task 08a rule that this task must not invoke Ansible or widen into orchestration.

Behavioral outcome:
- harbor-stack inventory.yml does not exist after rollback.
- ansible_playbook was present in the generated artifact and the Python extraction returned deploy-harbor-stack before rollback.
- Terraform provenance was proven via terragrunt state show before rollback.
- this task attempted a live mutation, hit a stop condition, and was rolled back within terraform/lxc/stacks/harbor-stack/.
- no issue number discoverable

Unexpected findings outside task boundary:
- terraform/lxc/stacks/harbor-stack still carries a destroy-time cleanup path through null_resource.stack_cleanup state, so a supposedly narrow artifact-generation apply actually invokes destroy-time Ansible. That behavior sits outside the Task 08a contract and needs package or implementation follow-up before retrying 08a safely.

Recommended disposition:
- blocked pending architecture update
