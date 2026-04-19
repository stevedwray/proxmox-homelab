# Provisioning Refactor Decisions

## Decision 1: pve-test Browser Domain

All pve-test browser-facing routes use:

```text
*.lab.gibbsgreatly.xyz
```

The apex-style `*.gibbsgreatly.xyz` hostnames found in older Phase 04 browser
ingress docs are legacy context. They must not be used for new pve-test
manifests.

## Decision 2: DNS Authority

CoreDNS is the code-managed authority for `lab.gibbsgreatly.xyz`.

MikroTik remains:

- the zone-local first-hop resolver for SDN clients
- the conditional forwarder for `lab.gibbsgreatly.xyz`
- the network enforcement point

MikroTik static DNS records should not be used as the long-term per-service
record store for browser routes under `lab.gibbsgreatly.xyz`.

The DNS reconciliation task is therefore a CoreDNS zone rendering/reload task
plus MikroTik delegation validation. It is not a MikroTik static-record
reconciliation task for lab browser hostnames.

## Decision 3: Stack-Owned Manifest Path

Each stack that exposes browser routes owns an edge manifest at:

```text
terraform/lxc/stacks/<stack>/edge.yaml
```

`stack.yaml` remains the LXC platform metadata contract. It should not grow
browser ingress, DNS, or Authentik provisioning fields as part of this refactor.

## Decision 4: Manifest API Version

The initial manifest API version is:

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
```

The contract task must document every field before renderer/reconciler
implementation begins.

## Decision 5: Traefik Runtime Split

Central Traefik ownership remains limited to shared runtime config:

- entrypoints
- certificate resolvers
- file/docker providers
- shared middleware definitions
- default certificate store

Per-service routers and services move to generated files under:

```text
/opt/proxy-stack/dynamic/stacks/<stack>.yml
```

During migration, generated routes must be checked against both generated
manifests and legacy central routes to prevent duplicate host rules.

## Decision 6: Auth Modes

The contract must support at least these modes:

| Mode | Meaning |
| --- | --- |
| `none` | No Traefik or Authentik auth. Used for Authentik itself. |
| `forwardAuth` | Traefik uses the shared Authentik forward-auth middleware. |
| `native` | Service handles auth natively; no Traefik middleware. |
| `oidc` | Service uses native OIDC against Authentik. No Traefik forward-auth. |

The contract must prevent auth modes that create recursion, double-auth loops,
or non-browser client breakage.

## Decision 7: Authentik Automation Sequencing

Authentik work is split:

1. Read-only discovery and object mapping.
2. Write-capable reconcile with explicit ownership labels/names.

No task may delete Authentik objects by default. Deletes require a later,
explicit cleanup task.

## Decision 8: Migration Unit

The migration unit is one browser service per branch/session.

For each service:

1. Add manifest.
2. Render Traefik/DNS/Auth state.
3. Deploy or apply only the required generated state.
4. Validate route, DNS, cert, and auth behavior.
5. Remove that service's central legacy route.
6. Commit only after validation passes.

Do not migrate multiple services in one session unless explicitly requested.
