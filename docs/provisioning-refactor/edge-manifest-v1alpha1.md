# EdgeManifest v1alpha1

## Overview

`EdgeManifest` is the stack-owned contract for exposing browser-facing routes
through the edge ingress layer (Traefik + CoreDNS + Authentik).

**API Group:** `homelab.gibbsgreatly.xyz`
**Version:** `v1alpha1`
**Kind:** `EdgeManifest`

Each stack that exposes browser routes owns exactly one manifest at
`terraform/lxc/stacks/<stack>/edge.yaml`. The manifest declares all routes,
their backends, DNS records, TLS certificates, and authentication modes.

The edge reconciler consumes these manifests and generates:
- Traefik router/service definitions
- CoreDNS zone records
- Authentik provisioning objects (if required by auth mode)

---

## Manifest Structure

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: <identifier>
  stack: <stack-name>
spec:
  routes:
    - name: <route-name>
      host: <fqdn>
      backend:
        type: <backend-type>
        [url: <http-url>]          # if type: url
        [service: <service-ref>]   # if type: traefikService
      dns:
        enabled: <boolean>
        target: <ip-address>
        ttl: <duration>
      tls:
        resolver: <resolver-name>
      auth:
        mode: <auth-mode>
```

---

## Field Reference

### `metadata`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique identifier for this manifest. Example: `portainer-edge`, `grafana-edge`. Used in logs and for tracking manifest identity. |
| `stack` | string | yes | Stack identifier that owns this manifest. Must match the directory name in `terraform/lxc/stacks/<stack>/`. |

### `spec.routes[]`

Array of route definitions. Each route describes one browser-facing ingress path.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique name for this route within the manifest. Example: `grafana-ui`, `prometheus-api`. Used in generated Traefik router names and logs. |
| `host` | string | yes | FQDN for browser access. Must match pattern `*.lab.gibbsgreatly.xyz`. Example: `grafana.lab.gibbsgreatly.xyz`. All pve-test routes use the `lab.gibbsgreatly.xyz` subdomain (Decision 1). |
| `backend` | object | yes | Upstream service target. See [Backend Types](#backend-types). |
| `dns` | object | yes | DNS record configuration. See [DNS Policy](#dns-policy). |
| `tls` | object | yes | Certificate resolver configuration. See [TLS Policy](#tls-policy). |
| `auth` | object | yes | Authentication mode. See [Auth Modes](#auth-modes). |

### `backend`

Defines how to reach the upstream service.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | enum | yes | Either `url` or `traefikService`. See [Backend Types](#backend-types). |
| `url` | string | required if type=url | HTTP or HTTPS URL to the service. Must be accessible from Traefik. Example: `http://192.168.20.20:9000`. |
| `service` | string | required if type=traefikService | Traefik service reference in format `<service>@<provider>`. See [Backend Types](#backend-types). |

### `dns`

Configures CoreDNS record generation and browser client discovery.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | boolean | yes | Whether a DNS A record should be generated for this route. Typically `true` for all browser routes. If `false`, route is not discoverable via DNS (rarely used). |
| `target` | string | yes | IP address that the DNS A record should resolve to. **Must always be `192.168.30.10`** (the Traefik edge entrypoint IP). CoreDNS generates records under `lab.gibbsgreatly.xyz` zone; MikroTik forwards queries for this zone to CoreDNS. |
| `ttl` | string | yes | Time-to-live for the DNS record. Examples: `5m`, `1h`, `300s`. Recommend `5m` for frequently changing lab services. |

### `tls`

Configures certificate resolution and HTTPS.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `resolver` | string | yes | Name of the certificate resolver configured in Traefik. Example: `letsencrypt`. The resolver must be available in Traefik's static configuration before manifests are reconciled. |

### `auth`

Defines authentication and authorization mode for the route.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mode` | enum | yes | One of `none`, `forwardAuth`, `native`, or `oidc`. See [Auth Modes](#auth-modes) for semantics and usage rules. |

---

## Backend Types

### `type: url`

Route requests to an HTTP/HTTPS service by URL.

```yaml
backend:
  type: url
  url: http://192.168.20.20:9000
```

**Use cases:**
- Services running in LXC containers or external systems accessible by IP:port
- Services without a native Traefik provider

**Validation:**
- `url` field is required
- URL scheme must be `http` or `https`
- URL must be reachable from Traefik (network connectivity check deferred to reconciler)

### `type: traefikService`

Route requests to a Traefik-managed service via service reference.

```yaml
backend:
  type: traefikService
  service: api@internal
```

**Use cases:**
- Traefik's own dashboard and API (`api@internal`)
- Services already defined in Traefik's file or Docker provider (future expansion)

**Validation:**
- `service` field is required
- Format: `<service-name>@<provider>` where provider is typically `internal`
- Service reference must exist in Traefik configuration before rendering
- Renderers must emit the service reference directly on the router. They must
  not synthesize a `loadBalancer` service for `traefikService` backends such as
  `api@internal`.

---

## Auth Modes

### `mode: none`

No authentication or authorization by Traefik or Authentik middleware.

```yaml
auth:
  mode: none
```

**Use cases:**
- Authentik itself (cannot use forward-auth against itself; would create recursion)
- Public dashboards or read-only monitoring endpoints
- Services with no auth requirements

**Traefik behavior:** Route has no auth middleware applied.

**Constraint:** Cannot be combined with `native` or `oidc` (pick one semantic).

### `mode: forwardAuth`

Traefik forwards unauthenticated requests to Authentik's forward-auth endpoint.
Authentik determines if request is authorized; returns 200 (OK) or 401 (unauthorized).
Traefik enforces the decision and proxies to backend on 200.

```yaml
auth:
  mode: forwardAuth
```

**Use cases:**
- Most browser services (Grafana, Portainer, NetBox, Harbor, dashboards)
- Services that don't have their own auth but need user gating

**Traefik behavior:** Uses shared Authentik forward-auth middleware at `middlewares.auth.forwardAuth.*`.

**Constraints:**
- Cannot be used for Authentik itself (Decision 6; would create recursion loop)
- Harbor explicitly rejects `forwardAuth` (known incompatibility; Harbor handles its own auth)

### `mode: native`

Service handles all authentication and authorization internally. Traefik does not apply auth middleware.

```yaml
auth:
  mode: native
```

**Use cases:**
- Services with built-in auth that should not be bypassed (GitLab, Gitea, etc.)
- Services that implement their own session/SSO
- Legacy services with non-standard auth

**Traefik behavior:** Route has no auth middleware applied; backend is fully responsible.

**Constraint:** Cannot be combined with `none` (pick the semantic that fits).

### `mode: oidc`

Service handles native OIDC (OpenID Connect) flow against Authentik.
Traefik does not apply auth middleware; service directly contacts Authentik for tokens.

```yaml
auth:
  mode: oidc
```

**Use cases:**
- Services with built-in OIDC support (future expansion; not currently used in lab)
- Services that require token-based access control beyond simple forward-auth

**Traefik behavior:** Route has no auth middleware applied; backend is fully responsible for OIDC flow.

**Constraint:** Future use; documented for completeness and schema clarity.

---

## DNS Policy

**DNS Records are Generated by the Edge Reconciler**

CoreDNS is the code-managed authority for `lab.gibbsgreatly.xyz` (Decision 2).

For each route with `dns.enabled: true`:
1. The reconciler generates a CoreDNS zone record: `<host> A 192.168.30.10`
2. MikroTik forwards queries for `*.lab.gibbsgreatly.xyz` to CoreDNS
3. Browser clients resolve to `192.168.30.10` (Traefik's edge entrypoint)

**Target IP Must Always Be `192.168.30.10`**

The `dns.target` field is **always `192.168.30.10`** per Decision 2.
This value is explicit in the contract to prevent accidental misrouting.

**TTL Recommendation**

For lab services:
- Use `5m` (5 minutes) for frequently updated or test routes
- Use `1h` for stable services

Short TTLs allow faster convergence during testing; longer TTLs reduce DNS load.

---

## TLS Policy

Each route is assigned a TLS certificate via the resolver specified in `tls.resolver`.

**Resolver Configuration**

The resolver must be pre-configured in Traefik's static config (stage 3a bootstrap).
Example resolver: `letsencrypt` (Let's Encrypt ACME).

**Certificate Generation**

Traefik requests a certificate for the FQDN at first route reconciliation.
Subsequent reconciliations reuse cached certificates until expiration.

**SNI (Server Name Indication)**

Traefik uses the route's `host` FQDN as the certificate CN and SAN.

---

## Compatibility Rules

### Rule 1: Authentik Cannot Use `forwardAuth`

**Constraint:** If a manifest is owned by the `authentik-stack`, `auth.mode` must be `none`.

**Reason:** Forward-auth against Authentik itself creates unbounded recursion:
client → Traefik (auth check) → Authentik (forward-auth) → Traefik (redirect) → ...

**Validator check:**
```
if stack == "authentik-stack" and auth.mode == "forwardAuth":
  raise ValidationError("Authentik cannot use forwardAuth; use auth.mode: none")
```

### Rule 2: Harbor Cannot Use `forwardAuth`

**Constraint:** If a manifest is owned by the `harbor-stack`, `auth.mode` must not be `forwardAuth`.

**Reason:** Harbor has its own auth and OIDC integration. Forward-auth middleware conflicts with Harbor's internal auth logic.

**Validator check:**
```
if stack == "harbor-stack" and auth.mode == "forwardAuth":
  raise ValidationError("Harbor does not support forwardAuth; use auth.mode: native or oidc")
```

### Rule 3: Host Must Be Under `lab.gibbsgreatly.xyz`

**Constraint:** All routes must have `host` matching `*.lab.gibbsgreatly.xyz`.

**Reason:** Decision 1: pve-test routes are scoped to `lab.gibbsgreatly.xyz`.
Legacy apex-style `*.gibbsgreatly.xyz` hostnames are not used for new manifests.

**Validator check:**
```
if not host.endswith(".lab.gibbsgreatly.xyz"):
  raise ValidationError(f"host {host} must end with .lab.gibbsgreatly.xyz")
```

### Rule 4: DNS Target Must Be `192.168.30.10`

**Constraint:** `dns.target` must always equal `192.168.30.10`.

**Reason:** All browser clients must resolve to the Traefik edge entrypoint.
Any other value would route traffic away from the ingress layer.

**Validator check:**
```
if dns.target != "192.168.30.10":
  raise ValidationError(f"dns.target must be 192.168.30.10, not {dns.target}")
```

### Rule 5: Auth Mode Must Be Valid

**Constraint:** `auth.mode` must be one of: `none`, `forwardAuth`, `native`, `oidc`.

**Validator check:**
```
valid_modes = {"none", "forwardAuth", "native", "oidc"}
if auth.mode not in valid_modes:
  raise ValidationError(f"auth.mode {auth.mode} not recognized; must be one of {valid_modes}")
```

### Rule 6: Backend Must Have Correct Type-Specific Fields

**Constraint:**
- If `backend.type == url`, the `url` field must be present
- If `backend.type == traefikService`, the `service` field must be present

**Validator check:**
```
if backend.type == "url" and not backend.get("url"):
  raise ValidationError("backend.type url requires backend.url field")
if backend.type == "traefikService" and not backend.get("service"):
  raise ValidationError("backend.type traefikService requires backend.service field")
```

### Rule 7: DNS Config Must Be Valid

**Constraint:** If `dns.enabled == true`:
- `dns.target` must be `192.168.30.10`
- `dns.ttl` must be a valid duration string

**Validator check:**
```
if dns.enabled:
  if dns.target != "192.168.30.10":
    raise ValidationError(f"dns.target must be 192.168.30.10")
  if not is_valid_duration(dns.ttl):
    raise ValidationError(f"dns.ttl {dns.ttl} is not a valid duration (e.g., 5m, 1h)")
```

### Rule 8: Route Name Must Be Unique Within Manifest

**Constraint:** No two routes in the same manifest may have the same `name`.

**Validator check:**
```
names = [route.name for route in spec.routes]
if len(names) != len(set(names)):
  raise ValidationError("Duplicate route names found")
```

### Rule 9: Host Must Be Unique Across All Manifests

**Constraint:** During reconciliation, no two routes in different manifests may have the same `host`.
(This is checked globally by the reconciler, not per-manifest.)

**Reconciler check (cutover rule from Decision 10):**
```
Accidental duplicates fail with clear error message.
One explicit intendedReplacement allowed during migration dry-run.
```

---

## Fixtures and Error Catalog

See [fixtures/README.md](fixtures/README.md) for valid and invalid manifest examples.

**Valid fixtures** demonstrate correct usage for:
- Authentik (auth.mode: none)
- Harbor (auth.mode: native)
- Grafana (auth.mode: forwardAuth)
- Portainer (auth.mode: forwardAuth)
- NetBox (auth.mode: forwardAuth)
- Traefik dashboard (auth.mode: forwardAuth)

**Invalid fixtures** demonstrate validation failures:
- Duplicate host
- Bad domain (not under *.lab.gibbsgreatly.xyz)
- Missing backend
- Bad auth mode
- Authentik with forwardAuth (recursion)
- Harbor with forwardAuth (incompatibility)
- Bad URL scheme
- Invalid traefikService

See [fixtures/error-catalog.md](fixtures/error-catalog.md) for detailed error messages.
