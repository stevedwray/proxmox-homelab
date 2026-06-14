# Session 6 Summary — Preflight and Evidence Capture

Date: 2026-05-22

## What Was Done

Session 6 implemented the preflight validation tool and evidence-capture
mechanism specified in the Session 3 decision outcomes.

### 1. Preflight script created

`scripts/preflight-network-refactor.sh`

Standalone bash script. Invoke via `./with-secrets` (required so the
targeting guard can verify `TF_VAR_proxmox_node`).

Four checks in order:

| # | Check | Type |
|---|-------|------|
| 1 | `TF_VAR_proxmox_node == pve-test` | Hard fail |
| 2 | ICMP ping to all four SDN gateways (192.168.10.1 – 192.168.40.1) | Hard fail |
| 3 | DNS via mgmt_seg gateway (192.168.20.1): internal and public name | Hard fail |
| 4 | TCP:22 reachability to at least one representative guest IP | Hard fail (explicit IPs) / Warn (default candidates only) |

Exit code 0 = all required checks passed. Exit code 1 = at least one failed.

The script accepts optional guest IPs as positional arguments:

```sh
./with-secrets scripts/preflight-network-refactor.sh 192.168.40.11 192.168.30.10
```

To save a copy of the output for evidence:

```sh
./with-secrets scripts/preflight-network-refactor.sh \
    --save-evidence docs/sessions/ 192.168.40.11
```

### 2. validation-gate.md updated

Added a "Preflight Script" section at the top with:
- Standard, explicit-IP, and evidence-capture invocations
- Per-check explanations (why each check matters, what failure means)
- Default guest candidate list
- Manual `dig` equivalent commands for the DNS checks

### 3. plan.md updated

Session 6 implementation note added under the Session 6 heading.

## Session 6 Validation Run

The script was run from `garuda` (operator workstation, not currently on the
lab LAN) to verify it runs to completion:

```
Check 1: PASS — TF_VAR_proxmox_node = pve-test
Check 2: FAIL — all four SDN gateways unreachable (workstation offline from lab)
Check 3: FAIL — DNS unreachable (gateway offline)
Check 4: WARN — no default candidate guests reachable (none deployed)
Exit: 1
```

The failures are expected. The workstation is not currently connected to the
lab LAN, so the MikroTik VLAN gateways are unreachable. The script correctly
identified this and failed fast without producing misleading output.

## Preflight Checks Implementation Checklist

| Item | Status |
|------|--------|
| Script exists and is executable | Done |
| Bash syntax valid | Done (`bash -n` passes) |
| Runs to completion with proper exit codes | Done |
| All four checks implemented | Done |
| Evidence file output (`--save-evidence`) | Done |
| `--no-colour` flag for log capture | Done |
| `--help` output | Done |
| validation-gate.md updated | Done |
| plan.md Session 6 note added | Done |

## Can Session 7 Begin?

**Yes, with one prerequisite step first.**

Before Session 7 can run representative stack validation, the operator must:

1. Be on the lab LAN (or have a path to the MikroTik from the workstation).
2. Run the preflight script and confirm all four checks pass.
3. Capture the evidence output with `--save-evidence`.

Once the preflight script exits 0, Session 7 may proceed directly to
representative stack validation in the order specified in plan.md:

1. `apt-cacher-stack` (infra_seg, 192.168.40.11)
2. One mgmt_seg stack (`dns-stack` or `step-ca-stack`)
3. One additional SDN-backed stack if needed

The preflight script will surface any remaining MikroTik prerequisite gaps
before any Terraform apply is attempted.

## Open Items for Session 7

1. Run `./with-secrets scripts/preflight-network-refactor.sh 192.168.40.11` once
   on the lab LAN and confirm exit code 0.
2. Save the evidence output.
3. Begin representative stack validation per plan.md Session 7.
4. Note any stacks still labeled `proxyjump_compat` that will need migration
   before the teardown gate can pass.
