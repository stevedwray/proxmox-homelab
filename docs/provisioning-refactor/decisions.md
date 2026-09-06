# Provisioning Refactor Decisions

## Decision 0: Bootstrap-Aware Edge Reconciliation

Edge reconciliation is not part of Terraform apply.

Terraform provisions LXCs and runs each stack's normal Ansible playbook. The
stack-owned `edge.yaml` manifests are consumed by an explicit edge reconciler
after the edge foundation is healthy.

Terraform does not detect edge service readiness and must not run a hidden
second pass for edge state.

Fresh Mode 2 rebuilds use Stage 3a:

1. CoreDNS with a seed `lab.gibbsgreatly.xyz` zone.
2. Traefik runtime with static entrypoints, providers, certificate resolvers,
   default store, and shared middleware only.
3. step-ca.
4. Authentik via direct IP first boot, followed by API token bootstrap.
5. Edge reconciler dry-run and apply.

Direct-IP access is the bootstrap fallback for foundational services until the
edge reconciler is active.

The reconciler must fail closed in apply mode if CoreDNS, Traefik, or required
Authentik API access is unavailable. It must not silently skip work based on
health checks.

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

CoreDNS has two classes of records:

- Seed or non-browser records required before the edge reconciler is available.
- Generated browser edge records derived from stack-owned manifests.

Generated browser records must target the Traefik edge IP `192.168.30.10`. During
migration, any direct service record for the same browser hostname is replaced
one host at a time.

## Decision 3: Stack-Owned Manifest Path

Each stack that exposes browser routes owns an edge manifest at:

```text
terraform/lxc/stacks/<stack>/edge.yaml
```

`stack.yaml` remains the LXC platform metadata contract. It must not grow
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

One-host replacement is explicit: a migration task may allow exactly the host it
is replacing while it validates generated output, but live publish must remove
the central route and add the generated route as the same deployment unit.

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
2. Run edge reconciler dry-run with the migration host marked as the intended
   replacement.
3. Apply only the required generated state.
4. Remove that service's central legacy route in the same deployment unit.
5. Validate route, DNS, cert, and auth behavior.
6. Re-run the reconciler and confirm no-op.
7. Commit only after validation passes.

Do not migrate multiple services in one session unless explicitly requested.

## Decision 9: Apply Defaults

All edge tooling defaults to dry-run.

Apply mode requires:

- explicit `--apply` or equivalent
- pve-test targeting preflight
- healthy CoreDNS and Traefik checks
- Authentik API token only when selected manifests require Authentik objects
- no automatic Authentik deletes

## Decision 10: One-Host Route Cutover Rule

Generated routes must never accidentally duplicate live central routes.

During cutover, exactly one intended replacement host per service is allowed:

1. **Accidental duplicates fail**: The Traefik renderer checks generated routes
   against both generated manifests and legacy central routes. If a generated
   route has the same host as any legacy central route AND there is no explicit
   `intendedReplacement` flag, the renderer fails dry-run with a clear error.

2. **One explicit replacement allowed**: A migration task may pass exactly one
   hostname as `intendedReplacement` to validate generated output without
   blocking the dry-run. This hostname must match the generated route being
   tested.

3. **Same-unit atomic swap**: Live publish removes the central legacy route and
   adds the generated route as the same deployment unit. Both operations must
   succeed or both must fail.

4. **No accidental survivors**: After live publish, a second reconciler run must
   report no duplicate host and no pending generated changes, confirming the
   cutover is complete.
