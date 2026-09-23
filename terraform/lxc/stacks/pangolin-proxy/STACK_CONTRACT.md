# pangolin-proxy — Stack Contract

## Purpose

A second, dedicated Traefik instance for routes published to the internet
via the OCI-hosted Pangolin edge (see `/home/steve/git/oci`), physically
separate from the main `proxy-stack` Traefik. Option B, operator-confirmed
2026-09-23 (see `docs/nextcloud-stack/README.md`): isolation is structural
(a second process with its own, deliberately narrow dynamic config) rather
than policy-based (relying on a shared renderer always assigning the right
entrypoint). A compromised or misconfigured Newt connector gets no network
path to anything except this instance's own routes.

This stack is shared platform infrastructure — any future Pangolin-published
service (cse-panel, deep-research, others, not just nextcloud-stack) rides
this same instance, opting in via its own `edge.yaml` (see
`docs/nextcloud-stack/plan.md` nextcloud-P3-03c) rather than requiring a new
VLAN or firewall rule per service.

## Network

| Field | Value |
|---|---|
| Zone | `edge_seg` (shared with the main `proxy-stack`, VLAN 30) |
| IP | `192.168.30.11/24` |
| Gateway | `192.168.30.1` |
| VMID | 30011 |

`192.168.30.11:443` is reachable only from `connector_seg`
(`docs/nextcloud-stack/plan.md` nextcloud-P3-01's firewall rule) — never
from the internet or the LAN directly. Unlike the main `proxy-stack`, this
instance has no `web`/`:80` entrypoint: Pangolin already terminates the
public-facing TLS leg, so there is nothing for this instance to redirect.

## Inputs

| Input | Source | Notes |
|---|---|---|
| `CF_DNS_API_TOKEN` | env var | **Mandatory.** Same Cloudflare API token as `proxy-stack`, used for this instance's own Let's Encrypt DNS-01 challenge |
| `TRAEFIK_DNS_RESOLVER_PRIMARY` | env var | **Mandatory.** Primary resolver passed to LEGO for DNS challenge |
| `TRAEFIK_DNS_RESOLVER_SECONDARY` | env var | **Mandatory.** Secondary resolver passed to LEGO for DNS challenge |
| `LAB_FQDN_AUTHENTIK_INTERNAL` | env var | Optional; defaults to `authentik-int.<LAB_DOMAIN>`. Same internal-only hostname `proxy-stack` uses for its forwardAuth middleware — resolves directly to Authentik, not through either Traefik (see nextcloud-P3-03b) |
| `LAB_FQDN_HARBOR` | env var | **Mandatory.** Harbor registry FQDN (routed through Traefik) — deliberately not `LAB_IP_HARBOR`, which fails TLS (see `docs/harbor-stack/image-sourcing-enforcement.md`) |
| `apt_cacher_host` | stack.yaml / env | Apt cache host passed through stack metadata |

No secret values are committed here. `CF_DNS_API_TOKEN` and all sensitive
values must come from the environment.

## Provides

| Service | Port | Protocol | Notes |
|---|---|---|---|
| HTTPS ingress (Pangolin routes only) | 443 | TCP | TLS termination for routes opted into Pangolin publishing; reachable only from `connector_seg` |

`stack.yaml` service identifier: `pangolin-proxy-https`.

## Dependencies

- `harbor-stack` for Docker image pulls (Traefik image, same pinned
  version/digest as `proxy-stack`'s).
- `apt-cacher-stack` for package cache availability during host
  provisioning.
- Authentik is **not** a deployment-time dependency, same reasoning as
  `proxy-stack`: the forwardAuth middleware config is written with the
  internal Authentik hostname at deploy time, but Traefik starts and serves
  traffic independently.
- Depends on `connector_seg` (nextcloud-P3-01) existing for its one
  permitted inbound path to have anywhere to come from — this stack itself
  has no dependency on `nextcloud-stack` or any other app-tier service.

## Persistent State

| Path | Storage | Contents |
|---|---|---|
| `/opt/pangolin-proxy` | LXC host filesystem / Docker compose project | Compose file, `.env`, `traefik.yml`, `dynamic/` config directory |
| `/opt/pangolin-proxy/dynamic` | LXC host filesystem | Traefik dynamic config files: Authentik middleware and generated Pangolin route files |
| `/opt/pangolin-proxy/dynamic/routes` | LXC host filesystem | Replaced atomically on deployment from the control-node generated output; empty means no service is published |
| `/opt/pangolin-proxy/certs` | extra mount (2 GiB) | ACME storage (`letsencrypt/acme.json`) — separate from `proxy-stack`'s own, since this is a distinct Traefik process |
| Docker volumes from compose | Docker storage (4 GiB) | Traefik runtime state |

## Generated Artifacts

- `dynamic/authentik.yml` — an exact duplicate of `proxy-stack`'s shared
  Authentik forwardAuth middleware definition, not a shared reference (see
  nextcloud-P3-03b for why this needs its own copy and how it's
  live-verified).
- `dynamic/routes/<stack>.yml` files — generated only for EdgeManifest
  routes that explicitly set `pangolin.public_host`. `reconcile-edge.py`
  writes them to `.generated/pangolin-traefik`; `provision.sh` passes that
  source to this playbook. The main proxy renderer never writes these
  routes. With no opt-ins, the directory is deliberately empty and this
  instance publishes nothing.

## What May Depend on This Stack

- Any service opted into Pangolin publishing through `pangolin.public_host`
  in its own `edge.yaml`.
- `nextcloud-stack`, once deployed and opted in (nextcloud-P3-04).

## What Must Not Be Edited Casually

- Do not add a `web`/`:80` entrypoint. This instance is deliberately
  unreachable except from `connector_seg` on 443 — a public HTTP listener
  would need its own inbound firewall/NAT path that does not exist and
  should not be added casually.
- Do not add a `connector_seg -> apps_seg` (or any other app zone, or the
  main `proxy-stack`) firewall rule to make a route "simpler" — every
  published route goes through this instance's own dynamic config, never
  through a direct zone-to-zone rule. See nextcloud-P3-01's firewall policy
  for the enforced boundary.
- `portainer_agent: false` is intentional, same reasoning as `proxy-stack`.
- Do not add router definitions directly to `/opt/pangolin-proxy/dynamic/`
  by hand. Use the generated EdgeManifest source so routing remains under
  version control and reconciliation cannot silently remove a manual route.

## Playbook

`deploy-pangolin-proxy` (plays: Docker base (`lxc_base`, `docker_base`),
then Traefik compose deploy via direct tasks — no `direct_stack` role, same
shape as `deploy-proxy-stack`).

## Notes

- This stack has only one ACME cert resolver: `letsencrypt` (Cloudflare
  DNS-01 challenge). Unlike `proxy-stack`, there is no `step-ca` resolver —
  nothing behind this instance uses internal step-ca certs; everything
  routed through it is a public Pangolin-published route needing a real
  public LE cert, and the `step-ca` resolver's HTTP-01 challenge would need
  a `web`/`:80` entrypoint this instance deliberately doesn't have.
- The `dynamic/` directory is a live watched file provider; Traefik reloads
  dynamically when files in this directory change without a full service
  restart — same as `proxy-stack`.
- The `certs/letsencrypt/acme.json` file is created with `mode: 0600` at
  first deploy and is not overwritten on reruns (`force: false`).
