# Trust Distribution Lifecycle

## Goal

Define how trust distribution works today and the standard day-2 workflow that
operators should use after new host deployment or CA-affecting changes.

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

## Standard Day-2 Operator Workflow

### A. After deploying a new dependent host

1. Confirm `step-ca-stack` health.
2. Confirm `certs/homelab-root.crt` is present/current.
3. Run normal stack reconcile (trust installed via `lxc_base`).
4. Verify trust on host.
5. Only then migrate that stack's clients from HTTP/IP to HTTPS/FQDN.

### B. After CA-affecting changes or for existing hosts

1. Refresh exported root certificate (`certs/homelab-root.crt`).
2. Run retrofit trust fan-out using `trust-homelab-ca.yml` over intended hosts.
3. Verify representative consumers now validate against current root.

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

Stack-specific logic should own:

- when a stack starts requiring direct certificate issuance
- stack-local client URL changes after trust is in place

## Remaining Gaps

- no single tracked metadata record for root fingerprint and last distribution intent
- no one-command fleet target abstraction for all trust consumers
- non-managed endpoints (control node/Proxmox host) are outside this normalized path
