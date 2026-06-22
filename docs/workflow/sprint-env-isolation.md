# Sprint: Environment Isolation (pve-test-vm)

**Scope:** Give pve-test-vm its own non-overlapping IP ranges and DNS subzone so
it can run alongside pve as a persistent staging environment.

**Promotion target:** `stable` only. These changes are pve-test-vm specific and
do not go to `main` until the legacy app integration sprint.

**Branch:** `work/sprint-env-isolation` — cut from `stable` after `work/sprint-harness`
merges. All sessions (E-1 through E-3) land here directly. Delete after merge to
`stable`. Sub-branches only if a session needs isolated review.

**Prerequisite:** [sprint-harness.md](sprint-harness.md) H-2 complete — smoke
tests must exist to validate the reprovision in session E-2.

---

## Decided IP scheme

Pattern: **same subnets as pve, last octet + 100**. pve and pve-test-vm share
the same VLANs and physical L2 infrastructure, so pve-test-vm containers stay
in the same `192.168.x.x` subnets. Containers are distinguished by last octet:
pve uses the base allocation; pve-test-vm adds 100.

No MikroTik subnet changes required — the VLAN interfaces and gateways are
already correct. Only a DNS forwarding rule needs to be added.

### Subnets and gateways (shared, unchanged)

| Zone | VLAN ID | Subnet | Gateway |
|---|---|---|---|
| `build_seg` | 10 | `192.168.10.0/24` | `192.168.10.1` |
| `mgmt_seg` | 20 | `192.168.20.0/24` | `192.168.20.1` |
| `edge_seg` | 30 | `192.168.30.0/24` | `192.168.30.1` |
| `infra_seg` | 40 | `192.168.40.0/24` | `192.168.40.1` |

### Container IPs

| Container | pve IP | pve-test-vm IP |
|---|---|---|
| ci-runner-01 | `192.168.10.63` | `192.168.10.163` |
| Portainer | `192.168.20.20` | `192.168.20.120` |
| Authentik | `192.168.20.10` | `192.168.20.110` |
| step-ca | `192.168.20.11` | `192.168.20.111` |
| Monitoring | `192.168.20.12` | `192.168.20.112` |
| CoreDNS | `192.168.20.13` | `192.168.20.113` |
| Traefik | `192.168.30.10` | `192.168.30.110` |
| Harbor | `192.168.40.10` | `192.168.40.110` |
| apt-cacher-ng | `192.168.40.11` | `192.168.40.111` |
| NetBox | `192.168.40.12` | `192.168.40.112` |

### DNS

| Environment | Zone | Authority |
|---|---|---|
| pve | `lab.gibbsgreatly.xyz` | CoreDNS at `192.168.20.13` |
| pve-test-vm | `test.gibbsgreatly.xyz` | CoreDNS at `192.168.20.113` |

`LAB_DOMAIN` in `.env.pve-test-vm` changes from `lab.gibbsgreatly.xyz` to
`test.gibbsgreatly.xyz`. All FQDN construction (Harbor, Authentik, Grafana,
etc.) should derive from `LAB_DOMAIN`.

Current concern: not every route and zone renderer is guaranteed to be
environment-derived yet. E-1 must audit and fix hardcoded
`lab.gibbsgreatly.xyz` references before E-2, especially CoreDNS seed records,
EdgeManifest hosts, edge-manifest validation suffixes, and stack-level registry
host settings.

Traefik on pve-test-vm requests its own wildcard cert (`*.test.gibbsgreatly.xyz`)
via DNS-01 Cloudflare — independent from pve's `*.gibbsgreatly.xyz` cert. No
conflict; LE treats them as separate domains.

---

## Session E-1 — Config changes (no live infra)

**Branch:** `work/sprint-env-isolation`
**Live infra required:** No
**Promotion gate:** `ansible-playbook --syntax-check` on all platform playbooks;
`terraform validate` on `terraform/lxc/network/`; diff shows only pve-test-vm
values changed — pve env files untouched

### Tasks

**E-1a — Update `.env.pve-test-vm.template`**

Update container IP variables to the +100 last-octet values. Gateway variables
are unchanged (same subnets as pve):

```
# Gateways unchanged — same subnets as pve
LAB_GW_BUILD=192.168.10.1
LAB_GW_MGMT=192.168.20.1
LAB_GW_EDGE=192.168.30.1
LAB_GW_INFRA=192.168.40.1

# Container IPs — last octet + 100
LAB_IP_CI_RUNNER=192.168.10.163
LAB_IP_PORTAINER=192.168.20.120
LAB_IP_AUTHENTIK=192.168.20.110
LAB_IP_STEP_CA=192.168.20.111
LAB_IP_MONITORING=192.168.20.112
LAB_IP_DNS=192.168.20.113
LAB_IP_PROXY=192.168.30.110
LAB_IP_HARBOR=192.168.40.110
LAB_IP_APT_CACHER=192.168.40.111
LAB_IP_NETBOX=192.168.40.112

LAB_DOMAIN=test.gibbsgreatly.xyz
```

