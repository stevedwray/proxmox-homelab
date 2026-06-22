# Environments

## Overview

Two environments: **pve-test** (staging / development validation) and **pve**
(production). Both are managed from the same repo. Environment selection is
controlled by env file and secrets file.

| | pve-test-vm | pve |
|---|---|---|
| Hardware | VM (bare-metal laptop host) | Production server |
| Env file | `.env.pve-test-vm` | `.env.pve` |
| Secrets file | `terraform/secrets.pve-test-vm.enc.yaml` preferred; `terraform/secrets.enc.yaml` fallback | `terraform/secrets.pve.enc.yaml` |
| Wrapper | `./with-secrets` | `./with-secrets-prod` |
| Proxmox node | `pve-test-vm` | `pve` |
| Purpose | Validation, staging | Production workloads |

---

## Current State: Shared IP Ranges

pve-test-vm currently uses the same container IPs as pve. pve-test-vm shares the
same VLANs and physical L2 infrastructure as pve (same MikroTik trunk), so a
separate IP prefix is not viable. This creates friction:

- You cannot scrape or monitor both environments simultaneously from one
  VictoriaMetrics instance without target label collisions.
- DNS records in CoreDNS for both environments resolve to the same IPs, making it
  impossible to reach both from the same control node.

This is acceptable while pve-test-vm is purely ephemeral. It becomes a problem
when running both environments in parallel as a persistent staging setup.

---

## Target State: Distinct IPs and DNS

For pve-test-vm to function as a persistent staging environment alongside pve:

### 1. Distinct container IPs (last octet + 100)

pve-test-vm shares the same VLANs and subnets as pve. Container IPs are
distinguished by adding 100 to the last octet. No MikroTik subnet changes needed.

| Container | pve IP | pve-test-vm IP |
|---|---|---|
| Authentik | `192.168.20.10` | `192.168.20.110` |
| step-ca | `192.168.20.11` | `192.168.20.111` |
| Monitoring | `192.168.20.12` | `192.168.20.112` |
| CoreDNS | `192.168.20.13` | `192.168.20.113` |
| Portainer | `192.168.20.20` | `192.168.20.120` |
| Traefik | `192.168.30.10` | `192.168.30.110` |
| Harbor | `192.168.40.10` | `192.168.40.110` |
| apt-cacher-ng | `192.168.40.11` | `192.168.40.111` |
| NetBox | `192.168.40.12` | `192.168.40.112` |
| ci-runner-01 | `192.168.10.63` | `192.168.10.163` |

### 2. Distinct DNS zone

```
lab.gibbsgreatly.xyz          ← pve (production), CoreDNS at 192.168.20.13
test.gibbsgreatly.xyz         ← pve-test-vm (staging), CoreDNS at 192.168.20.113
```

`LAB_DOMAIN=test.gibbsgreatly.xyz` in `.env.pve-test-vm`. All FQDN construction
should derive from `LAB_DOMAIN`.

Implementation concern: existing stack-owned edge manifests, CoreDNS seed data,
edge validation, and some registry host settings may still assume
`lab.gibbsgreatly.xyz`. The environment-isolation sprint must remove or template
those assumptions before pve-test-vm can safely run as `test.gibbsgreatly.xyz`.

MikroTik requires one new forwarding rule: `test.gibbsgreatly.xyz` → `192.168.20.113`.

### 3. Secrets (already isolated)

Separate secrets files already exist:
- `secrets.pve-test-vm.enc.yaml` — pve-test-vm when `PVE_ENV=pve-test-vm`
- `secrets.enc.yaml` — shared/fallback test secrets loaded by `./with-secrets`
- `secrets.pve.enc.yaml` — pve (loaded by `./with-secrets-prod`)

Only Proxmox API credentials must differ. Service passwords and OIDC client
secrets can be identical across both files.

---

## What This Enables

Once pve-test-vm has distinct IPs and DNS:

- **Parallel operation**: pve-test-vm can run continuously alongside pve. Changes
  can be validated on a live staging environment before being promoted to pve.
- **Shared monitoring**: a monitoring stack can scrape both environments with
  environment labels distinguishing the data (different container IPs, different zone).
- **DNS-based smoke tests**: health checks resolve FQDNs under `test.gibbsgreatly.xyz`
  rather than hardcoded IPs, making the test harness environment-agnostic.

## Implementation Work Required

Tracked in [sprint-env-isolation.md](sprint-env-isolation.md). Sessions E-1 through E-3.

| Item | File(s) to update | Status |
|---|---|---|
| Update container IPs (+100 last octet) | `.env.pve-test-vm.template` | ✓ done |
| Set DNS zone + re-derive FQDNs | `.env.pve-test-vm.template` (`LAB_DOMAIN`, `LAB_FQDN_*`) | ✓ done |
| Update pve-test-vm IP snapshot | `terraform/lxc/network/pve-test-vm.zone-members.yaml` | ✓ done |
| Document pve-test-vm IP table | `docs/design/network.md` | ✓ done |
| Template CoreDNS zone origin and authority | `terraform/lxc/ansible/files/coredns-lab.zone`, `deploy-coredns.yml` | ✓ done |
| Template edge route hosts and validation suffix | `terraform/lxc/stacks/*/edge.yaml`, `terraform/lxc/edge_manifest.py` | ✓ done |
| Add MikroTik DNS forwarding rule | MikroTik REST API — `test-zone-delegate` FWD `(^|\.)test\.gibbsgreatly\.xyz$` → `192.168.20.113` | ✓ done |
| Cloudflare DNS-01 for `*.test.gibbsgreatly.xyz` | No action — parent zone `gibbsgreatly.xyz` in Cloudflare; existing `CF_DNS_API_TOKEN` handles it | ✓ n/a |
| Full rebuild validation | pve-test-vm full reprovision + smoke tests green | E-2 pending |
