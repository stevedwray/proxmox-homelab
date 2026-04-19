# Provisioning Refactor Task Sequence

Each task below is intended to be small enough for one AI-agent session. Tasks
are ordered to reduce ambiguity before implementation begins.

## Task 00: Normalize Planning Docs

Type: documentation

Objective: Make this directory the explicit source of truth and document that
older Phase 04 browser-ingress docs are legacy context for this refactor.

Prompt: [prompts/00-normalize-planning-docs.yaml](prompts/00-normalize-planning-docs.yaml)

Task doc: [tasks/00-normalize-planning-docs.md](tasks/00-normalize-planning-docs.md)

## Task 01: Define Edge Manifest Contract

Type: documentation/specification

Objective: Define the full v1alpha1 `EdgeManifest` contract, validation rules,
and fixtures for all six current browser services.

Prompt: [prompts/01-edge-manifest-contract.yaml](prompts/01-edge-manifest-contract.yaml)

Task doc: [tasks/01-edge-manifest-contract.md](tasks/01-edge-manifest-contract.md)

## Task 02: Implement Manifest Validator

Type: development

Objective: Implement a local validator for `edge.yaml` files with no deployment
side effects.

Prompt: [prompts/02-manifest-validator.yaml](prompts/02-manifest-validator.yaml)

Task doc: [tasks/02-manifest-validator.md](tasks/02-manifest-validator.md)

## Task 03: Implement Traefik Renderer

Type: development

Objective: Render deterministic per-stack Traefik dynamic config from valid
manifests and detect collisions with legacy central routes.

Prompt: [prompts/03-traefik-renderer.yaml](prompts/03-traefik-renderer.yaml)

Task doc: [tasks/03-traefik-renderer.md](tasks/03-traefik-renderer.md)

## Task 04: Implement DNS Zone Renderer

Type: development

Objective: Render CoreDNS lab-zone records from manifests and validate MikroTik
conditional forwarding.

Prompt: [prompts/04-dns-zone-renderer.yaml](prompts/04-dns-zone-renderer.yaml)

Task doc: [tasks/04-dns-zone-renderer.md](tasks/04-dns-zone-renderer.md)

## Task 05: Discover Authentik State

Type: development/read-only

Objective: Query Authentik and produce a drift report that maps manifest auth
intent to current providers, applications, and outposts.

Prompt: [prompts/05-authentik-discovery.yaml](prompts/05-authentik-discovery.yaml)

Task doc: [tasks/05-authentik-discovery.md](tasks/05-authentik-discovery.md)

## Task 06: Implement Authentik Reconciler

Type: development

Objective: Implement idempotent create/update behavior for Authentik objects
needed by stack-owned routes. Deletes remain out of scope.

Prompt: [prompts/06-authentik-reconciler.yaml](prompts/06-authentik-reconciler.yaml)

Task doc: [tasks/06-authentik-reconciler.md](tasks/06-authentik-reconciler.md)

## Task 07: Wire Proxy Deployment To Generated Files

Type: development

Objective: Update the proxy deployment workflow so generated per-stack files
are published to `/opt/proxy-stack/dynamic/stacks/` while central config remains
shared-only.

Prompt: [prompts/07-proxy-generated-file-wiring.yaml](prompts/07-proxy-generated-file-wiring.yaml)

Task doc: [tasks/07-proxy-generated-file-wiring.md](tasks/07-proxy-generated-file-wiring.md)

## Task 08: Migrate Portainer

Type: deployment

Objective: Move `portainer.lab.gibbsgreatly.xyz` to stack-owned provisioning.

Prompt: [prompts/08-migrate-portainer.yaml](prompts/08-migrate-portainer.yaml)

Task doc: [tasks/08-migrate-portainer.md](tasks/08-migrate-portainer.md)

## Task 09: Migrate NetBox

Type: deployment

Objective: Move `netbox.lab.gibbsgreatly.xyz` to stack-owned provisioning.

Prompt: [prompts/09-migrate-netbox.yaml](prompts/09-migrate-netbox.yaml)

Task doc: [tasks/09-migrate-netbox.md](tasks/09-migrate-netbox.md)

## Task 10: Migrate Harbor

Type: deployment

Objective: Move `harbor.lab.gibbsgreatly.xyz` to stack-owned provisioning while
preserving native Harbor auth and non-browser registry clients.

Prompt: [prompts/10-migrate-harbor.yaml](prompts/10-migrate-harbor.yaml)

Task doc: [tasks/10-migrate-harbor.md](tasks/10-migrate-harbor.md)

## Task 11: Migrate Authentik

Type: deployment

Objective: Move `authentik.lab.gibbsgreatly.xyz` to stack-owned provisioning
without introducing forward-auth recursion.

Prompt: [prompts/11-migrate-authentik.yaml](prompts/11-migrate-authentik.yaml)

Task doc: [tasks/11-migrate-authentik.md](tasks/11-migrate-authentik.md)

## Task 12: Migrate Grafana

Type: deployment

Objective: Move `grafana.lab.gibbsgreatly.xyz` to stack-owned provisioning
while preserving native Grafana OIDC.

Prompt: [prompts/12-migrate-grafana.yaml](prompts/12-migrate-grafana.yaml)

Task doc: [tasks/12-migrate-grafana.md](tasks/12-migrate-grafana.md)

## Task 13: Migrate Traefik Dashboard

Type: deployment

Objective: Move `traefik.lab.gibbsgreatly.xyz` to stack-owned provisioning
using the special `api@internal` backend target.

Prompt: [prompts/13-migrate-traefik-dashboard.yaml](prompts/13-migrate-traefik-dashboard.yaml)

Task doc: [tasks/13-migrate-traefik-dashboard.md](tasks/13-migrate-traefik-dashboard.md)

## Task 14: Final Cutover Cleanup

Type: deployment

Objective: Remove remaining central per-service route ownership and validate
the stack-owned model end to end.

Prompt: [prompts/14-final-cutover-cleanup.yaml](prompts/14-final-cutover-cleanup.yaml)

Task doc: [tasks/14-final-cutover-cleanup.md](tasks/14-final-cutover-cleanup.md)
