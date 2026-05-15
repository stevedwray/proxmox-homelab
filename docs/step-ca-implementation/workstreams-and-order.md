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

## Workstreams

| Workstream | Shared vs stack-specific | Current state | Gap to close next |
| --- | --- | --- | --- |
| Trust anchor ownership (`certs/homelab-root.crt`) | Shared | Export and host install path already exist | Make refresh/fingerprint/fan-out workflow explicit |
| Fleet trust rollout | Shared | New hosts inherit via `lxc_base`; retrofit playbook exists | One standard day-2 operator command sequence |
| Direct endpoint naming for non-browser clients | Shared policy + stack usage | `*-bg` names are current direct-access truth | Keep using current direct names first; postpone naming redesign |
| First direct certificate consumer | Stack-specific (`authentik-stack`) + shared pattern | Authentik is already central and exposes `9443` | Prove one cert presentation + one verified client |
| Authentik backchannel migration | Stack-specific per consumer | Grafana/Harbor/Portainer/Traefik flows still weak | Migrate to verified HTTPS one by one |
| Renewal/expiry/reload checks | Shared + stack hooks | Traefik ACME persistence exists | Define direct-cert renewal ownership + reload checks |
| Higher-blast-radius service TLS | Stack-specific (`harbor-stack`) | Registry trust posture still mixed/insecure | Keep as later track after Authentik pattern is stable |
| CA rotation/compromise procedures | Shared | Lightly defined today | Document minimum manual response path |

## Which Internal Flows Should Move First

Move Authentik consumers first in this order:

1. Grafana token/API backchannel
2. Harbor OIDC reconcile/health path
3. Portainer OAuth token/resource path
4. Traefik forward-auth backchannel

Rationale:

- same dependency target (`authentik-stack`)
- visible HTTP/insecure patterns today
- narrower blast radius than Harbor registry TLS rework

## Trust-Only Versus Active Issuance

Trust-only first:

- `dns-stack`
- `ci-runner-01`
- `apt-cacher-stack`
- `monitoring-stack`, `netbox-stack`, `harbor-stack`, `portainer-stack` host OS trust

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
4. Apply stack-specific HTTPS/FQDN changes.

After CA-affecting change, run one retrofit trust fan-out action with
`trust-homelab-ca.yml` for already-deployed hosts.

## Shortest Recommended Implementation Order

1. Normalize shared trust distribution and verification workflow.
2. Implement Authentik direct certificate pattern.
3. Migrate Grafana/Harbor/Portainer Authentik backchannels.
4. Migrate Traefik forward-auth to verified HTTPS.
5. Add shared direct-cert renewal/expiry checks.
6. Plan Harbor registry TLS normalization and CA compromise/rotation response.

## Smallest Useful First Slice

1. Keep `certs/homelab-root.crt` as the trust anchor source.
2. Make Authentik present one step-issued cert on direct-access name.
3. Switch Grafana to verified HTTPS for Authentik backchannel.
4. Capture a repeatable operator runbook for issue, verify, renew, and reload.

## Highest-Risk Or Least-Defined Areas

- Harbor registry TLS normalization (broad client impact).
- Direct-service naming beyond current `*-bg` path.
- CA compromise and root rotation procedures.
- Consistent trust lifecycle for non-managed endpoints.
