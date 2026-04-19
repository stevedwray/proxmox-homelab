# 04-core-services-06 — Wire browser-facing service UIs through Traefik and Authentik

## GitHub Issue

[stevedwray/proxmox-homelab#144](https://github.com/stevedwray/proxmox-homelab/issues/144)

## Phase

Phase 04 — Core Shared Services

## Objective

All six browser-facing service UIs are reachable via HTTPS at their canonical hostnames,
routed through Traefik with Let's Encrypt staging certificates, and protected by Authentik
forward-auth where practicable.

| Service | Canonical URL | Auth policy |
|---|---|---|
| Traefik dashboard | `https://traefik.lab.gibbsgreatly.xyz` | Authentik forward-auth |
| Grafana | `https://grafana.gibbsgreatly.xyz` | Grafana OIDC (native, no Traefik middleware) |
| Authentik | `https://authentik.gibbsgreatly.xyz` | None — Authentik is the IdP |
| Portainer | `https://portainer.gibbsgreatly.xyz` | Authentik forward-auth |
| Harbor | `https://harbor.gibbsgreatly.xyz` | Harbor native auth — no Traefik middleware |
| NetBox | `https://netbox.gibbsgreatly.xyz` | Authentik forward-auth |

## Auth policy rationale

**Authentik forward-auth** (Traefik intercepts, checks session with Authentik before proxying):
applied to Traefik dashboard, Portainer, and NetBox. These services either have no meaningful
native auth (Traefik) or benefit from a single SSO session without requiring a separate
credential store. Users still hold Portainer/NetBox local accounts for API access; forward-auth
gates the browser UI only.

**Grafana OIDC**: Grafana authenticates via Authentik's OIDC provider directly. No Traefik
middleware is needed — Grafana handles the redirect and token exchange itself. Adding
forward-auth on top would cause a double-auth loop.

**No middleware — Authentik**: Authentik cannot use its own forward-auth (circular dependency).
The route proxies directly to `10.57.1.10:9000`.

**No middleware — Harbor**: Harbor's auth model is project-level RBAC with robot accounts used
by CI/CD and container runtimes for image pull/push. Fronting it with forward-auth would break
all non-browser clients. Harbor native auth remains authoritative.

## Authentik outpost: domain-level mode

The existing Proxy Provider (`traefik-forwardauth`) was created in
"Forward auth (single application)" mode, scoped to one redirect URI. To cover multiple
hostnames (Portainer, NetBox, Traefik dashboard), the provider must be reconfigured to
"Forward auth (domain level)" mode.

Domain-level mode:
- Sets a shared auth cookie for `.gibbsgreatly.xyz`
- No per-application redirect URI configuration required
- One outpost covers all protected subdomains
- The Traefik `forwardAuth` address (`http://10.57.1.10:9000/outpost.goauthentik.io/auth/traefik`) is unchanged

Reconfiguration is a manual step in the Authentik admin UI — not yet automatable without
`terraform-provider-authentik`. See dep-05 step 2 for the exact UI steps.

## Prerequisites

- dep-01-authentik complete — Authentik running at `10.57.1.10`, outpost exists
- dep-02-traefik complete — Traefik running at `10.57.2.10`, wildcard cert issued
- All six target services running and reachable on their backend IPs

## Scope

1. **Code change** (rem-05): Update `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
   to add Traefik routes for Authentik, Portainer, Harbor, and NetBox in the `authentik.yml`
   dynamic config template

2. **Manual Authentik step** (dep-05): Reconfigure Proxy Provider to domain-level mode

3. **Deployment** (dep-05): Run the updated Traefik playbook against VMID 153 to push the new
   routes

4. **DNS** (dep-05): Update MikroTik static records so all four new hostnames resolve to
   `10.57.2.10`:
   - Add `authentik.gibbsgreatly.xyz → 10.57.2.10`
   - Add `netbox.gibbsgreatly.xyz → 10.57.2.10`
   - Update `portainer.gibbsgreatly.xyz` from `192.168.1.4` → `10.57.2.10`
   - Update `harbor.gibbsgreatly.xyz` from `192.168.1.4` → `10.57.2.10`

## Out of scope

- `terraform-provider-authentik` automation for outpost management (future)
- Grafana OIDC reconfiguration (already complete in dep-01)
- NetBox native OIDC integration (distinct from Traefik forward-auth; future improvement)
- Portainer OIDC/LDAP integration (forward-auth is sufficient for browser access)

## Traefik route specification

Routes to add to `dynamic/authentik.yml` (in `deploy-proxy-stack.yml` template):

```yaml
routers:
  authentik:
    rule: "Host(`authentik.gibbsgreatly.xyz`)"
    entryPoints: [websecure]
    service: authentik-backend
    tls:
      certResolver: letsencrypt
      domains:
        - main: "gibbsgreatly.xyz"
          sans: ["*.gibbsgreatly.xyz"]

  portainer:
    rule: "Host(`portainer.gibbsgreatly.xyz`)"
    entryPoints: [websecure]
    service: portainer-backend
    middlewares: [authentik]
    tls:
      certResolver: letsencrypt
      domains:
        - main: "gibbsgreatly.xyz"
          sans: ["*.gibbsgreatly.xyz"]

  harbor:
    rule: "Host(`harbor.gibbsgreatly.xyz`)"
    entryPoints: [websecure]
    service: harbor-backend
    tls:
      certResolver: letsencrypt
      domains:
        - main: "gibbsgreatly.xyz"
          sans: ["*.gibbsgreatly.xyz"]

  netbox:
    rule: "Host(`netbox.gibbsgreatly.xyz`)"
    entryPoints: [websecure]
    service: netbox-backend
    middlewares: [authentik]
    tls:
      certResolver: letsencrypt
      domains:
        - main: "gibbsgreatly.xyz"
          sans: ["*.gibbsgreatly.xyz"]

services:
  authentik-backend:
    loadBalancer:
      servers:
        - url: "http://10.57.1.10:9000"
  portainer-backend:
    loadBalancer:
      servers:
        - url: "http://10.57.1.20:9000"
  harbor-backend:
    loadBalancer:
      servers:
        - url: "http://10.57.3.10"
  netbox-backend:
    loadBalancer:
      servers:
        - url: "http://10.57.3.12:8080"
```

## DNS record changes

All four new hostnames must resolve to Traefik at `10.57.2.10`. MikroTik RouterOS commands:

```
/ip dns static add name=authentik.gibbsgreatly.xyz address=10.57.2.10
/ip dns static add name=netbox.gibbsgreatly.xyz address=10.57.2.10
/ip dns static set [find name=portainer.gibbsgreatly.xyz] address=10.57.2.10
/ip dns static set [find name=harbor.gibbsgreatly.xyz] address=10.57.2.10
```

Verify after applying:
```bash
for h in authentik portainer harbor netbox; do
  echo -n "$h.gibbsgreatly.xyz → "
  dig +short @192.168.1.1 $h.gibbsgreatly.xyz
done
```

All four must return `10.57.2.10`.

## Known gaps

- Authentik outpost reconfiguration is manual (terraform-provider-authentik not yet built)
- Portainer and NetBox users still require local service credentials for API/programmatic access;
  forward-auth only gates the browser UI
- Harbor robot accounts and Docker daemon image pulls are unaffected (not browser traffic)

## Acceptance criteria

- [ ] `deploy-proxy-stack.yml` contains routers for all six services in the `authentik.yml` template
- [ ] Authentik Proxy Provider is in domain-level mode with cookie domain `.gibbsgreatly.xyz`
- [ ] All four DNS records resolve to `10.57.2.10`
- [ ] `curl -skI --resolve authentik.gibbsgreatly.xyz:443:10.57.2.10 https://authentik.gibbsgreatly.xyz` returns 200 or 302
- [ ] `curl -skI --resolve portainer.gibbsgreatly.xyz:443:10.57.2.10 https://portainer.gibbsgreatly.xyz` returns 302 redirect to Authentik
- [ ] `curl -skI --resolve harbor.gibbsgreatly.xyz:443:10.57.2.10 https://harbor.gibbsgreatly.xyz` returns 200 or 302
- [ ] `curl -skI --resolve netbox.gibbsgreatly.xyz:443:10.57.2.10 https://netbox.gibbsgreatly.xyz` returns 302 redirect to Authentik
- [ ] TLS cert for all routes shows `(STAGING) Let's Encrypt` on pve-test
- [ ] rem-05-browser-ingress code gate: playbook passes `docker compose config -q`
