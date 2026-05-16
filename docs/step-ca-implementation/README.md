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
- Grafana, Portainer, and Traefik forward-auth Authentik backchannels now use
  verified internal direct TLS.
- Harbor Authentik backchannel migration is intentionally deferred because
  Harbor derives token and userinfo endpoints from OIDC discovery and does not
  expose the same independent override fields used by Grafana and Portainer.
- CoreDNS direct-access behavior matters: browser-facing names and direct
  service names are not always the same thing.
- Docker-backed consumers do not automatically prove internal DNS correctness
  just because the host trusts the homelab CA. Container resolver state can
  diverge from host resolver state during provisioning and remain wrong even
  after host DNS is restored.

## Canonical Decisions For This Planning Set

### 1. Which internal flows moved first?

Completed Authentik non-browser backchannel migrations:

1. Grafana token/API backchannel -> Authentik direct TLS
2. Portainer OAuth token/resource path -> Authentik direct TLS
3. Traefik forward-auth backchannel -> Authentik direct TLS

Deferred from the first rollout tranche:

4. Harbor OIDC reconcile/health path -> deferred pending a Harbor-specific
  approach because discovery-derived endpoints cannot be independently
  overridden like Grafana/Portainer token and API URLs.

### 2. Which stacks are trust-only vs active issuance?

Trust-only first:

- `dns-stack`
- `ci-runner-01`
- `apt-cacher-stack`
- `monitoring-stack` host OS
- `monitoring-stack` container trust for non-Authentik services
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
3. Verify host trust on that host before changing client URLs.
4. Verify internal DNS from the actual consuming runtime, not just from the host.
5. Apply stack-specific HTTPS/FQDN client changes only after trust and DNS are verified.

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
- internal DNS verification workflow for managed hosts and containerized clients
- guidance for when Docker-backed stacks should pin `LAB_IP_DNS`
- trust-only vs issuance classification
- expiry/trust validation checks

Stack-specific logic:

- local TLS termination ports and direct FQDN choice
- cert/key file paths and reload behavior
- client URL migrations from HTTP/IP to HTTPS/FQDN
- stack-local container DNS overrides when internal service discovery is required

### 6. Shortest recommended implementation order

Completed:

1. Normalize one shared trust distribution workflow.
2. Normalize internal DNS readiness for Docker-backed consumers.
3. Prove Authentik direct certificate issuance and service presentation.
4. Migrate Grafana and Portainer Authentik backchannels to verified HTTPS.
5. Move Traefik forward-auth to verified HTTPS.

Remaining:

6. Define and implement Harbor OIDC backchannel migration approach.
7. Add shared renewal/expiry checks and service reload validation.
8. Plan Harbor registry TLS normalization and CA compromise/rotation response.

### 7. Smallest useful first implementation slice

1. Keep `certs/homelab-root.crt` as trust anchor source.
2. Ensure the consuming runtime can resolve the internal Authentik hostname through lab DNS.
3. Issue/present one direct Authentik certificate on the internal service name.
4. Move one client (Grafana) to verified HTTPS on that name.
5. Document renewal owner, reload behavior, and trust-plus-DNS verification steps.

### 8. Highest-risk or least-defined areas

- Harbor OIDC backchannel migration details under discovery-coupled endpoint
  behavior (deferred from first rollout tranche).
- Harbor registry TLS normalization (largest blast radius).
- Direct service naming conventions beyond existing `*-bg` records.
- Container DNS drift caused by temporary provisioning fallbacks or inherited host resolver state.
- CA rotation and compromise response.
- Normalized trust handling for non-managed endpoints (control node, Proxmox).

## DNS As Part Of Internal TLS

Internal TLS adoption depends on three independent prerequisites:

1. the consumer trusts the homelab CA
2. the server presents the expected internal certificate
3. the consuming runtime can resolve the internal FQDN to the right service IP

For Docker-backed stacks, item 3 must be verified from inside the container.
Host-level DNS success is not enough. A host can resolve lab-internal names
correctly while a container still uses Docker's embedded resolver with public
upstreams and returns `NXDOMAIN`.

Planning rule for future sessions:

- treat in-container DNS verification as part of the certificate migration gate
- do not classify an internal TLS migration as complete until the consumer can
  resolve and validate the target FQDN from its real runtime context
- where a stack's containers need reliable internal service discovery, prefer an
  explicit DNS policy instead of relying on temporary host resolver state during
  provisioning

## Document Map

- [workstreams-and-order.md](workstreams-and-order.md): implementation order and
  boundaries
- [internal-tls-consumer-matrix.md](internal-tls-consumer-matrix.md): consumer
  classification and migration targets
- [trust-distribution-lifecycle.md](trust-distribution-lifecycle.md): trust
  anchor fan-out and day-2 operations
- [certificate-lifecycle.md](certificate-lifecycle.md): issuance, renewal,
  rotation, and failure/compromise planning
