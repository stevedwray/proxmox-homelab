TASK REPORT
Task id: 25 (rebuild gate attempt — post tasks 23/24)
Status: blocked

Branch state:
- Branch: task/24-pve-test-reboot (carry-forward from tasks 23/24 package reconciliation)
- Cut from dev/pve-test: yes
- Commit made: no
- Commit SHA: none
- Merge target: dev/pve-test
- Merge-ready: no

Files changed:
- docs/refactor-remove-portainer/reports/25-rebuild-gate-sdn-idempotency-failure-report.md

Preflight:
- Command: ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
- Result: pass
- Notes: Output was exactly pve-test.

Rebuild gate step 1 — destroy:
- Command: ./with-secrets terragrunt --working-dir terraform/lxc/stacks --non-interactive run --all -- destroy -auto-approve
- Exit code: 0
- Result: pass
- Notes: Run Summary: 21 units, Succeeded: 21, Failed: 0. All LXC stacks destroyed cleanly.

Rebuild gate step 2 — apply:
- Command: ./with-secrets terragrunt --working-dir terraform/lxc/stacks --non-interactive run --all -- apply -auto-approve
- Exit code: 1
- Result: FAIL
- Notes: Run Summary: 21 units, Succeeded: 6, Failed: 15.

Rebuild gate steps 3-6:
- Not run. Blocked by step 2 failure.

Stop conditions:
- Triggered: yes
- Details: Apply produced 15 failures across two distinct root causes (see below). Per runbook section 5, executor stops and returns findings to architecture session.

Failure analysis — Root cause 1: SDN idempotency (affects 13 stacks)

  The Ansible playbook `configure-network-sdn-vnet.yml` calls `pvesh create` unconditionally to
  create SDN zone, vnet, and subnet objects. Destroy does tear down the LXC containers themselves,
  but does not guarantee SDN objects are removed before the parallel apply begins. When `pvesh
  create` is called for an object that already exists, the Proxmox API returns a non-zero exit code
  and the playbook fails.

  Observed error messages:
  - step-ca-stack:      create sdn zone object failed: sdn zone object ID 'tvmgmt' already defined (rc=2)
  - portainer-stack:    create sdn subnet object failed: sdn subnet object ID 'tvmgmt-10.57.1.0-24' already defined (rc=255)
  - netbox-stack:       create sdn vnet object failed: sdn vnet object ID 'tvinfra' already defined (rc=255)
  - apt-cacher-stack:   create sdn vnet object failed: sdn vnet object ID 'tvinfra' already defined (rc=255)

  Pattern: `pvesh create /cluster/sdn/zones/<id>`, `/cluster/sdn/vnets/<id>`, and
  `/cluster/sdn/subnets/<id>` all fail with "already defined" when the object exists.
  The playbook does not check existence before attempting creation.

  Fix required: Replace unconditional `pvesh create` calls with idempotent logic — either
  `pvesh get ... || pvesh create ...` guards, or migrate to Ansible `community.general.proxmox_sdn_*`
  modules which handle create-or-update semantics. Scope: `configure-network-sdn-vnet.yml`.

Failure analysis — Root cause 2: Invalid zone key references in Terraform locals (affects 2 stacks)

  Two stacks reference zone keys that do not exist in `local.network_intent.zones`:

  - net-service-02: `local.stack_network_zone is "observe_seg"` — key not present
  - net-svc-01:     `local.stack_network_zone is "infra"` — key not present

  Error: `Invalid index — The given key does not identify an element in this collection value.`

  This is a Terraform locals bug independent of the SDN race condition. Even after fixing the
  playbook idempotency issue, these two stacks will fail unless the zone key references are
  corrected or the corresponding zones are added to `local.network_intent.zones`.

  Fix required: Either (a) correct the zone key names in the stack locals to match defined keys in
  `network_intent.zones`, or (b) add `observe_seg` and `infra` zone definitions to the shared
  network intent. Scope: stack configs for net-service-02 and net-svc-01, and/or the shared
  network intent definition.

Behavioral outcome:
- Destroy phase was clean. No partial-destroy or stuck-resource issues.
- Apply phase hit two independent failure modes before any platform-tier provisioning could run.
- The refactor does not pass the rebuild gate in its current state.
- The two failure modes are separable: fix the Terraform zone keys first (pure config bug), then
  fix SDN playbook idempotency (behavioral fix).

Unexpected findings outside task boundary:
- none beyond the two root causes above

Recommended disposition:
- Return to architecture session.
- Task 26: fix `net-service-02` and `net-svc-01` invalid zone key references.
- Task 27 (or combined): make `configure-network-sdn-vnet.yml` idempotent.
- Re-run full rebuild gate after both fixes are merged to dev/pve-test.
