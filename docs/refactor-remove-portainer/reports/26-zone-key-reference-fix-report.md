TASK REPORT
Task id: 26
Status: complete

Branch state:
- Branch: task/26-fix-zone-key-references
- Cut from dev/pve-test: yes
- Commit made: yes
- Commit SHA: ba8da20
- Merge target: dev/pve-test
- Merge-ready: yes

Files changed:
- terraform/lxc/stacks/net-service-02/stack.yaml
- terraform/lxc/stacks/net-svc-01/stack.yaml

Preflight:
- Command: ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
- Result: pass
- Notes: Output was exactly pve-test.

Source-only validation:
- Command: rg -n "zone:" terraform/lxc/stacks/net-service-02/stack.yaml terraform/lxc/stacks/net-svc-01/stack.yaml
- Result: pass (confirmed mismatch)
- Notes: net-service-02 had zone: observe_seg; net-svc-01 had zone: infra. Both absent from pve-test.yaml zones section.

- Command: rg -n "^zones:|infra_seg|mgmt_seg|edge_seg|build_seg|observe_seg|infra:" terraform/lxc/network/pve-test.yaml
- Result: pass (confirmed valid keys)
- Notes: Valid zone keys in pve-test.yaml zones section are: infra_seg, mgmt_seg, edge_seg, build_seg. observe_seg has zero presence in the file. infra is not a zone key (infra_seg is). Adding observe_seg would require a new VLAN definition, subnet, and MikroTik routing — broader network-model redesign, not a narrow fix.

- Command: ./with-secrets /home/steve/.local/bin/sonar-scanner
- Result: pass
- Notes: EXECUTION SUCCESS. No new issues introduced.

Task-complete validation:
- Command: ./with-secrets terragrunt --working-dir terraform/lxc/stacks/net-svc-01 plan
- Result: pass
- Notes: Exit code 0. Plan: 3 to add, 0 to change, 0 to destroy. No invalid-index error. network.attachment_type resolved to "bridge" (vmbr0 default).

- Command: ./with-secrets terragrunt --working-dir terraform/lxc/stacks/net-service-02 plan
- Result: pass
- Notes: Exit code 0. Plan: 3 to add, 0 to change, 0 to destroy. No invalid-index error. network.attachment_type resolved to "bridge" (vmbr0 default).

- Command: git diff --name-only
- Result: pass
- Notes: Diff limited to terraform/lxc/stacks/net-service-02/stack.yaml and terraform/lxc/stacks/net-svc-01/stack.yaml only.

- Command: git status --short --branch
- Result: pass
- Notes: Branch task/26-fix-zone-key-references. Only the two stack files modified. All local hazards preserved as untracked files.

Stop conditions:
- Triggered: no
- Details: none

Behavioral outcome:
- Both net-service-02 and net-svc-01 now plan without the Terraform "Invalid index — The given key does not identify an element in this collection value." error that caused 2 of the 15 apply failures in the Task 25 rebuild gate attempt.
- The fix removed the network.zone stanza from both stacks, causing Terraform to resolve them to the vmbr0 bridge default (attachment_type: bridge, zone: null).
- net-svc-01 is explicitly described as a "bridge-path network layer test" with a LAN IP (192.168.1.72); removing the zone reference matches the stated test purpose.
- net-service-02 references zone observe_seg which has no VLAN, subnet, or attachment defined anywhere in pve-test.yaml; adding it would require a network-model addition not in scope. Removing the zone reference and falling back to bridge defaults is the smallest valid fix.
- No SDN playbook changes were made. No rebuild gate was run.
- Issue search returned no matching open issue; no Closes #N in commit.

Unexpected findings outside task boundary:
- net-isolated-01 also references zone: isolated, which is also not defined in pve-test.yaml zones section. This was NOT in the Task 25 failure report and is outside this task's scope. Architecture session should evaluate whether net-isolated-01 needs the same treatment in a follow-up task.

Recommended disposition:
- task complete — merge task/26-fix-zone-key-references to dev/pve-test
- follow-up: check net-isolated-01 zone: isolated reference (outside scope here)
- SDN playbook idempotency (the other 13 apply failures from Task 25) remains unresolved — architecture session should scope Task 27 accordingly
