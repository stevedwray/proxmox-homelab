# Session 8 Summary — Teardown And Redeploy Validation Gate (pve-test)

Date: 2026-05-22

## Scope

Completed Session 8 from `docs/network-refactor/plan.md`:

1. Captured fresh preflight evidence before teardown.
2. Executed the `pve-test` teardown/redeploy workflow using the documented harness.
3. Confirmed SDN zone/VNet attachment reconciliation during redeploy.
4. Revalidated representative stacks (`apt-cacher-stack`, `dns-stack`, `proxy-stack`) through redeploy/final checks.
5. Captured post-rebuild evidence for direct access, no default ProxyJump, no host-route priming dependency, MikroTik DNS path, and representative stack health.

## Preconditions And Preflight

Mandatory preflight command (before teardown):

```bash
./with-secrets scripts/preflight-network-refactor.sh --save-evidence docs/teardown-test/evidence 192.168.40.11
```

Result: PASS

Evidence:

- `docs/teardown-test/evidence/preflight-evidence-20260522-131059.txt`

## Teardown/Redeploy Execution

Harness path used:

```bash
scripts/teardown-deploy-test.sh cycle --execute --approval-text "approve" --approval-packet /tmp/teardown-approval-20260522-011241.md --stamp 20260522-011241
```

Initial cycle run status:

- `destroy`: passed
- `deploy-foundation`: passed
- `deploy-edge`: passed
- `activate-edge`: passed
- `deploy-platform`: failed at `deploy-netbox-stack`

Failure cause:

- `configure-keyctl.yml` required `pve_host`, but direct-access inventory no longer emits that host var by default.

Fix applied during this session:

- `terraform/lxc/ansible/playbooks/configure-keyctl.yml`
  - Added `proxmox_delegate_host` fallback (`pve_host` -> `PVE_TEST_FQDN` -> `pve-test.gibbsgreatly.xyz`).

Resume command:

```bash
scripts/teardown-deploy-test.sh deploy-platform --execute --approval-text "approve" --stamp 20260522-011241
scripts/teardown-deploy-test.sh final-validation --stamp 20260522-011241
```

Resume status:

- `deploy-platform`: passed
- `final-validation`: passed

Evidence stamp:

- `docs/teardown-test/evidence/20260522-011241/`

## SDN Attachment Confirmation

Post-destroy redeploy logs show SDN attachment orchestration running and passing (`configure_network_sdn_attachment`) during stack apply.

Representative evidence logs:

- `docs/teardown-test/evidence/20260522-011241/logs/deploy-apt-cacher-stack.log`
- `docs/teardown-test/evidence/20260522-011241/logs/deploy-dns-stack.log`
- `docs/teardown-test/evidence/20260522-011241/logs/deploy-proxy-stack.log`

## Post-Rebuild Direct-Access Evidence

Post-redeploy preflight (explicit representative guest IPs):

```bash
./with-secrets scripts/preflight-network-refactor.sh --save-evidence docs/teardown-test/evidence 192.168.40.11 192.168.20.13 192.168.30.10
```

Result: PASS

Evidence:

- `docs/teardown-test/evidence/preflight-evidence-20260522-135237.txt`

Observed:

1. Target guard passed (`TF_VAR_proxmox_node = pve-test`).
2. All SDN gateways reachable (`192.168.10.1`, `.20.1`, `.30.1`, `.40.1`).
3. DNS via MikroTik gateway (`192.168.20.1`) resolved internal and public names.
4. TCP:22 reachable for representative guest IPs in infra/mgmt/edge zones.

## No Default ProxyJump Evidence

Representative generated inventories after rebuild:

- `terraform/lxc/stacks/apt-cacher-stack/inventory.yml`
- `terraform/lxc/stacks/dns-stack/inventory.yml`
- `terraform/lxc/stacks/proxy-stack/inventory.yml`

Observed:

1. `ssh_access_mode: direct` for all three representatives.
2. `ansible_host` set directly to guest IP.
3. No `ProxyJump` token present.
4. No `pve_host` key present.

## No Host-Route Priming Dependency Evidence

Representative state inspection:

```bash
./with-secrets bash -lc 'for s in apt-cacher-stack dns-stack proxy-stack; do
  cd terraform/lxc/stacks/$s
  terragrunt state list | rg "prime_sdn_host_route|configure_network_sdn_attachment|local_file.ansible_inventory" || true
  cd - >/dev/null
done'
```

Observed:

1. `local_file.ansible_inventory` and `null_resource.configure_network_sdn_attachment[0]` present.
2. No `prime_sdn_host_route` entries present.
3. No manual host-side route priming step required to complete apply/provision/final-validation.

## Representative Stack Health After Rebuild

Representative stacks validated in required order through harness phase logs:

1. `apt-cacher-stack` (infra_seg): deploy/provision/pct/health passed.
2. `dns-stack` (mgmt_seg): deploy/provision/pct/authoritative+delegated DNS checks passed.
3. `proxy-stack` (edge_seg): deploy/provision/pct/HTTPS route health passed.

Representative evidence logs:

- `docs/teardown-test/evidence/20260522-011241/logs/deploy-apt-cacher-stack.log`
- `docs/teardown-test/evidence/20260522-011241/logs/health-apt-cacher-stack.log`
- `docs/teardown-test/evidence/20260522-011241/logs/deploy-dns-stack.log`
- `docs/teardown-test/evidence/20260522-011241/logs/health-dns-stack-delegated.log`
- `docs/teardown-test/evidence/20260522-011241/logs/deploy-proxy-stack.log`
- `docs/teardown-test/evidence/20260522-011241/logs/health-proxy-stack.log`

## Final Gate Verdict

Network refactor teardown/redeploy validation gate on `pve-test`: **YES (PASSED)**.

Rationale:

1. Full teardown and redeploy lifecycle completed (with resume after one code-level blocker fix).
2. Direct-access path remains in effect post-rebuild.
3. No default ProxyJump usage in representative inventories.
4. No host-route priming dependency observed.
5. DNS and routed service checks through MikroTik gateway path passed after rebuild.

## Blockers Before Promotion Or Canary Resume

No unresolved network-path blockers remain from Session 8.

Resolved within session:

- `configure-keyctl.yml` dependence on `pve_host` for direct-mode inventories.

Tracking note:

- Harness `state.json` still records `cycle: failed` from the first interrupted run, while resumed phases (`deploy-platform`, `final-validation`) are recorded as passed for the same stamp.
- Use log evidence under stamp `20260522-011241` as the authoritative completion record.