Verify that `.env.pve.template` and `.env.pve` are not touched.

**E-1b — Update `docs/design/network.md` pve-test-vm section**

Add a pve-test-vm container IP table documenting the +100 last-octet scheme and
the `test.gibbsgreatly.xyz` subzone. Note that subnets, gateways, and VLAN IDs
are shared with pve.

**E-1c — Verify Terraform network module**

`terraform/lxc/network/pve-test-vm.yaml` subnet and gateway values should be
unchanged (same as pve). Confirm container IP assignments in the network config
pick up `LAB_IP_*` env vars rather than hardcoded addresses.

**E-1d — CoreDNS zone files**

The authority zone must reflect `test.gibbsgreatly.xyz` when deployed to
pve-test-vm.

Audit and update:

- `terraform/lxc/ansible/files/coredns-lab.zone`: do not leave `$ORIGIN`, SOA,
  or NS records hardcoded to `lab.gibbsgreatly.xyz`.
- `terraform/lxc/render-edge-coredns.py`: generated records must use the active
  zone derived from `LAB_DOMAIN`, not only the seed zone's hardcoded origin.
- `terraform/lxc/ansible/playbooks/deploy-coredns.yml`: the published zone and
  validation checks must agree on `lab_domain`.

If a zone name is hardcoded, extract it to use the Ansible `lab_domain` variable
sourced from `LAB_DOMAIN`, or a renderer input that is populated from
`LAB_DOMAIN`.

**E-1e — Edge routes and registry hostnames**

Audit stack-owned edge and registry settings for hardcoded production-zone names.
At minimum, check:

- `terraform/lxc/stacks/*/edge.yaml` route hosts
- `terraform/lxc/edge_manifest.py` domain-suffix validation
- `terraform/lxc/stacks/netbox-stack/stack.yaml` and inventory registry host
  values
- Any generated Traefik or Authentik reconciliation inputs that use route hosts

Recommendation: allow route hosts to be expressed as environment-derived values,
for example `service.${LAB_DOMAIN}`, or teach the edge manifest loader/renderer
to substitute a documented `${LAB_DOMAIN}` placeholder before validation.
Validation should require the active `LAB_DOMAIN` suffix, not a fixed
`.lab.gibbsgreatly.xyz` suffix.

**E-1f — Mark tracking table complete in `environments.md`**

Update the implementation tracking table in `docs/workflow/environments.md`
for the items completed in this session.

### Handoff state

- `.env.pve-test-vm.template` container IPs updated to +100 last-octet values; gateways unchanged
- `LAB_DOMAIN=test.gibbsgreatly.xyz` set in template
- CoreDNS zone file uses `LAB_DOMAIN` variable (not hardcoded)
- Edge manifests, edge validation, generated DNS, and registry hostnames are
  environment-derived
- Syntax checks and `terraform validate` pass
- Existing pve env files untouched (confirm with `git diff`)

---

## Session E-2 — MikroTik prerequisite + full rebuild validation

**Branch:** `work/sprint-env-isolation` (continued)
**Live infra required:** Yes — pve-test-vm must be torn down and rebuilt from scratch

### MikroTik manual prerequisite (operator action before session)

The MikroTik has no IaC (TM-09). This change must be applied manually before
the teardown validation can run.

pve-test-vm containers share the same VLANs, subnets, and gateways as pve.
The MikroTik VLAN interfaces and ACL rules are already correct — pve-test-vm
containers at `.110-.163` are within the existing `/24` subnets and subject to
the same cross-zone policy (see [docs/design/network.md](../design/network.md)).
Control node routing is unchanged (same `192.168.x.x` space).

Required MikroTik change — one rule only:

1. **DNS forwarding rule**: forward `test.gibbsgreatly.xyz` to CoreDNS at
   `192.168.20.113` (mirroring the existing rule for `lab.gibbsgreatly.xyz` → `192.168.20.13`).

### Full rebuild validation

Once MikroTik is configured:

```bash
# Destroy existing pve-test-vm state
PVE_ENV=pve-test-vm ./with-secrets terragrunt run-all destroy --terragrunt-non-interactive

# Recreate infrastructure with the new IP scheme
PVE_ENV=pve-test-vm ./with-secrets terragrunt run-all apply --terragrunt-non-interactive

# Configure and smoke-test platform services
PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --tier platform
```

Expected result: all platform-stack smoke tests pass on the new container IPs.

Recommendation: once a dedicated rebuild harness exists, replace the three
manual commands above with that single command. The rebuild harness must make the
target environment explicit before secrets are loaded, run Terraform/Terragrunt
creation as well as Ansible configuration, and publish a concise smoke-test
summary.

### Handoff state

