# step-ca Workstreams And Order

## Goal

Define the shortest repo-true execution order for expanding internal TLS with
`step-ca`.

This is an implementation plan, not a redesign.

## Baseline Constraints

- `deploy-step-ca.yml` exports `certs/homelab-root.crt`.
- `lxc_base` and `trust-homelab-ca.yml` are the current trust distribution path.
- Traefik already trusts `step-ca` through `combined-ca.crt` and has a
  `step-ca` ACME resolver.
- Most non-browser backchannels remain HTTP, IP-based, or insecure-verify.
- CoreDNS direct-access records and browser-route records are different paths;
  first direct TLS work should follow current direct-access behavior.
- Deploy order already puts `dns-stack` before `step-ca-stack`, `proxy-stack`,
  and `authentik-stack`, with `activate-edge` publishing generated CoreDNS state
  before Stage 3b platform stacks such as `harbor-stack` and `monitoring-stack`.
- Even with correct deploy order, Docker containers can still inherit stale or
  public resolver upstreams if provisioning temporarily rewrites host
  `/etc/resolv.conf` before container startup.

## Workstreams

| Workstream | Shared vs stack-specific | Current state | Gap to close next |
| --- | --- | --- | --- |
| Trust anchor ownership (`certs/homelab-root.crt`) | Shared | Export and host install path already exist | Make refresh/fingerprint/fan-out workflow explicit |
| Fleet trust rollout | Shared | New hosts inherit via `lxc_base`; retrofit playbook exists | One standard day-2 operator command sequence |
| Internal DNS readiness for TLS consumers | Shared policy + stack runtime checks | DNS stack deploys early, but container resolver state is inconsistent | One standard host-plus-container DNS validation workflow and explicit DNS policy for Docker stacks that need internal names |
| Direct endpoint naming for non-browser clients | Shared policy + stack usage | `*-bg` names are current direct-access truth | Keep using current direct names first; postpone naming redesign |
| First direct certificate consumer | Stack-specific (`authentik-stack`) + shared pattern | Authentik is already central and exposes `9443` | Prove one cert presentation + one verified client |
| Authentik backchannel migration | Stack-specific per consumer | Grafana, Portainer, and Traefik forward-auth are migrated to verified internal direct TLS | Define Harbor-specific migration path for discovery-coupled OIDC endpoints |
| Renewal/expiry/reload checks | Shared + stack hooks | Traefik ACME persistence exists | Define direct-cert renewal ownership + reload checks |
| Higher-blast-radius service TLS | Stack-specific (`harbor-stack`) | Registry trust posture still mixed/insecure | Keep as later track after Authentik pattern is stable |
| CA rotation/compromise procedures | Shared | Minimum manual response path documented | Exercise via tabletop and add stronger verification automation |

## Which Internal Flows Moved First

Completed Authentik consumer migrations:

1. Grafana token/API backchannel
2. Portainer OAuth token/resource path
3. Traefik forward-auth backchannel

Deferred from this tranche:

4. Harbor OIDC reconcile/health path

Rationale:

- same dependency target (`authentik-stack`)
- visible HTTP/insecure patterns today
- DNS resolution failures present as misleading auth/token errors, so fixing the
  Authentik consumer class gives the fastest feedback on both trust and DNS
  readiness
- narrower blast radius than Harbor registry TLS rework

## Trust-Only Versus Active Issuance

Trust-only first:

- `dns-stack`
- `ci-runner-01`
- `apt-cacher-stack`
- `monitoring-stack`, `netbox-stack`, `harbor-stack`, `portainer-stack` host OS trust
- container runtimes that do not yet consume internal service FQDNs

Active issuance first:

- `authentik-stack` direct endpoint
- internal-only Traefik routes that deliberately choose `step-ca`

Active issuance later:

- Harbor direct registry/API endpoint
- Portainer direct API/UI and agent mTLS endpoints
- NetBox direct API/UI endpoint
- Grafana direct API/UI endpoint

## Standard Day-2 Workflow

After deploying a new dependent host:

1. Confirm `step-ca-stack` health and refresh status of `certs/homelab-root.crt`.
2. Run normal host reconcile (trust via `lxc_base`).
3. Verify host trust before any client URL migration.
4. Verify internal DNS from the consuming runtime:
   - host-level for systemd/non-container clients
   - in-container for Docker-backed clients
5. Apply stack-specific HTTPS/FQDN changes.

After CA-affecting change, run one retrofit trust fan-out action with
`trust-homelab-ca.yml` for already-deployed hosts.

## Deployment Order Implication

Current deploy order already supports internal DNS before TLS-consuming
platform stacks:

1. `apt-cacher-stack`
2. `ci-runner-01`
3. `dns-stack`
4. `step-ca-stack`
5. `proxy-stack`
6. `authentik-stack`
7. `activate-edge`
8. `harbor-stack`
9. `monitoring-stack`
10. `netbox-stack`
11. `portainer-stack`

That means later TLS consumers should not need a reorder. The remaining gap is
runtime DNS consistency, especially for Docker containers created while a host
has temporary public resolver fallback configured.

## Shortest Recommended Implementation Order

Completed:

1. Normalize shared trust distribution and verification workflow.
2. Normalize internal DNS readiness checks for Docker-backed consumers.
3. Implement Authentik direct certificate pattern.
4. Migrate Grafana and Portainer Authentik backchannels.
5. Migrate Traefik forward-auth to verified HTTPS.

Remaining:

6. Design and implement Harbor OIDC backchannel migration under discovery-derived endpoint behavior.
7. Add shared direct-cert renewal/expiry checks.
8. Plan Harbor registry TLS normalization.

## Smallest Useful First Slice

1. Keep `certs/homelab-root.crt` as the trust anchor source.
2. Ensure the first client can resolve the internal Authentik hostname from its
   actual runtime.
3. Make Authentik present one step-issued cert on internal service name.
4. Switch Grafana to verified HTTPS for Authentik backchannel.
5. Capture a repeatable operator runbook for issue, verify, renew, reload, and
   DNS validation.

Status: complete and extended by two immediate follow-on migrations (Portainer
OAuth/resource backchannel and Traefik forward-auth runtime path).

## Highest-Risk Or Least-Defined Areas

- Harbor registry TLS normalization (broad client impact).
- Direct-service naming beyond current `*-bg` path.
- Inconsistent Docker resolver upstreams across stacks after temporary host DNS fallback.
- CA compromise and root rotation rehearsal/automation maturity.
- Consistent trust lifecycle for non-managed endpoints.
