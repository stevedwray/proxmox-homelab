# Session 7 Summary — Representative Stack Validation (Blocked)

Date: 2026-05-22

## Session Goal

Run representative live stack validation for the router-centric provisioning
path in this order:

1. `apt-cacher-stack`
2. one `mgmt_seg` stack (`dns-stack` or `step-ca-stack`)
3. one additional SDN-backed stack if needed

## Required Precondition

Proceed only if preflight exits 0 while the operator is on the lab LAN.

### Commands attempted

1. `./with-secrets preflight-network-refactor.sh 192.168.40.11`
   - Result: command not found (`preflight-network-refactor.sh` is not on PATH
     in this workspace)
2. `./with-secrets scripts/preflight-network-refactor.sh 192.168.40.11`
   - Result: executed, exit code 1

### Preflight results

1. Check 1 (targeting guard): PASS (`TF_VAR_proxmox_node = pve-test`)
2. Check 2 (gateway reachability): FAIL (`192.168.10.1`, `192.168.20.1`,
   `192.168.30.1`, `192.168.40.1` unreachable)
3. Check 3 (DNS via MikroTik): FAIL (`traefik.lab.gibbsgreatly.xyz` and
   `github.com` unresolved via `192.168.20.1`)
4. Check 4 (representative guest reachability): FAIL (`192.168.40.11:22`
   unreachable)

## Outcome

Session 7 live validation did not proceed.

Per the validation gate and session constraints, representative re-apply or
provisioning runs were not executed after preflight failure.

## Findings and Exceptions

1. No new generated inventory evidence was captured from a fresh apply run in
   this session because the precondition failed.
2. No stack-specific health checks were run in this session for
   `apt-cacher-stack`, `dns-stack`/`step-ca-stack`, or additional SDN-backed
   stacks.
3. No evidence was produced for direct SSH path success from workstation to
   guest for this session.
4. The previous compatibility inventory artifacts under stack state/history may
   still show `ProxyJump`; they were not re-validated live in this blocked run.

## Blockers

1. Workstation-to-lab routed path is currently unavailable from this operator
   context (all SDN gateways unreachable).
2. DNS via MikroTik gateway is not reachable from the current operator context.
3. Representative guest TCP:22 is unreachable from this operator context.

## Next Session Restart Checklist

1. Ensure operator workstation is on the lab LAN with route to
   `192.168.10.0/24`–`192.168.40.0/24` through MikroTik.
2. Re-run preflight and require exit 0:
   - `./with-secrets scripts/preflight-network-refactor.sh 192.168.40.11`
3. If preflight passes, run representative validation in order:
   - `apt-cacher-stack`
   - one `mgmt_seg` stack (`dns-stack` or `step-ca-stack`)
   - one additional SDN-backed stack (for example `proxy-stack`) if needed
4. Capture evidence per stack:
   - generated inventory (`ssh_access_mode`, `ansible_ssh_common_args`)
   - SSH/provisioning path (no default `ProxyJump`)
   - DNS behavior via zone gateway
   - stack-specific health check

## Session 8 Readiness

Session 8 teardown/redeploy validation cannot begin yet.

Reason: Session 7 representative live validation prerequisites are not met
(preflight did not pass).