- DNS forwarding rule for `test.gibbsgreatly.xyz` → `192.168.20.113` active on MikroTik
- Full rebuild succeeded on pve-test-vm
- All platform smoke tests pass on new IPs
- Branch merged to `stable`

---

## Session E-3 — DNS subzone and routing documentation

**Branch:** `work/sprint-env-isolation` (continued)
**Live infra required:** Partial — DNS registration is external; smoke test
with FQDNs requires E-2 running

### Tasks

**E-3a — Register `test.gibbsgreatly.xyz` in Cloudflare**

`test.gibbsgreatly.xyz` is a peer zone to `lab.gibbsgreatly.xyz` — a flat sibling,
not a subzone. MikroTik forwards queries for `test.gibbsgreatly.xyz` to CoreDNS
at `192.168.20.113` (mirroring the `lab.gibbsgreatly.xyz` → `192.168.20.13` rule).

For public/browser-facing routes (Traefik): add a `*.test.gibbsgreatly.xyz`
wildcard `A` record in Cloudflare pointing to the pve-test-vm edge (or the control
node's NAT, if applicable). Traefik requests the LE cert automatically via DNS-01.

For internal-only services, no Cloudflare records are needed — CoreDNS resolves
them within the test network.

**E-3b — Smoke test with FQDNs**

Verify end-to-end FQDN resolution from the control node:

```bash
curl -sf "https://harbor.test.gibbsgreatly.xyz/api/v2.0/health"
curl -sf "https://authentik.test.gibbsgreatly.xyz/api/v3/root/config/"
```

These should resolve and respond correctly once both E-2 and E-3a are done.

**E-3c — Update `environments.md`**

Mark all tracking table items complete. No control node routing changes are
required — pve-test-vm uses the same `192.168.x.x` space already reachable.

### Handoff state

- `test.gibbsgreatly.xyz` resolves from control node
- FQDN-based smoke test for harbor and authentik passes
- `environments.md` tracking table fully checked off
- Branch merged to `stable`

---

## Validation tiers

| Session | Change class | Minimum validation |
|---|---|---|
| E-1 | Ansible var / template changes | `--syntax-check` all platform playbooks; `terraform validate` |
| E-2 | Network / SDN change (pve-test-vm) | Full rebuild cycle on pve-test-vm |
| E-3 | External DNS + smoke test | FQDN smoke test passes from control node |

---

## Secrets model

For `PVE_ENV=pve-test-vm`, `with-secrets` prefers
`terraform/secrets.pve-test-vm.enc.yaml` when present and falls back to
`terraform/secrets.enc.yaml`. Keep the docs, templates, and actual wrapper
behaviour aligned before running E-2 so operators know which file is authoritative.

The only values that **must** differ between the pve-test-vm secrets file and
`secrets.pve.enc.yaml` (pve) are the Proxmox API credentials:

```
TF_VAR_proxmox_token_id
TF_VAR_proxmox_token_secret
```

Everything else — service admin passwords, OIDC/OAuth client secrets, Authentik
secret key, step-ca provisioner password — can be identical across both files.
OIDC client secrets (`GRAFANA_OAUTH_CLIENT_SECRET`, `HARBOR_OIDC_CLIENT_SECRET`,
`PORTAINER_OAUTH_CLIENT_SECRET`) are locally meaningful within each environment;
sharing the same value across environments carries no security risk.

Practical rule: when rotating a service password, update it to the same value in
both files. Only Proxmox API creds need environment-specific values.

To edit a SOPS-encrypted secrets file:
```bash
sops terraform/secrets.pve-test-vm.enc.yaml  # pve-test-vm, if present
sops terraform/secrets.enc.yaml              # shared/fallback test secrets
sops terraform/secrets.pve.enc.yaml          # pve
```

To verify resolved values without decrypting manually:
```bash
PVE_ENV=pve-test-vm ./with-secrets env | grep TF_VAR_proxmox
PVE_ENV=pve-test-vm ./with-secrets env | grep HARBOR_ADMIN
```

---

## Promotion scan handling

E-1 changes YAML, shell-adjacent configuration, and possibly Python renderers.
E-2 may change Terraform/network inputs. Before promotion, run the scans required
by the final diff:

- Terraform changed: `/home/steve/.local/bin/snyk iac test terraform/`
- Python, shell, YAML, Ansible, or workflow files changed:
  `./with-secrets /home/steve/.local/bin/sonar-scanner`

For every new actionable scan finding, create a GitHub issue with the scan
evidence and mark whether it blocks promotion. Do not merge until blocking
findings are fixed or explicitly accepted by the operator.

---

## What this enables

Once E-3 is complete:

- pve-test-vm can run continuously alongside pve with no DNS collision; container
  IPs are distinct (last octet +100) within the shared subnets
- The monitoring stack on pve-test-vm can coexist with pve without scrape target
  label conflicts (different IPs, different zone in labels)
- Smoke tests and integration checks can use FQDNs instead of hardcoded IPs
- The environment isolation items in `environments.md` are fully resolved
