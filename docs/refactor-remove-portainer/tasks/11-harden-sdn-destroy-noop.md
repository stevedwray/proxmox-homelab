# Task 11: Harden SDN VNet destroy path for rebuild-gate no-op handling

## Type

Development

## Objective

Fix the retained Terraform host-automation destroy path so the final rebuild
gate can destroy `pve-test` cleanly when an SDN VNet is already absent by the
time the destroy-time playbook reaches the delete step.

This task exists because the rebuild gate stopped at Step 1 on:

- `./with-secrets terragrunt run --all destroy`
- stack: `terraform/lxc/stacks/harbor-stack`
- retained resource: `null_resource.configure_network_sdn_attachment`
- playbook: `terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml`
- observed error: `sdn vnet 'tvinfra' does not exist`

The scope is intentionally narrow: make the destroy path idempotent for the
already-absent VNet case without widening into unrelated SDN create-path or
Portainer-removal behavior.

## Files

- `terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml`

## Preconditions

- Task 10 complete.
- The rebuild gate stopped at destroy because `destroy-network-sdn-vnet.yml`
  treated an already-absent VNet as a hard failure.

## Background

Decision 3 explicitly retains `configure_network_sdn_attachment` as Terraform
infrastructure automation. This task must not remove that retained host-level
automation.

The current playbook already computes `network_sdn_vnet_exists` and
`network_sdn_safe_to_delete_vnet`, but the live rebuild gate showed a destroy
race or stale-read path still reaches `pvesh delete /cluster/sdn/vnets/...`
and fails when the VNet is already gone.

The fix must preserve these boundaries:

- `pve-test`-only guardrails remain intact
- active bridge-user detection remains intact
- zone deletion still depends on an actual VNet delete, not a no-op
- this task does not widen into the full rebuild gate retry

## Operations

1. Read `terraform/lxc/ansible/playbooks/destroy-network-sdn-vnet.yml` in full
   before editing.
2. Update the VNet destroy flow so an already-absent VNet is treated as a
   no-op rather than a hard failure.
3. Keep the existing safe-delete gate for active bridge users.
4. Ensure downstream tasks that depend on a real VNet delete still key off an
   actual change, not the no-op path.
5. Do not widen into `configure-network-sdn-vnet.yml`, `main.tf`, or the full
   rebuild gate unless validation proves this task doc is incomplete.
6. Run the required lint, syntax, and scan validation.

## Postconditions

- `destroy-network-sdn-vnet.yml` handles the already-absent VNet case as a
  no-op.
- The playbook still fails on real destroy errors other than the specific
  already-absent case.
- Zone deletion and `pvesh set /cluster/sdn` remain gated on actual delete
  changes.

## Validation

```bash
cd terraform/lxc/ansible

ansible-lint playbooks/destroy-network-sdn-vnet.yml

ansible-playbook --syntax-check \
  -i localhost, \
  playbooks/destroy-network-sdn-vnet.yml \
  -e '{
    "network_sdn_enable": true,
    "network_sdn_target": "pve-test",
    "network_sdn_pve_host": "pve-test.gibbsgreatly.xyz",
    "network_sdn_zone_type": "simple",
    "network_sdn_nodes": ["pve-test"],
    "network_sdn_vnet": "tvinfra",
    "network_sdn_zone": "tvinfra-zone",
    "network_sdn_ssh_key": "/tmp/test-key"
  }'

sed -n '70,170p' playbooks/destroy-network-sdn-vnet.yml

cd /home/steve/git/proxmox-homelab
./with-secrets /home/steve/.local/bin/sonar-scanner
```

Expected outcome:

- `ansible-lint` passes
- syntax-check passes
- the delete block clearly treats the already-absent VNet case as a no-op while
  preserving real error handling
- Sonar reports no new issues

## Stop Conditions

- Stop if fixing the absent-VNet case requires changing retained Terraform
  resource boundaries (`configure_network_sdn_attachment`) rather than just the
  destroy playbook behavior.
- Stop if validation shows the failure is actually in zone deletion or another
  retained resource, not the VNet delete path.
- Stop if Sonar reports new issues.
- Stop if task-complete validation would require widening into the full rebuild
  gate.
