# Special Cases

This file tracks stacks whose lifecycle is more complex than a simple "configure host and run service" model.

## Current Special-Case Candidates

### `dns-stack`

- generated zone publication
- tighter coupling to network and DNS behavior

### `proxy-stack`

- generated ingress publication
- edge routing and cross-stack exposure concerns

### `step-ca-stack`

- trust distribution beyond the local container

### `authentik-stack`

- identity bootstrap and external integration side effects

### `monitoring-stack`

- external identity reconciliation
- richer bootstrap and integration behavior

### `netbox-stack`

- deeper app bootstrap and state management

### `ci-runner-01`

- external registration lifecycle

### `portainer-stack`

- central control-plane role for other stacks

## Working Guidance

- keep a common base contract for all stacks
- allow stack-specific extensions where needed
- avoid forcing false uniformity
- normalize only where doing so reduces brittleness

## Open Questions

- which special cases can be expressed as reusable capability flags
- which should remain explicit per-stack exceptions
- when a stack should be migrated into the new model vs deferred until later
