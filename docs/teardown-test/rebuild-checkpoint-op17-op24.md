# Rebuild Checkpoint: OP-17 through OP-24

**Date**: 2026-04-21
**Branch**: `docs/teardown-test-execution-variables`
**HEAD commit**: `151190d` — fix: recover Portainer stale Docker daemon config
**Status**: All Stage 3a (Edge Foundation) and prerequisite stacks deployed and validated. OP-25 not executed.

---

## Approval Scope Used

Approved block: OP-17 through OP-24 (Stage 2 rebuild: portainer-stack, apt-cacher-stack,
harbor-stack, ci-runner-01 + Stage 3a: dns-stack, proxy-stack, step-ca-stack, authentik-stack).
Target guard required `TF_VAR_proxmox_node=pve-test` before every apply. Stop-on-failure
discipline applied throughout.

---

## OP Status

| OP   | Stack           | VMID | IP           | Status   | Notes                                   |
|------|-----------------|------|--------------|----------|-----------------------------------------|
| OP-17 | portainer-stack | 120  | 10.57.1.20   | PASSED   | Docker active; daemon.json valid; Portainer API HTTP 200 |
| OP-18 | apt-cacher-stack | 142 | 10.57.1.42   | PASSED   | Service active                          |
| OP-19 | harbor-stack    | 121  | 10.57.3.10   | PASSED   | VMID 121 running; /v2/ responding (HTTP 401/200) |
| OP-20 | ci-runner-01    | 141  | 10.57.1.41   | PASSED   | Runner configured; actions-runner service active |
| OP-21 | dns-stack       | 151  | 10.57.1.13   | PASSED   | Path correction retry (see note); auth + delegated DNS pass |
| OP-22 | proxy-stack     | 153  | 10.57.2.10   | PASSED   | Traefik TLS HTTP/2 404 on 443 (expected: no routes yet) |
| OP-23 | step-ca-stack   | 152  | 10.57.1.11   | PASSED   | step-ca active; ACME directory JSON reachable |
| OP-24 | authentik-stack | 150  | 10.57.1.10   | PASSED   | Health endpoint HTTP 200; AUTHENTIK_SUPERUSER_API_TOKEN present |

### OP-21 Path Correction Note

First four apply attempts for dns-stack used the wrong relative path
(`../../../with-secrets` from inside `terraform/lxc/stacks/dns-stack/`).
Corrected to `../../../../with-secrets` (4 levels up to repo root) on the fifth attempt
(`20260421-085032`), which succeeded immediately (9 added, VMID 151 at 10.57.1.13).

### OP-25 Not Executed

OP-25 (edge reconciliation activation) was explicitly held pending a separate approval.
All Stage 3a prerequisites are healthy and ready.

---

## Current VMID State (as of checkpoint)

```
120  running  portainer-stack
121  running  harbor-stack
141  running  ci-runner-01
142  running  apt-cacher-stack
150  running  authentik-stack
151  running  dns-stack
152  running  step-ca
153  running  proxy-stack
```

**Absent (expected — not yet deployed)**:
- VMID 154: monitoring-stack
- VMID 143: netbox-stack

---

## Evidence Directories

| Ops           | Evidence Directory                                         |
|---------------|------------------------------------------------------------|
| OP-07–OP-16 (destroy batch) | `docs/teardown-test/evidence/20260420-194201/logs` |
| OP-17         | `docs/teardown-test/evidence/20260420-202102/logs`         |
| OP-18         | `docs/teardown-test/evidence/20260420-202625/logs`         |
| OP-19         | `docs/teardown-test/evidence/20260420-203835/logs`         |
| OP-20         | `docs/teardown-test/evidence/20260420-204445/logs`         |
| OP-21–OP-24   | `docs/teardown-test/evidence/20260421-085032/logs`         |
| OP-21 path retries | `docs/teardown-test/evidence/20260421-084914/`, `084935/`, `084944/`, `085014/` |

---

## Validation Evidence Summary

### OP-21 dns-stack
- `pct status 151` → `status: running`
- `dig @10.57.1.13 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`
- `dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz` → `10.57.2.10`

### OP-22 proxy-stack
- `pct status 153` → `status: running`
- `curl -skI --resolve traefik.lab.gibbsgreatly.xyz:443:10.57.2.10 https://traefik.lab.gibbsgreatly.xyz/` → `HTTP/2 404`

### OP-23 step-ca-stack
- `pct status 152` → `status: running`
- `pct exec 152 -- systemctl is-active step-ca` → `active`
- `curl -sk https://10.57.1.11/acme/acme/directory` → ACME directory JSON returned

### OP-24 authentik-stack
- `pct status 150` → `status: running`
- `curl -sk -o /dev/null -w '%{http_code}' http://10.57.1.10:9000/-/health/live/` → `200`
- `AUTHENTIK_SUPERUSER_API_TOKEN` present in `with-secrets` environment

---

## Remaining Work

| OP    | Description                                  | Approval Required      |
|-------|----------------------------------------------|------------------------|
| OP-25 | Edge reconciliation activation               | **Separate approval**  |
| OP-26 | Deploy monitoring-stack (VMID 154)           | After OP-25            |
| OP-27 | Deploy netbox-stack (VMID 143)               | After OP-25            |
| OP-28 | Final validation (all services, DNS, routes) | After OP-26 + OP-27    |
| OP-29 | Closeout (docs, commit, branch cleanup)      | After OP-28            |
