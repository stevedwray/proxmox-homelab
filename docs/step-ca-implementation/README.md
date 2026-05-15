# step-ca Implementation Planning Package

## Purpose

This directory is the implementation-grounded planning package for expanding
internal TLS with `step-ca`.

Scope is intentionally narrow:

- use what already exists in this repo
- document the shortest safe implementation path
- avoid redesigning PKI or edge architecture

## Current Repo-True Baseline

- `deploy-step-ca.yml` bootstraps `step-ca` and exports
  `certs/homelab-root.crt`.
- `lxc_base` distributes that root certificate to managed hosts when the local
  file exists.
- `trust-homelab-ca.yml` exists for retrofit trust fan-out to already-deployed
  managed hosts.
- Traefik already has a `step-ca` ACME resolver and combined CA bundle logic in
  `deploy-proxy-stack.yml`.
- Most non-browser backchannels still use HTTP, IP-based URLs, or insecure
  verification patterns.
- CoreDNS direct-access behavior matters: browser-facing names and direct
  service names are not always the same thing.

## Canonical Decisions For This Planning Set

### 1. Which internal flows move first?

Move Authentik non-browser backchannels first, in this order:

1. Grafana token/API backchannel -> Authentik
2. Harbor OIDC reconcile/health path -> Authentik
3. Portainer OAuth token/resource path -> Authentik
4. Traefik forward-auth backchannel -> Authentik

### 2. Which stacks are trust-only vs active issuance?

Trust-only first:

- `dns-stack`
- `ci-runner-01`
- `apt-cacher-stack`
- `monitoring-stack` host OS
- `netbox-stack` host OS
- `harbor-stack` host OS
- `portainer-stack` host OS

Active issuance first:

- `authentik-stack` direct endpoint
- internal-only Traefik routes that intentionally use `step-ca`

Active issuance later / case-by-case:

- `harbor-stack` direct registry/API endpoint
- `portainer-stack` direct API/UI endpoint
- `netbox-stack` direct API/UI endpoint
- `monitoring-stack` direct Grafana endpoint
- Portainer agent mTLS endpoints

### 3. Standard day-2 operator workflow after new dependent host deployment

1. Confirm `step-ca-stack` health and that `certs/homelab-root.crt` is current.
2. Run the host's normal reconcile so `lxc_base` installs trust.
3. Verify trust on that host before changing client URLs.
4. Apply stack-specific HTTPS/FQDN client changes only after trust is verified.

For already-deployed hosts, or after CA-affecting changes, run one explicit
retrofit trust rollout using `trust-homelab-ca.yml`.

### 4. Is `certs/homelab-root.crt` acceptable long term?

Yes, as the current trust anchor distribution artifact.

It should evolve from a convenient file into an explicitly owned lifecycle:

- refresh ownership
- fingerprint verification
- explicit retrofit fan-out

### 5. Shared tooling vs stack-specific logic

Shared tooling:

- root cert export/fingerprint tracking
- trust fan-out and trust verification workflow
- trust-only vs issuance classification
- expiry/trust validation checks

Stack-specific logic:

- local TLS termination ports and direct FQDN choice
- cert/key file paths and reload behavior
- client URL migrations from HTTP/IP to HTTPS/FQDN

### 6. Shortest recommended implementation order

1. Normalize one shared trust distribution workflow.
2. Prove Authentik direct certificate issuance and service presentation.
3. Migrate Grafana, Harbor, and Portainer Authentik backchannels to verified HTTPS.
4. Move Traefik forward-auth to verified HTTPS.
5. Add shared renewal/expiry checks and service reload validation.
6. Plan Harbor registry TLS normalization and CA compromise/rotation response.

### 7. Smallest useful first implementation slice

1. Keep `certs/homelab-root.crt` as trust anchor source.
2. Issue/present one direct Authentik certificate on the direct-access name.
3. Move one client (Grafana) to verified HTTPS on that name.
4. Document renewal owner, reload behavior, and verification steps.

### 8. Highest-risk or least-defined areas

- Harbor registry TLS normalization (largest blast radius).
- Direct service naming conventions beyond existing `*-bg` records.
- CA rotation and compromise response.
- Normalized trust handling for non-managed endpoints (control node, Proxmox).

## Document Map

- [workstreams-and-order.md](workstreams-and-order.md): implementation order and
  boundaries
- [internal-tls-consumer-matrix.md](internal-tls-consumer-matrix.md): consumer
  classification and migration targets
- [trust-distribution-lifecycle.md](trust-distribution-lifecycle.md): trust
  anchor fan-out and day-2 operations
- [certificate-lifecycle.md](certificate-lifecycle.md): issuance, renewal,
  rotation, and failure/compromise planning
