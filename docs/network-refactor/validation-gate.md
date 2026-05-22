# Network Refactor Validation Gate

## Purpose

This gate defines the minimum validation required before the network refactor
can be considered complete on `pve-test`.

## Preflight Script

Session 6 added a standalone preflight script that automates all required
checks and produces structured evidence output:

```
scripts/preflight-network-refactor.sh
```

**Standard invocation** (run from repo root):

```sh
./with-secrets scripts/preflight-network-refactor.sh
```

**With explicit representative guest IPs** (recommended once stacks are
deployed):

```sh
./with-secrets scripts/preflight-network-refactor.sh 192.168.40.11 192.168.30.10
```

**With evidence file saved to a session directory:**

```sh
./with-secrets scripts/preflight-network-refactor.sh \
    --save-evidence docs/sessions/ 192.168.40.11
```

Exit code 0 means all required checks passed. Exit code 1 means one or more
required checks failed and the session should not proceed.

If `--save-evidence` points to a directory, the script writes a timestamped
`preflight-evidence-YYYYMMDD-HHMMSS.txt` file there. Keep evidence files in
an ignored directory; summarize results in tracked docs only.

## Preconditions

Before any apply or teardown/redeploy validation:

1. Run `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` and confirm it
   returns `pve-test`. The preflight script performs this check automatically.
2. Confirm the intended branch is a short-lived work branch, not
   `baseline/teardown-validated` or `dev/pve-test`.
3. Confirm the manual MikroTik prerequisites for the SDN zones are present
   (VLAN interfaces, gateway IPs, DNS rules). The preflight script tests the
   observable outcomes; it does not configure the router.
4. Confirm the generated inventory path under test is the new direct-access
   path, not a silent fallback to `ProxyJump`.

## Preflight Checks (performed by the script)

The preflight script runs these four checks in order:

### Check 1 — Targeting guard

Verifies `TF_VAR_proxmox_node == pve-test` in the injected environment.

Required because:

- Operators must invoke `./with-secrets` before any apply.
- A wrong target node would silently run teardown/redeploy against production.

### Check 2 — SDN gateway reachability

Pings each MikroTik VLAN gateway from the workstation:

| Zone       | Gateway IP  |
|------------|-------------|
| build_seg  | 192.168.10.1 |
| mgmt_seg   | 192.168.20.1 |
| edge_seg   | 192.168.30.1 |
| infra_seg  | 192.168.40.1 |

Failure means either the MikroTik VLAN interface is missing or the workstation
does not have a route to that subnet through the router.

### Check 3 — DNS via MikroTik gateway

Queries the `mgmt_seg` gateway (`192.168.20.1`) for:

1. A delegated internal name: `traefik.lab.gibbsgreatly.xyz`
   - Confirms MikroTik static A record or FWD delegation is in place.
2. A public name: `github.com`
   - Confirms MikroTik upstream DNS forwarding is working.

Equivalent manual commands for evidence capture:

```sh
dig @192.168.20.1 +short traefik.lab.gibbsgreatly.xyz
dig @192.168.20.1 +short github.com
```

### Check 4 — Representative guest reachability

Probes TCP:22 on one or more guest IPs to confirm the workstation can reach a
live container through the routed path without `ProxyJump`.

Default candidate list (first reachable wins):

```
192.168.40.11  apt-cacher-stack (infra_seg)
192.168.30.10  proxy-stack / Traefik (edge_seg)
192.168.20.10  authentik-stack (mgmt_seg)
192.168.20.11  step-ca-stack (mgmt_seg)
192.168.20.12  monitoring-stack (mgmt_seg)
192.168.40.10  harbor-stack (infra_seg)
192.168.10.63  ci-runner-01 (build_seg)
```

If no stacks are currently deployed, this check produces a warning rather than
a failure when using the default candidate list. Once stacks are deployed,
pass explicit IPs on the command line to convert this to a hard check.

## Preflight Evidence

Capture evidence for each of these before changing live state. The preflight
script produces a structured summary suitable for pasting into a session doc.
To save a copy automatically, use `--save-evidence docs/sessions/`.

Required evidence items (produced by the script):

1. Targeting guard result (`TF_VAR_proxmox_node = pve-test`)
2. Gateway ping results for all four SDN zones
3. DNS resolution results via `192.168.20.1` for both internal and public names
4. Representative guest TCP:22 probe result

## Representative Live Validation

Before a full teardown/redeploy cycle, validate the new access model on live
stacks in this order:

1. `apt-cacher-stack`
2. one `mgmt_seg` stack such as `dns-stack` or `step-ca-stack`
3. one additional SDN-backed stack if needed

For each stack, capture:

1. generated inventory content
2. SSH path used
3. provisioning result
4. stack-specific health proof
5. confirmation that no Proxmox-side route priming step was required

## Teardown And Redeploy Cycle

Run at least one full validation cycle on `pve-test` after the representative
live checks succeed.

Required sequence:

1. ensure preflight evidence is current
2. run the teardown/redeploy workflow for `pve-test`
3. recreate or confirm SDN zone and VNet attachments
4. reprovision representative stacks
5. rerun DNS and service-health checks
6. capture any manual router actions required during the cycle

## Success Criteria

The refactor passes only if all of these are true:

1. SDN-backed guests are provisioned through the intended router-centric path.
2. No Proxmox host route priming is required.
3. No default `ProxyJump` through Proxmox is required for the validated stacks.
4. DNS works through the intended MikroTik gateway path for validated guests.
5. Representative stack health checks pass after the rebuild.

## Failure Conditions

Stop and document options instead of continuing if:

1. a validated stack still requires `ProxyJump`
2. a validated stack still requires host-side route priming
3. the workstation cannot reach a required SDN subnet through the router
4. DNS works only via public resolver overrides rather than the zone gateway
5. the teardown/redeploy cycle needs undocumented manual recovery steps

## Post-Gate Outputs

When the gate passes, record:

1. commands used
2. evidence locations
3. remaining cleanup items
4. what is now safe to resume from the preserved productionizing work
