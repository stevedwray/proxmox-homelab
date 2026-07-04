# Current State — `dns-stack` (CoreDNS)

This is the baseline a Technitium replacement must account for. Sourced from
[terraform/lxc/stacks/dns-stack/STACK_CONTRACT.md](../../terraform/lxc/stacks/dns-stack/STACK_CONTRACT.md),
[terraform/lxc/stacks/dns-stack/stack.yaml](../../terraform/lxc/stacks/dns-stack/stack.yaml),
[docs/design/network.md](../design/network.md), and
[docs/teardown-test/inventory.md](../teardown-test/inventory.md) — treat
`STACK_CONTRACT.md` as the most authoritative of these if anything drifts.

## Progress of the replacement as of 2026-07-04

The baseline below still describes the original `dns-stack` contract, but in
`pve-test-vm` the active resolver path for `test.gibbsgreatly.xyz` has now
been rehearsed through Technitium: the MikroTik test-zone delegate points to
`192.168.20.115` rather than CoreDNS `192.168.20.113`. CoreDNS remains live
as the previous authority and rollback target.

Alongside it, the replacement stack is now live in `pve-test-vm`:

| Field | Value |
|---|---|
| Replacement stack | `technitium-stack` |
| Zone | `mgmt_seg` |
| IP (`pve-test-vm`) | `192.168.20.115/24` |
| Bootstrap zone | `tech.test.gibbsgreatly.xyz` |
| Browser route | `https://technitium.test.gibbsgreatly.xyz` |
| Auth model | Native OIDC against Authentik |

What is proven:
- Technitium answers authoritatively for the bootstrap zone.
- Technitium performs recursive lookups for external names.
- Traefik routes the admin UI/API successfully.
- Authentik-backed login works end-to-end.
- Technitium also serves a direct-query parity view of
  `test.gibbsgreatly.xyz`, with browser-routed names resolving to Traefik
  and authority records (`dns`, `ns1`) resolving to `192.168.20.115`.
- That parity view is now covered by a checked-in direct-query verification
  matrix (`terraform/lxc/stacks/technitium-stack/verify-parity.sh`) instead
  of ad hoc manual `dig` spot checks.
- The MikroTik resolver path on `pve-test-vm` now also resolves
  `test.gibbsgreatly.xyz` through Technitium successfully:
  browser-routed names still land on Traefik, direct/internal names still
  land on their service IPs, and external recursion still works.
- The full teardown/redeploy gate has now exercised that resolver path
  successfully end-to-end on `pve-test-vm` (stamp `20260703-220525`),
  including final delegated/authoritative DNS checks and edge reconciliation.
- Browser validation after the gate confirmed the main routed services were
  healthy through the usual UI path.

What is not yet true:
- Production (`pve`) still uses the existing CoreDNS-backed client path via
  MikroTik.
- Production Technitium is now live in parallel at `192.168.20.15`,
  serving direct-query parity answers for `lab.gibbsgreatly.xyz`, but no
  production delegate cutover has been attempted.
- The first formal production parity pass exposed a root-authority mismatch
  in Technitium's parity zone (`NS`/`SOA.primaryNameServer` defaulting to
  `tech.lab.gibbsgreatly.xyz`). The publisher fix is now validated on
  `pve-test-vm`, but production still needs a reprovision plus parity rerun
  before cutover can be considered.

## What it is

Internal authoritative nameserver and recursive resolver for the `mgmt_seg`
platform network. Authoritative for `lab.gibbsgreatly.xyz` (pve) /
`test.gibbsgreatly.xyz` (pve-test-vm); recursive resolver for external names.
**Every platform and application stack resolves lab/test FQDNs through this
service** — it is a foundational dependency, not an optional add-on.

## Network position

| Field | Value |
|---|---|
| Zone | `mgmt_seg` |
| IP (pve) | `192.168.20.13/24` |
| IP (pve-test-vm) | `192.168.20.113/24` |
| Gateway | `192.168.20.1` (MikroTik, `mgmt_seg`) |
| VMID | `20013` |
| Resources | 1 core, 1024 MB RAM, 512 MB swap, 8 GB rootfs |

## How it's actually deployed (important for parity)

- **Not containerized.** CoreDNS runs as a bare binary installed from an
  upstream GitHub release tarball, managed as a systemd service
  (`coredns.service`). No Docker, no Harbor pull, no Portainer agent
  (`portainer_agent: false` is intentional for this stack).
- Ansible playbook: `deploy-coredns` (role: `lxc_base`; rest is direct tasks).
- CoreDNS version is pinned (`1.10.1` in playbook vars) — version bumps
  require a full redeploy + version probe.
- **Technitium implication:** Technitium typically ships as a Docker image.
  Adopting it is a deployment-shape change, not just a service swap — it
  would need `docker_storage_size`/`docker_mount` in `stack.yaml`, a
  Harbor-proxied image pull, and possibly a Portainer-agent decision, none
  of which the current CoreDNS contract needs. This is an open design
  question — see [decisions.md](./decisions.md).

## DNS model (two-tier)

1. **MikroTik** (`192.168.<vlan-id>.1` per zone) is the resolver every
   container actually points at (`/etc/resolv.conf`). It answers public
   names directly and conditionally forwards the lab zone.
2. **CoreDNS** (`192.168.20.13` / `.113`) holds authority for the lab zone.
   MikroTik forwards matching queries to it via an `/ip dns static ... type=FWD`
   rule (currently manual — no MikroTik IaC, tracked as TM-09 in
   `docs/design/architecture.md`).

