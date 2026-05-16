# Next Session Note

## Current Rollout Checkpoint

Branch focus: Authentik internal direct TLS rollout status tracking, not a new
implementation slice.

Completed in committed state:

- Grafana internal Authentik backchannel migrated to verified direct TLS
- Portainer internal Authentik backchannel migrated to verified direct TLS
- Traefik forward-auth runtime path migrated to verified direct TLS
- DNS/runtime groundwork and host resolver cleanup already completed earlier

Deferred by design:

- Harbor internal Authentik backchannel migration

## Harbor Defer Rationale

Harbor does not expose the same independent token/API endpoint override pattern
used by Grafana and Portainer.

Its OIDC behavior derives token and userinfo endpoints from discovery, so the
same direct swap pattern used in the completed migrations is not directly
reusable without a Harbor-specific approach.

## What This Session Should Do

Documentation-only closeout for the current checkpoint:

1. Update step-ca planning docs to reflect the completed migrations.
2. Remove stale sequencing that still implies Portainer or Traefik are pending.
3. Record Harbor as explicitly deferred with discovery-coupling rationale.
4. Keep branch reviewable and avoid new infra/code rollout changes.

## What Is No Longer The Next Step

- Basic trust fan-out groundwork
- Basic DNS/runtime resolver groundwork
- First Authentik direct-TLS proof-of-concept

Those prerequisites are already complete; remaining work is consumer-specific
follow-on planning, especially Harbor and later high-blast-radius TLS tracks.

## Next Open Planning Questions

1. What Harbor-compatible migration pattern should be used when discovery owns
   token and userinfo endpoint selection?
2. What validation gate should define Harbor migration readiness before changing
   runtime behavior?
3. Should Harbor backchannel migration and Harbor registry TLS normalization be
   planned in one workstream or intentionally kept separate?
