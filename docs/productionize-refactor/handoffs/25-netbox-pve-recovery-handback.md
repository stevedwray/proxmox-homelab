# NetBox pve Recovery Handback

Date: 2026-05-24
Branch: work/productionize-06-canary-validation
Scope: Recover `netbox-stack` on `pve` after the infra-only teardown/redeploy test, without touching `portainer-stack` or running a broad teardown.

## Evidence

- Evidence directory: `docs/productionize-refactor/evidence/netbox-pve-recovery-20260524-101800/logs`
- Prior context reviewed:
  - `docs/productionize-refactor/handoffs/23-pve-template-parity-handback.md`
  - `docs/productionize-refactor/handoffs/24-post-template-recreate-handback.md`
  - `docs/productionize-refactor/evidence/pve-post-template-recreate-20260523-215902/logs/apply-netbox-stack.log`
  - `docs/productionize-refactor/evidence/pve-post-template-recreate-20260523-215902/logs/provision-netbox-stack.log`

## Files Changed

- `terraform/lxc/templates/inventory.tpl`
- `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`
- `terraform/lxc/stacks/netbox-stack/docker-compose.yml`
- `docs/productionize-refactor/handoffs/25-netbox-pve-recovery-handback.md`

## What Was Fixed

### 1. Keyctl delegation bug

Status: fixed

Root cause:
- Terraform already computed `pve_host = pve.gibbsgreatly.xyz` for production stacks.
- The generated inventory only serialized `pve_host` when `use_proxyjump` was enabled.
- `netbox-stack` is a direct-access SDN stack, so `configure-keyctl.yml` never received `pve_host` and fell back to `pve-test.gibbsgreatly.xyz`.

Code change:
- `terraform/lxc/templates/inventory.tpl` now emits `pve_host` whenever it is non-empty, not only for ProxyJump inventories.

Validated by:
- Read-only production plan showed `pve_host: pve.gibbsgreatly.xyz` in the rendered `netbox-stack` inventory.
- Production apply succeeded and `configure-keyctl.yml` delegated to `pve.gibbsgreatly.xyz` successfully.

### 2. Harbor DNS publishing gap

Status: fixed

Root cause:
- `terraform/lxc/.generated/coredns/coredns-lab.zone` can render `harbor.lab.gibbsgreatly.xyz` correctly from checked-in EdgeManifest files.
- Production `dns-stack` was still serving a stale published zone that contained `portainer.lab.gibbsgreatly.xyz` but not `harbor.lab.gibbsgreatly.xyz`.

Validated before fix:
- `dns-stack` live zone contained only `harbor-bg` and no generated `harbor` record.
- VMID `40012` resolved `portainer.lab.gibbsgreatly.xyz` but not `harbor.lab.gibbsgreatly.xyz` via `192.168.40.1`.

Fix applied:
- Re-rendered/published the generated CoreDNS zone by running `./scripts/provision.sh --stack dns-stack` under `./with-secrets-prod`, which passed `coredns_generated_zone_src` to `deploy-coredns.yml`.

Validated after fix:
- `dns-stack` live zone now contains `harbor          5m   IN  A   192.168.30.10`.
- `dig @127.0.0.1 +short harbor.lab.gibbsgreatly.xyz` on `dns-stack` returns `192.168.30.10`.
- `getent hosts harbor.lab.gibbsgreatly.xyz` inside VMID `40012` returns `192.168.30.10`.
- `curl http://harbor.lab.gibbsgreatly.xyz/v2/` inside VMID `40012` now returns `301` instead of DNS failure.

## Minimal Production Retry Results

Commands executed under `TASK_APPROVAL=25-netbox-pve-recovery` and `./with-secrets-prod`:

1. Target preflight: `bash -lc 'echo "$TF_VAR_proxmox_node"'`
2. Live DNS inspection on `dns-stack` and VMID `40012`
3. `terragrunt apply --working-dir terraform/lxc/stacks/netbox-stack -auto-approve -no-color`
4. `./scripts/provision.sh --stack dns-stack`
5. Post-publish DNS and Harbor reachability checks from `dns-stack` and VMID `40012`
6. `./scripts/provision.sh --stack netbox-stack` (multiple focused retries after each local fix)

Results:

- `netbox-stack` apply now succeeds: yes
- `configure-keyctl.yml` production delegation fixed: yes
- `harbor.lab.gibbsgreatly.xyz` resolves from VMID `40012`: yes
- `netbox-stack` provision now succeeds: no

## Current NetBox State

NetBox recovery is partial.

Working now:
- Container creation/apply path succeeds.
- Keyctl configuration succeeds against `pve.gibbsgreatly.xyz`.
- Harbor DNS resolution no longer blocks image pulls.
- NetBox compose deployment now reaches a healthy main container state during the later retries.

Still failing:
- The provision play still fails at `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`, task `Ensure NetBox admin users exist`.
- Exact runtime symptom: the ORM-based admin bootstrap command exits with status `137` on VMID `40012`.
- Supporting evidence:
  - `netbox-admin-sync-manual.log`
  - `provision-netbox-stack-retry-4.log`

Additional observations from the focused retries:
- NetBox main health failures caused by a `3s` healthcheck timeout were mitigated by increasing the timeout to `10s`.
- The main container is serving `GET /login/` with `200` responses.
- The remaining failure is now after container health, inside admin/bootstrap automation, not in DNS, template parity, or keyctl setup.

## Remaining Blockers

1. NetBox admin bootstrap still fails on production VMID `40012` with exit `137` during `Ensure NetBox admin users exist`.
2. Because that admin/bootstrap step fails, `netbox-stack` is not fully provisioned end-to-end and the API token creation step does not complete.

## Validation Run

Focused validations executed:

- Read-only production `terragrunt plan` for `netbox-stack` to confirm rendered `pve_host`
- `ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/configure-keyctl.yml`
- `ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-coredns.yml`
- `ansible-playbook --syntax-check -i terraform/lxc/stacks/netbox-stack/inventory.yml terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`
- Live production DNS checks on `dns-stack` and VMID `40012`
- Production `terragrunt apply` for `netbox-stack`
- Production `./scripts/provision.sh --stack dns-stack`
- Production `./scripts/provision.sh --stack netbox-stack` retries after each focused change

## Out-of-Scope Safety

- `portainer-stack` was not touched.
- No broad teardown was run.
- No unrelated guests were modified.
- One supporting out-of-stack production guest was touched: `dns-stack`, only to publish the generated CoreDNS zone required for `netbox-stack` image pulls.

## Conclusion

The original post-template blockers are resolved:

- keyctl delegation bug: fixed
- Harbor DNS resolution from VMID `40012`: fixed

`netbox-stack` is not fully recovered yet because a new, narrower blocker remains in the NetBox admin bootstrap step (`exit 137` during admin user sync). The pve infra redeploy should not be treated as ready for final validation sign-off until that remaining `netbox-stack` provision failure is resolved or explicitly accepted.

## Review Note

Follow-up review found that the current admin-sync patch has a recursion/indentation
bug: the superuser `ensure_admin_user()` call is nested inside the
`ensure_admin_user()` function body. Treat the `exit 137` resource-pressure
assessment above as unproven until that script-structure bug is fixed and the
NetBox provision retry is repeated.
