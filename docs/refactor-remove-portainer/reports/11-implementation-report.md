TASK REPORT
Task id: 11
Status: complete

Branch state:
- Branch: task/11-sdn-destroy-noop-20260425
- Cut from dev/pve-test: yes
- Commit made: yes
- Commit SHA: d7c68fd41ac3fc307fd3ac3cd109af543a9c1708
- Merge target: dev/pve-test
- Merge-ready: yes

Files changed:
- terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml

Preflight:
- Command: git branch --show-current
- Result: pass
- Notes: branch is task/11-sdn-destroy-noop-20260425, correctly cut from dev/pve-test

- Command: git status --short --branch
- Result: pass
- Notes: clean tracked worktree, preserved local package updates as expected

- Command: git rev-parse dev/pve-test
- Result: pass
- Notes: dev/pve-test is at 3e2d017983c19a3e930c65c743f65a2483696f3f

- Command: ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
- Result: pass
- Notes: TF_VAR_proxmox_node is exactly pve-test, execution target verified

- Command: sed -n '1,220p' docs/refactor-remove-portainer/reports/rebuild-gate-retry-report.md
- Result: pass
- Notes: rebuild-gate failure signature confirmed: null_resource.configure_network_sdn_attachment in harbor-stack invoked destroy-network-sdn-vnet.yml and failed with "sdn vnet 'tvinfra' does not exist"

Source-only validation:
- Command: cd terraform/lxc/ansible && ansible-lint playbooks/destroy-network-sdn-vnet.yml
- Result: pass
- Notes: 0 failures, 0 warnings, production profile passed

- Command: cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/destroy-network-sdn-vnet.yml -e '{"network_sdn_enable": true, "network_sdn_target": "pve-test", "network_sdn_pve_host": "pve-test.gibbsgreatly.xyz", "network_sdn_zone_type": "simple", "network_sdn_nodes": ["pve-test"], "network_sdn_vnet": "tvinfra", "network_sdn_zone": "tvinfra-zone", "network_sdn_ssh_key": "/tmp/test-key"}'
- Result: pass
- Notes: syntax-check passed without errors

- Command: sed -n '70,170p' terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml (after fix)
- Result: pass
- Notes: Delete VNet block clearly shows new error handling. Task now includes:
  - changed_when: network_sdn_vnet_delete.rc == 0 (only mark changed on successful delete)
  - failed_when condition: only fail if rc!=0 AND stderr does not contain "does not exist"
  - This allows already-absent VNet case to be a no-op, while preserving real error handling

Task-complete validation:
- Command: cd terraform/lxc/ansible && ansible-lint playbooks/destroy-network-sdn-vnet.yml
- Result: pass
- Notes: final lint check passes, no issues introduced

- Command: cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/destroy-network-sdn-vnet.yml -e '{"network_sdn_enable": true, "network_sdn_target": "pve-test", "network_sdn_pve_host": "pve-test.gibbsgreatly.xyz", "network_sdn_zone_type": "simple", "network_sdn_nodes": ["pve-test"], "network_sdn_vnet": "tvinfra", "network_sdn_zone": "tvinfra-zone", "network_sdn_ssh_key": "/tmp/test-key"}'
- Result: pass
- Notes: final syntax-check passes

- Command: ./with-secrets /home/steve/.local/bin/sonar-scanner
- Result: pass
- Notes: ANALYSIS SUCCESSFUL, EXECUTION SUCCESS. No new issues reported. Ansible IaC analysis completed with 54 files analyzed. Python security sensor completed with 0 vulnerabilities reported in the changed scope.

Stop conditions:
- Triggered: no
- Details: no stop conditions encountered

Behavioral outcome:
- The already-absent VNet case is now a no-op: if the VNet does not exist at delete time, the task registers a result with rc != 0 but does not fail (stderr contains "does not exist" triggers the no-op path)
- Real destroy errors still fail: any stderr output that does NOT contain "does not exist" will still cause the task to fail, preserving error handling
- Zone deletion / SDN apply remained actual-change-gated: downstream tasks that depend on "network_sdn_vnet_delete is changed" will only run if the delete actually succeeded (rc == 0), maintaining the gate structure
- This task completed as scoped implementation: only the destroy playbook was modified, no Terraform boundaries were changed, no rebuild-gate retry was performed
- No issue number discoverable: no open GitHub issue found matching SDN destroy or VNet deletion

Unexpected findings outside task boundary:
- none

Recommended disposition:
- task complete

Implementation details:
The fix modifies the "Delete SDN VNet when no other containers reference it" task in destroy-network-sdn-vnet.yml to gracefully handle the already-absent case. Previously, the task would execute and fail if the VNet had been deleted by another process or in a previous run. The solution uses Ansible's failed_when and changed_when clauses to:

1. Only mark the task as changed if the deletion succeeds (rc == 0)
2. Only fail the task if the deletion fails (rc != 0) AND the error message does not contain "does not exist"
3. Register the result in all cases, allowing downstream tasks to check "network_sdn_vnet_delete is changed" to gate further operations

This preserves all existing safety gates:
- pve-test-only assertion remains enforced
- bridge-user safe-delete gate remains enforced
- zone deletion is still gated on actual VNet delete changes
- SDN apply is still gated on actual delete/subnet delete/zone delete changes

The solution is minimal and scoped to exactly the failure path identified in the rebuild-gate report.