Namespaces:

| Namespace | Resolver | Used for |
|---|---|---|
| `gibbsgreatly.xyz` | Cloudflare public DNS | Public ingress — browser-facing Traefik routes |
| `lab.gibbsgreatly.xyz` | CoreDNS on `pve` (`192.168.20.13`) | Internal platform identity |
| `test.gibbsgreatly.xyz` | Technitium on `pve-test-vm` (`192.168.20.115`) after the 2026-07-04 rehearsal; CoreDNS `192.168.20.113` remains rollback target | Same, for the validation environment |

Operationally in `pve` today:
- Clients still resolve `lab.gibbsgreatly.xyz` through the MikroTik-backed
  CoreDNS path.
- `technitium-stack` is now deployed in parallel at `192.168.20.15`.
- Direct queries against production Technitium return the expected parity
  set, including browser-routed names via `192.168.30.10`, direct/internal
  names (`authentik-int`, `step-ca`), authority records (`dns`, `ns1`),
  and public recursion.
- `https://technitium.lab.gibbsgreatly.xyz` is reachable and OIDC-backed
  admin login is working.
- CoreDNS remains the active production authority only because the
  MikroTik delegate has not yet been repointed.

Operationally in `pve-test-vm` today:
- Clients still point at the MikroTik resolver (`192.168.1.1`), not directly
  at Technitium.
- For the `test.gibbsgreatly.xyz` zone, MikroTik now delegates to
  Technitium, so service-to-service and browser-path resolution for that
  zone depends on Technitium.
- Public recursion still depends on MikroTik's resolver behavior.
- CoreDNS is still deployed in `pve-test-vm`, but as the previous authority
  and rollback target rather than the active delegate target for the `test`
  zone.

## Inputs (from `STACK_CONTRACT.md`)

Mandatory: `LAB_IP_DNS`, `LAB_IP_PROXY`, `LAB_IP_AUTHENTIK`, `LAB_IP_STEP_CA`,
`LAB_IP_MONITORING`, `LAB_IP_PORTAINER`, `LAB_IP_HARBOR`, `LAB_IP_NETBOX`,
`LAB_GW_MGMT`, `COREDNS_LOOPBACK_IP` — these seed the zone template with A
records for every core platform stack. Optional: `LAB_DOMAIN`,
`LAB_FQDN_TRAEFIK`. `coredns_generated_zone_src` lets a reconciler supply a
pre-generated zone file instead of the static seed template — this is the
hook `docs/provisioning-refactor/tasks/08-coredns-renderer.md` and
`docs/provisioning-refactor/tasks/02-dns-ownership-transition.md` use for
stack-owned edge DNS ownership. Any replacement needs an equivalent
integration point.

## Provides

| Service | Port | Protocol |
|---|---|---|
| DNS authority (lab/test zone) | 53 | UDP + TCP |
| DNS recursion (external names) | 53 | UDP + TCP |

## Zone management flow (must be preserved)

- Seed zone template: `ansible/files/coredns-lab.zone`, `${LAB_IP_*}`
  placeholders substituted at deploy time.
- Publish flow: stage candidate zone → validate with `named-checkzone` →
  assert required bootstrap authority records (SOA, NS, `ns1` A record)
  exist → promote. This exists specifically to prevent an accidental loss of
  zone authority records — a Technitium equivalent needs an analogous
  guard, even though Technitium manages zones via its own API/DB rather than
  flat zone files.
- Direct edits to the live zone are explicitly disallowed
  (`coredns_generated_zone_src` is "the only safe way to replace the live
  zone" per the contract).

## Deploy/destroy order (from `docs/teardown-test/inventory.md`)

`dns-stack` deploys **3rd** (after `apt-cacher-stack`, `ci-runner-01`) and is
destroyed **9th of 11** (before only `ci-runner-01`, `apt-cacher-stack`):

Deploy: apt-cacher → ci-runner-01 → **dns-stack** → step-ca → proxy → authentik
→ edge reconciliation → harbor → monitoring → graylog → netbox → portainer.

Destroy: portainer → netbox → graylog → monitoring → harbor → authentik →
step-ca → proxy → **dns-stack** → ci-runner-01 → apt-cacher.

**Implication:** nearly the entire platform is deployed after DNS and torn
down before it. A cutover cannot be a simple "destroy dns-stack, create
technitium-stack" swap without breaking every dependent stack's name
resolution in between — it needs either a dual-running parity window or a
scripted, near-atomic MikroTik forward-rule repoint. Design this explicitly
in `plan.md` before attempting a full teardown validation run.

## Explicit dependents

- `proxy-stack` (Traefik) and `authentik-stack` are called out by the
  contract as requiring lab zone resolution to function.
- Every stack whose smoke test resolves an FQDN rather than a bare IP.
- Effectively all of `mgmt_seg` and `infra_seg`.

## Known gaps in the current implementation

- MikroTik FWD-rule configuration is still manual, not IaC (TM-09), even
  though the `pve-test-vm` rehearsal is now documented.
- The 2026-07-04 rehearsal showed an important RouterOS nuance: the
  existing `test-zone-delegate` entry had to be updated in place
  (`/ip dns static set *53 forward-to=192.168.20.115`) rather than adding a
  second FWD rule with the same regexp.
- The full teardown gate has now exercised the Technitium-backed router
  path successfully on `pve-test-vm`.
