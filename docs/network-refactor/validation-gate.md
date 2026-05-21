# Network Refactor Validation Gate

## Purpose

This gate defines the minimum validation required before the network refactor
can be considered complete on `pve-test`.

## Preconditions

Before any apply or teardown/redeploy validation:

1. Run `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` and confirm it
   returns `pve-test`.
2. Confirm the intended branch is a short-lived work branch, not
   `baseline/teardown-validated` or `dev/pve-test`.
3. Confirm the manual MikroTik prerequisites for the SDN zones are present.
4. Confirm the generated inventory path under test is the new direct-access
   path, not a silent fallback to `ProxyJump`.

## Preflight Evidence

Capture evidence for each of these before changing live state:

1. Reach the expected SDN gateways from the workstation:
   - `10.57.0.1`
   - `10.57.1.1`
   - `10.57.2.1`
   - `10.57.3.1`
2. Resolve a delegated internal name through MikroTik:
   - `dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz`
3. Resolve a public name through MikroTik:
   - `dig @10.57.1.1 +short github.com`
4. Reach at least one representative guest IP directly from the workstation.

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
2. a validated stack still requires `prime_sdn_host_route`
3. the workstation cannot reach a required SDN subnet through the router
4. DNS works only via public resolver overrides rather than the zone gateway
5. the teardown/redeploy cycle needs undocumented manual recovery steps

## Post-Gate Outputs

When the gate passes, record:

1. commands used
2. evidence locations
3. remaining cleanup items
4. what is now safe to resume from the preserved productionizing work
