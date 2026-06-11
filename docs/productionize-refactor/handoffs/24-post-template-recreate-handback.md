# Post-Template Recreate Handback

Date: 2026-05-24
Branch: work/productionize-06-canary-validation
Scope: Recreate only the previously failed pve infra stacks after correcting the shared LXC template artifact on pve.

## Inputs Reviewed

- Prior template parity confirmation: `docs/productionize-refactor/handoffs/23-pve-template-parity-handback.md`
- Execution packet: `docs/productionize-refactor/18-pve-infra-teardown-execution-packet.md`
- Prior failure evidence:
  - `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-204056/logs/apply-netbox-stack.log`
  - `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-204056/logs/provision-netbox-stack.log`
  - `docs/productionize-refactor/evidence/pve-infra-teardown-exec-20260523-204056/logs/provision-portainer-stack.log`

## Template Baseline Used

- pve template checksum at retest time: `39a697a4e7c121b18d8dfd8d70a3845d10f0df04ba0f50a8d3abab3c10bf2250`
- pve-test template checksum: `39a697a4e7c121b18d8dfd8d70a3845d10f0df04ba0f50a8d3abab3c10bf2250`
- Parity before recreate: exact

## Evidence

- New recreate evidence directory: `docs/productionize-refactor/evidence/pve-post-template-recreate-20260523-215902`

## Commands / Phases Run

The rerun stayed scoped to `netbox-stack` and `portainer-stack` only.

Commands executed under `./with-secrets-prod` with `TASK_APPROVAL="pve-post-template-recreate-validation"`:

1. `terragrunt destroy --working-dir terraform/lxc/stacks/netbox-stack -auto-approve -no-color`
2. `terragrunt apply --working-dir terraform/lxc/stacks/netbox-stack -auto-approve -no-color`
3. `./scripts/provision.sh --stack netbox-stack`
4. `terragrunt destroy --working-dir terraform/lxc/stacks/portainer-stack -auto-approve -no-color`
5. `terragrunt apply --working-dir terraform/lxc/stacks/portainer-stack -auto-approve -no-color`
6. `./scripts/provision.sh --stack portainer-stack`
7. Post-recreate host check: `ssh root@pve 'pct list'`
8. Narrow follow-up validation for netbox DNS: `ssh root@pve 'pct exec 40012 -- getent hosts harbor.lab.gibbsgreatly.xyz || true; pct exec 40012 -- cat /etc/resolv.conf'`
9. Narrow follow-up validation for container state: `ssh root@pve 'pct status 40012; pct status 20020'`

## Results By Stack

### netbox-stack

- Recreated: yes
- VMID after recreate: `40012`
- Final container state: running

Phase results:

- Destroy: partial success
  - Container destruction succeeded.
  - Terraform destroy then failed during the SDN destroy local-exec guard.
  - Exact blocker: `network_sdn_allow_destroy | default(false) | bool` evaluated false in `destroy-network-sdn-vnet.yml`.
- Apply: failed again
  - Container was created from the corrected template.
  - Apply then failed at `playbooks/configure-keyctl.yml` because the playbook still delegates to `pve-test.gibbsgreatly.xyz` and ran `pct set 40012 -features nesting=1,keyctl=1` against the wrong host.
  - Exact error: `Configuration file 'nodes/pve-test/lxc/40012.conf' does not exist`.
- Provision: failed again
  - Docker compose pull still failed because `harbor.lab.gibbsgreatly.xyz` was not resolvable from inside the recreated container.
  - Exact error remained: `lookup harbor.lab.gibbsgreatly.xyz on 192.168.40.1:53: no such host`.

Post-recreate validation:

- `pct status 40012` returned `status: running`.
- `pct exec 40012 -- getent hosts harbor.lab.gibbsgreatly.xyz` returned no result.
- `pct exec 40012 -- cat /etc/resolv.conf` showed `nameserver 192.168.40.1`.

Assessment:

- Template parity changed the template baseline used for the recreated container, but it did not change the failure outcome.
- Remaining failures are clearly not template-related.
- Current blockers are:
  - wrong environment target in `configure-keyctl.yml`
  - Harbor DNS/registry reachability from the infra segment

Classification: clearly not template-related.

### portainer-stack

- Recreated: yes
- VMID after recreate: `20020`
- Final container state: running

Phase results:

- Destroy: partial success
  - Container destruction succeeded.
  - Terraform destroy then failed during the same SDN destroy guard as above.
  - Exact blocker: `network_sdn_allow_destroy | default(false) | bool` evaluated false in `destroy-network-sdn-vnet.yml`.
- Apply: succeeded
  - Container recreation completed successfully from the corrected template.
- Provision: failed again
  - Failure remained in the edge publication step, not the base container creation path.
  - Exact issues remained:
    - `EGR200`: target preflight refused `PVE_ENV=pve` because it expected `pve-test`
    - `EGR211`: Authentik discovery reported drift/issues

Post-recreate validation:

- `pct status 20020` returned `status: running`.
- `pct list` showed `20020 portainer-stack` present and running.

Assessment:

- Template parity did not change the outcome.
- Remaining failure is clearly not template-related.
- Current blockers are:
  - production guard requiring an explicit `ALLOW_PVE=true` override for the edge target preflight/apply path if production mutation is intended
  - unresolved Authentik discovery drift/issues for the Portainer edge manifest objects

Classification: clearly not template-related.

## Overrides / Guards Encountered

Observed during the scoped rerun:

- SDN destroy guard blocked both `terragrunt destroy` commands from completing cleanly after container removal.
  - Relevant override path shown by the destroy provisioner: `NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true`
  - This was not applied during the rerun.
- Portainer edge preflight refused production targeting.
  - Relevant override called out by the tool output: `ALLOW_PVE=true`
  - This was not applied during the rerun.

## Out-of-Scope Safety

- Scope stayed limited to `netbox-stack` and `portainer-stack`.
- Post-recreate `pct list` still showed the broader guest set intact, including out-of-scope guests such as `910 debian13-template-builder`.
- No full teardown was rerun.

## Conclusion

Recreating the failed stacks after template parity correction did not fix the previously observed failures.

- `netbox-stack` still fails for the same two reasons:
  - keyctl configuration targets `pve-test` instead of `pve`
  - Harbor DNS lookup fails from inside the recreated container
- `portainer-stack` still fails for the same reason:
  - edge reconciliation is blocked by a production guard and existing Authentik drift/issues

This retest is strong evidence that the earlier failures were not caused by pve vs pve-test template drift.

## Readiness Recommendation

- Ready for narrow post-redeploy infrastructure validation of container presence/state: yes
- Ready for functional testing of `netbox-stack`: no
- Ready for functional testing of `portainer-stack` edge publication: no
- Ready for broader post-redeploy validation sign-off for these two stacks: not yet

Recommended next steps:

1. Fix `configure-keyctl.yml` so production runs delegate to `pve.gibbsgreatly.xyz` rather than hardcoding `pve-test.gibbsgreatly.xyz`.
2. Restore or verify Harbor DNS publication/reachability from the infra segment before retrying `netbox-stack` provision.
3. Decide whether Portainer edge reconciliation is intended to mutate production in this phase; if yes, rerun that path with the explicit `ALLOW_PVE=true` override and then resolve the reported Authentik drift.
