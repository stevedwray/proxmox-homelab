# Certificate Lifecycle

## Scope

This document defines the next certificate lifecycle planning steps for current
repo implementation:

- issuance
- renewal
- rotation
- failure recovery
- compromise response

It assumes existing `step-ca` bootstrap and trust distribution remain in place.

## Current Baseline

Strong today:

- `step-ca` bootstrap
- root export and host trust path
- Traefik `step-ca` ACME resolver integration

Still weak:

- direct service issuance pattern ownership
- renewal/reload ownership for direct cert consumers
- explicit response playbooks for CA rotation/compromise

## 1. Issuance

What exists:

- ACME-enabled `step-ca`
- Traefik internal resolver plumbing

What must be proven next:

- one direct service certificate pattern (`authentik-stack` first)
- one client verifying that direct certificate end-to-end
- direct-access naming usage consistent with current CoreDNS behavior

Planned first issuance path:

1. Issue/present direct Authentik certificate on direct-access name.
2. Switch Grafana Authentik backchannel to verified HTTPS.
3. Reuse same pattern for Harbor and Portainer Authentik backchannels.

## 2. Renewal

Current state:

- Traefik handles its ACME renewal state in `acme.json`.

Gap for direct cert consumers:

- no standard owner for renewal execution
- no standard service reload expectation after renewal
- no shared expiry checks for direct cert consumers

Planning rule:

- shared tooling should detect expiry risk
- each stack must own reload/health behavior after cert refresh

## 3. Rotation

Leaf/service cert rotation (near-term):

- define cert/key file paths
- define reload/restart command
- define post-rotation health check

CA/root rotation (later high-risk track):

- impacts all trust consumers and direct cert paths
- requires explicit staged runbook before broad adoption

## 4. Failure Recovery

Failure class: direct cert issuance fails

1. keep previous working cert if available
2. verify host trust and CA reachability
3. verify certificate identity naming and endpoint path
4. retry issuance only after prerequisites pass

Failure class: trust exists but validation still fails

- client still uses IP instead of cert DNS identity
- client uses browser-route name instead of direct-access endpoint
- stale root cert on consumer
- service not presenting/reloading intended cert

Failure class: CA host outage

- existing certs work until expiry
- new issuance/renewal stop
- internal Traefik `step-ca` issuance also stops

Required planning output: define restore path and outage survivability checks.

## 5. Compromise Response (Least Defined / Highest Risk)

This is least defined today and must be documented before broad direct issuance.

Minimum response sequence to define:

1. stop issuance from compromised authority
2. rebuild/restore authority on deliberate path
3. export new trust anchor
4. fan out trust to managed consumers
5. reissue direct service certificates in priority order
6. verify representative consumers stack-by-stack

## Shortest Session Order

1. Prove Authentik direct cert + one verified client (Grafana).
2. Define renewal owner and reload behavior for that pattern.
3. Apply same pattern to Harbor and Portainer Authentik backchannels.
4. Add shared expiry/trust verification checks.
5. Document CA rotation and compromise runbook.

## Smallest Useful First Slice

The smallest useful lifecycle slice is:

- one direct service cert (Authentik)
- one verified client migration (Grafana)
- one explicit renewal owner
- one explicit reload + health-check path

This is the minimum step from "CA exists" to "direct internal TLS is operated."
