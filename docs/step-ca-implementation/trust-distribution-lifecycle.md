# Trust Distribution Lifecycle

## Goal

Define how trust distribution works today and the standard day-2 workflow that
operators should use after new host deployment or CA-affecting changes.

This lifecycle now explicitly includes internal DNS readiness for consumers that
will use `step-ca`-backed internal FQDNs.

## Current Mechanism (Repo-True)

### 1. Root trust anchor export

`deploy-step-ca.yml`:

- bootstraps `step-ca`
- exports `/etc/step-ca/certs/root_ca.crt`
- fetches it into the repo as `certs/homelab-root.crt`

### 2. New managed host trust installation

`lxc_base` role:

- checks local control-node presence of `certs/homelab-root.crt`
- installs cert to `/usr/local/share/ca-certificates/homelab-root.crt`
- runs `update-ca-certificates` when changed

### 3. Retrofit trust distribution

`trust-homelab-ca.yml` exists to fan out trust to already-deployed managed
hosts.

### 4. Traefik combined trust bundle

`deploy-proxy-stack.yml` builds `combined-ca.crt` from system roots plus optional
homelab root so Traefik can validate both public CAs and internal `step-ca`.

### 5. Internal DNS readiness

Current repo behavior already deploys `dns-stack` before `step-ca-stack`,
`proxy-stack`, `authentik-stack`, and later platform stacks. `activate-edge`
publishes generated CoreDNS state before `harbor-stack`, `monitoring-stack`,
`netbox-stack`, and `portainer-stack` are deployed.

That means internal DNS should exist in time for later consumers, but two
additional realities matter:

- host resolver correctness does not automatically prove container resolver correctness
- temporary public-DNS fallback during provisioning can leak into long-lived
  Docker containers if they start before resolver state is normalized

For internal TLS adoption, DNS readiness is therefore part of the same
lifecycle as trust distribution.

## Standard Day-2 Operator Workflow

### A. After deploying a new dependent host

1. Confirm `step-ca-stack` health.
2. Confirm `certs/homelab-root.crt` is present/current.
3. Run normal stack reconcile (trust installed via `lxc_base`).
4. Verify trust on host.
5. Verify internal DNS from the actual consumer runtime:
   - host-level for native/systemd clients
   - in-container for Docker-backed clients
6. Only then migrate that stack's clients from HTTP/IP to HTTPS/FQDN.

### B. After CA-affecting changes or for existing hosts

1. Refresh exported root certificate (`certs/homelab-root.crt`).
2. Run retrofit trust fan-out using `trust-homelab-ca.yml` over intended hosts.
3. Verify representative consumers now validate against current root.
4. Re-check internal DNS from representative consumer runtimes if any client
   uses internal FQDNs instead of IP-based access.

This is the canonical fleet trust action. Do not treat the extra `dns-stack`
play in `deploy-step-ca.yml` as general fleet trust rollout.

## Is `certs/homelab-root.crt` Acceptable Long Term?

Yes, with explicit ownership.

Why acceptable now:

- public trust anchor artifact (not secret)
- already consumed by current automation
- simple for managed-host bootstrap

What should evolve:

- explicit refresh ownership after CA changes
- fingerprint verification as part of runbook
- explicit retrofit fan-out as standard action

Recommended stance for future sessions:

- keep `certs/homelab-root.crt` as current source of trust distribution
- formalize lifecycle metadata/checks around it
- avoid replacing this mechanism before Authentik-first migrations are complete

## Shared Tooling Vs Stack-Specific Trust Logic

Shared tooling should own:

- root artifact refresh/fingerprint checks
- fleet trust fan-out command path
- trust verification checks
- DNS verification checks for managed hosts and containerized consumers
- guidance on when a Docker-backed stack should explicitly use `LAB_IP_DNS`

Stack-specific logic should own:

- when a stack starts requiring direct certificate issuance
- stack-local client URL changes after trust is in place
- stack-local container DNS overrides when internal name resolution is required

## Standard Verification Pattern For Internal TLS Consumers

Before flipping any internal client from HTTP/IP to HTTPS/FQDN:

1. verify the host trusts `certs/homelab-root.crt`
2. verify the server presents the expected internal certificate
3. verify the client runtime can resolve the internal FQDN
4. verify the client runtime can complete a TLS request to that FQDN

For Docker-backed clients, steps 3 and 4 must be executed from inside the
container, not only from the host.

## Remaining Gaps

- no single tracked metadata record for root fingerprint and last distribution intent
- no one-command fleet target abstraction for all trust consumers
- no normalized container DNS policy for Docker-backed stacks that need internal service discovery
- temporary public resolver fallback can still create inconsistent container DNS state
- non-managed endpoints (control node/Proxmox host) are outside this normalized path
