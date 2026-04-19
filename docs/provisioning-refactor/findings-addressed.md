# Findings Addressed

This document maps the review findings to concrete changes in the provisioning
refactor plan.

## Finding 1: DNS Ownership Was Split

Resolution: [decisions.md](decisions.md) makes CoreDNS the record authority for
`lab.gibbsgreatly.xyz` and keeps MikroTik as resolver/conditional forwarder.

Task impact:

- Task 04 renders CoreDNS records from manifests.
- Task 04 validates MikroTik delegation instead of managing MikroTik static
  records for lab browser hosts.

## Finding 2: Hostname Policy Was Inconsistent

Resolution: pve-test hostnames are standardized on
`*.lab.gibbsgreatly.xyz`.

Task impact:

- Task 01 documents the legacy Phase 04 conflict.
- Task 02 validator rejects pve-test manifests outside
  `.lab.gibbsgreatly.xyz`.
- Fixtures include all six pve-test browser services.

## Finding 3: Central Proxy Routes Would Collide With Generated Routes

Resolution: migration requires generated plus legacy duplicate-host detection.

Task impact:

- Task 03 renderer must fail if generated routes collide with central legacy
  routes.
- Task 08 removes one central route only after the generated route is validated.

## Finding 4: Contract Fixtures Were Too Narrow

Resolution: the contract task includes all six current browser services:

- Authentik
- Portainer
- Harbor
- NetBox
- Grafana
- Traefik dashboard

Task impact:

- Task 01 requires valid fixtures for all six.
- Task 01 requires special backend modeling for `api@internal`.

## Finding 5: Authentik Automation Was Too Broad

Resolution: Authentik work is split into discovery and apply tasks.

Task impact:

- Task 05 is read-only object discovery and drift reporting.
- Task 06 implements write-capable upserts only after discovery is documented.

## Finding 6: Renderer Validation Was Too Weak

Resolution: renderer validation must parse and semantically inspect generated
Traefik dynamic config.

Task impact:

- Task 03 requires YAML syntax validation plus semantic checks for routers,
  services, middleware references, duplicate names, duplicate hosts, and TLS
  resolver policy.

## Finding 7: Manifest Location Was Ambiguous

Resolution: [decisions.md](decisions.md) defines
`terraform/lxc/stacks/<stack>/edge.yaml` as the standard path.

Task impact:

- Task 01 documents the path.
- Task 02 implements discovery for that path only.
