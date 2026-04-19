# Stack-Owned Ingress/Auth/DNS Design

## Purpose

Move browser ingress ownership from a central Traefik routing file to each stack, while keeping a single Traefik runtime. Each stack becomes the source of truth for its own:
- Traefik router/service definitions
- Auth policy intent (none, forward-auth, native)
- DNS records needed for user-facing hostnames
- Authentik app/provider registration metadata (where applicable)

This design removes the current bottleneck where adding or changing one stack requires editing the central proxy playbook.

## Current state (problem)

Today, `deploy-proxy-stack.yml` writes a central dynamic config file with routes for multiple services. DNS and some Authentik operations are also performed outside stack ownership. This causes:
- Coupled change sets across unrelated services
- Higher blast radius for syntax or routing mistakes
- Manual drift between stack, DNS, and Authentik records
- Harder incremental rollout in separate sessions

## Target state

### Ownership model

Each stack must own a declarative edge manifest file, committed with the stack:
- `edge.hosts`: FQDNs served by the stack
- `edge.backends`: target URLs and health hints
- `edge.auth`: auth mode per route (`none`, `forward_auth`, `native_oidc`, `native_basic`)
- `edge.tls`: resolver policy (`letsencrypt-staging` on pve-test)
- `edge.dns`: desired records (`A`, optional `CNAME`)
- `edge.authentik`: optional app/provider metadata for automated registration

Traefik remains central runtime infra, but route definitions are generated from stack manifests.

### Central components kept (but narrowed)

Central Traefik stack should keep only:
- Static Traefik config (`entryPoints`, providers, cert resolvers)
- Shared middlewares that are platform-wide (for example `authentik-forward-auth`)
- Dynamic loader behavior

Central Traefik stack should no longer own per-service routers/services.

### Render pipeline

1. Each stack publishes `edge-manifest.yaml` under a standard path.
2. A render/reconcile step validates all manifests against a schema.
3. Renderer produces one dynamic config file per stack in `/opt/proxy-stack/dynamic/stacks/<stack>.yml`.
4. Traefik file provider hot-reloads.
5. DNS reconciler applies desired records to MikroTik using REST API.
6. Authentik reconciler ensures required provider/app/outpost mapping exists.

## Contracts

### Edge manifest (v1)

Required fields:
- `apiVersion: homelab.gibbsgreatly/v1alpha1`
- `kind: EdgeManifest`
- `metadata.stack`
- `spec.routes[]`

Each `route` requires:
- `name`
- `host`
- `backend.url`
- `auth.mode`
- `tls.resolver`
- `dns.enabled`

Optional:
- `auth.forwardAuthMiddleware`
- `authentik.applicationSlug`
- `authentik.groupPolicy`

### Validation rules

- Hostnames must end with `.lab.gibbsgreatly.xyz` for pve-test
- No duplicate hostnames across manifests
- No route can point to localhost backends
- `forward_auth` requires middleware name
- `dns.enabled=true` requires record target IP

## Migration strategy

1. Add schema + validator + renderer without removing current central routes.
2. Migrate one stack at a time behind feature flags.
3. Dual-publish window: central route + stack route cannot share same host simultaneously.
4. Cut stack host from central file after stack route validates.
5. Repeat until all browser stacks are stack-owned.
6. Remove legacy central route blocks.

## Service migration order

1. Portainer
2. NetBox
3. Harbor
4. Authentik
5. Grafana
6. Traefik dashboard

This order reduces auth coupling risk and preserves operator access.

## Testing strategy

### Unit tests

- Schema validation with valid/invalid fixtures
- Duplicate host detection
- Rendered Traefik snippets syntax checks

### Integration tests (pve-test)

- `ansible-playbook` render/deploy idempotence
- `docker compose config -q` for proxy stack
- Route checks with `curl --resolve`
- DNS checks with `dig @192.168.1.1`
- Auth flow checks for `forward_auth` routes

### Non-functional checks

- Rollback within 5 minutes by restoring prior dynamic files
- No central file edits required to onboard a new stack

## Rollback design

- Renderer keeps previous generated file snapshot per stack.
- Reconciler can disable a stack manifest and re-render.
- Emergency fallback: restore legacy central route template and redeploy proxy stack.

## Security constraints

- No hardcoded API credentials in manifests
- DNS and Authentik tokens read from environment-backed secrets only
- Route metadata must not include secrets
- Changes continue to target `pve-test` only during development

## Definition of done (program level)

- Central dynamic config no longer contains per-stack service routes
- At least 6 browser-facing services are stack-owned
- DNS and Authentik reconciliation are automated from stack metadata
- Runbooks and prompts exist for each migration task
- Rebuild from code produces same working ingress state on pve-test
