# Multi-Source Inventory Gate Closeout (2026-06-13, pve-test-vm)

## Execution Summary

- Branch: feat/netbox-populate-multi-source-inventory
- Final commit at gate run: f4d1f25 (`docs: update current state and lessons learned after pve-test-vm teardown validation`)
- Test target: `pve-test-vm` (`192.168.1.41`) — VM-hosted Proxmox, ZFS pool `infrastructure-containers`
- Evidence stamp: session-level (evidence directories gitignored; summary in netbox-stack/current-state.md)
- Harness command: `PVE_ENV=pve-test-vm ./scripts/teardown-deploy-test.sh cycle --execute`
- End date: 2026-06-13

## Gate Result

**✅ PASSED** — The full teardown + redeploy validation cycle succeeded on `pve-test-vm`.

## Phase Results

All phases in the cycle completed successfully:

- approval-preflight: Passed — clean tree, branch/commit captured, source and live checks passed
- destroy: Passed — all 10 in-scope stacks destroyed cleanly in reverse inventory order
- deploy-foundation: Passed — `apt-cacher-stack` (VMID 40011) and `ci-runner-01` (VMID 10063) applied and provisioned
- deploy-edge: Passed — `dns-stack` (20013), `step-ca-stack` (20011), `proxy-stack` (30010), `authentik-stack` (20010) applied and provisioned
- activate-edge: Passed — edge renders, Authentik reconcile, CoreDNS/Traefik publish, post-activate dry-run all passed
- deploy-platform: Passed — `harbor-stack` (40010), `monitoring-stack` (20012), `netbox-stack` (40012), `portainer-stack` (20020) applied and provisioned
- final-validation: Passed — DNS, HTTPS routes, direct service checks, and final reconcile dry-run all passed

## Target Platform Note

`pve-test-vm` replaces the retired bare-metal `pve-test` laptop as the designated
test target. The teardown harness was extended (commit `d169967`) to support
`pve-test-vm` as an explicit node name via `PVE_ENV`.

## Cold-Start Failures Fixed During This Cycle

Four cold-start failures were discovered and fixed in the same branch:

### 1. Harbor unavailable during Stage 3a deploy (authentik)
- **Commit:** `81f9fe1`
- **Fix:** Added `nc -z` Harbor reachability check in `deploy-authentik-stack.yml`.
  When Harbor is unreachable, all 6 compose images are pre-pulled from public
  registries and tagged with Harbor proxy-cache paths; `pull: "never"` used.
- **Lesson:** [Lesson 8](../../lessons-learned.md) — apply the same pattern to any
  future stack that references Harbor registry paths during cold deploy.

### 2. `netbox_network_env` undefined in populate timer play
- **Commit:** `5df61f0`
- **Fix:** Added `netbox_network_env` to the `vars:` block of play 5 in
  `deploy-netbox-stack.yml`. Ansible play vars do not cross play boundaries.
- **Lesson:** [Lesson 11](../../lessons-learned.md)

### 3. MikroTik 401 crash in netbox-populate
- **Commit:** `aaa4f95`
- **Fix:** Wrapped `discover_from_mikrotik()` with graceful `RuntimeError` catch;
  added `MIKROTIK_ADMIN`/`MIKROTIK_ADMIN_PASSWORD` credential fallback in playbook.

### 4. Portainer "local" endpoint not matching management-stack LXC
- **Commit:** `9459630`
- **Fix:** Resolved `portainer_url` hostname to IP; mapped unix-socket endpoints
  to that IP in the VM/service index.
- **Lesson:** [Lesson 9](../../lessons-learned.md)

### 5. PVE_ENV not propagating to target guard
- **Commits:** `fe9868d`, `a8bab1d`
- **Fix:** Added `PVE_ENV` to the fallback chain before `TF_VAR_proxmox_node` in
  `scripts/teardown-deploy-test.sh` line 24.
- **Lesson:** [Lesson 10](../../lessons-learned.md)

## Final NetBox Populate Result

Validated on pve-test-vm after full redeploy: `VMs: 26, IPs: 34, Services: 56, Stale managed objects: 1`

Sources: pve-test-vm (12 LXCs), pve (14 LXCs via Portainer API), MikroTik hAP.

## Promotion Status

This successful cycle satisfies the `baseline/teardown-validated` promotion gate
for branch `feat/netbox-populate-multi-source-inventory`.

**Gate Requirements Met:**
- ✅ Full teardown validation: all stacks destroyed cleanly in order
- ✅ Full redeploy validation: all stacks redeployed, provisioned, and healthy
- ✅ Final validation: DNS, HTTPS routes, direct service checks, and reconcile all passed
- ✅ All cold-start failures identified and fixed in the same branch
- ✅ No unrelated churn; fixes are scoped to the branch purpose
