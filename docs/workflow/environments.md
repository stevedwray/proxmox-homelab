# Environments

## Overview

Two environments: **pve-test** (staging / development validation) and **pve**
(production). Both are managed from the same repo. Environment selection is
controlled by env file and secrets file.

| | pve-test | pve |
|---|---|---|
| Hardware | Bare-metal laptop (16 GB) | Production server |
| Env file | `.env.pve-test` | `.env.pve` |
| Secrets file | `terraform/secrets.enc.yaml` | `terraform/secrets.pve.enc.yaml` |
| Wrapper | `./with-secrets` | `./with-secrets-prod` |
| Proxmox node | `pve-test` | `pve` |
| Purpose | Validation, teardown testing | Production workloads |

---

## Current State: Shared IP Ranges

pve-test currently uses the same IP ranges as pve. This works when the two
environments are fully network-isolated from each other (separate physical
hardware, no cross-routing), but it creates friction:

- You cannot scrape or monitor both environments simultaneously from one
  VictoriaMetrics instance without target label collisions.
- DNS records in CoreDNS for both environments would resolve to the same IPs,
  making it impossible to reach both from the same control node.
- Secrets and tokens generated for pve-test must be kept separate from pve, but
  there is no automatic enforcement when the IPs are identical.

This is acceptable while pve-test is purely ephemeral (tear down and rebuild from
scratch each time). It becomes a problem if pve-test is intended to run in
parallel with pve as a staging environment.

---

## Target State: Full Isolation

For pve-test to function as a genuine staging environment that can run alongside
pve:

### 1. Distinct IP ranges

pve-test must use IP ranges that do not overlap with pve. The specific ranges are
recorded in `.env.pve-test.template`; they need to be updated to non-overlapping
values.

Suggested approach: shift all pve-test management and infrastructure subnets to a
distinct prefix (e.g., `10.20.x.x` vs `192.168.x.x` for pve). The VLAN IDs
themselves can remain the same (they are internal to each Proxmox node), but the
L3 addresses must differ.

### 2. Distinct DNS subzone

pve uses `lab.gibbsgreatly.xyz`. pve-test should use a separate subzone so DNS
records for both can exist simultaneously and be independently maintained:

```
lab.gibbsgreatly.xyz          ← pve (production)
test.lab.gibbsgreatly.xyz     ← pve-test (staging)
```

Alternatively `lab-test.gibbsgreatly.xyz` as a flat sibling rather than a
subzone. Either works; the key requirement is that the zone is distinct and both
can be delegated independently.

`LAB_DOMAIN` in `.env.pve-test` would be set to the test zone. All FQDN
construction (Harbor, Grafana, Authentik, etc.) derives from `LAB_DOMAIN`, so no
other changes are needed once the variable is set correctly.

### 3. Secrets independence (already done)

Separate secrets files already exist:
- `secrets.enc.yaml` — pve-test secrets (loaded by `./with-secrets`)
- `secrets.pve.enc.yaml` — pve secrets (loaded by `./with-secrets-prod`)

No changes needed here.

### 4. Control node routing

Once pve-test uses distinct IP ranges, the control node (dev machine) needs routes
to both environments. This is typically handled by the VPN or direct connection to
each Proxmox node; document the required routes in this file once the IP scheme is
decided.

---

## What Full Isolation Enables

Once pve-test has distinct IPs and DNS:

- **Parallel operation**: pve-test can run continuously alongside pve, not just
  during teardown cycles. Changes can be validated on a live staging environment
  before being promoted to pve.
- **Shared monitoring**: a monitoring stack (or the control node) can scrape both
  environments, with environment labels distinguishing the data.
- **DNS-based smoke tests**: health checks can resolve FQDNs rather than hardcoding
  IPs, making the test harness environment-agnostic.
- **Credential isolation**: pve-test can have its own user accounts, OIDC clients,
  and API tokens with no risk of them colliding with pve credentials.

---

## Implementation Work Required

This is a tracking list, not a completed implementation.

| Item | File(s) to update | Notes |
|---|---|---|
| Define pve-test IP ranges | `.env.pve-test.template` | Must not overlap with `.env.pve.template` |
| Define pve-test DNS subzone | `.env.pve-test.template` (`LAB_DOMAIN`) | e.g., `test.lab.gibbsgreatly.xyz` |
| Delegate DNS subzone | External DNS / registrar | One-time setup per subzone |
| Update Terraform network module | `terraform/lxc/` network vars | SDN/VLAN gateway IPs derive from env |
| Verify CoreDNS zone files | `terraform/lxc/stacks/dns-stack/` | Zone file must use the test subzone |
| Document control node routing | This file | Add required routes once IP scheme is settled |
| Update `.env.pve-test.template` guidance | `getting-started.md` | Point new operators to correct template |
