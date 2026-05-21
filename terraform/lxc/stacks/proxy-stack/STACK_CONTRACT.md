# proxy-stack — Stack Contract

## Purpose

Edge ingress and TLS termination for the pve-test platform. Traefik v3 runs in
`edge_seg` and acts as the single ingress point for all platform services. It also
provides the Authentik forward-auth middleware integration that protects all
platform routes.

## Network

| Field | Value |
|---|---|
| Zone | `edge_seg` |
| IP | `${lab_ip_proxy}/24` |
| Gateway | `${lab_gw_edge}` |
| VMID | 30010 |

## Inputs

| Input | Source | Notes |
|---|---|---|
| `CF_DNS_API_TOKEN` | env var | **Mandatory.** Cloudflare API token for Let's Encrypt DNS-01 challenge |
| `TRAEFIK_DNS_RESOLVER_PRIMARY` | env var | **Mandatory.** Primary resolver passed to LEGO for DNS challenge |
| `TRAEFIK_DNS_RESOLVER_SECONDARY` | env var | **Mandatory.** Secondary resolver passed to LEGO for DNS challenge |
| `LAB_IP_AUTHENTIK` | env var | **Mandatory.** Authentik IP; written into the `authentik` forward-auth middleware config |
| `LAB_IP_STEP_CA` | env var | **Mandatory.** Step CA IP; used to derive the ACME `caServer` for the `step-ca` cert resolver |
| `LAB_IP_HARBOR` | env var | **Mandatory.** Harbor registry IP; used for Docker daemon insecure-registry config |
| `LAB_FQDN_TRAEFIK` | env var | Optional Traefik FQDN override; defaults to `traefik.<LAB_DOMAIN>` |
| `traefik_generated_source_dir` | extra var (provision.sh) | Path to per-stack dynamic config directory on the control node; defaults to `terraform/lxc/.generated/traefik`; published into `/opt/proxy-stack/dynamic/` at deploy time |
| `portainer_server_ip` | stack.yaml / env | Shared platform IP metadata |
| `registry_host` | stack.yaml / env | Harbor registry host passed through stack metadata |
| `apt_cacher_host` | stack.yaml / env | Apt cache host passed through stack metadata |

No secret values are committed here. `CF_DNS_API_TOKEN` and all sensitive values must come from the environment.

## Provides

| Service | Port | Protocol | Notes |
|---|---|---|---|
| HTTP ingress | 80 | TCP | Redirects all traffic to HTTPS |
| HTTPS ingress | 443 | TCP | TLS termination; routes to platform services via dynamic config |

`stack.yaml` service identifiers: `proxy-http`, `proxy-https`.

## Dependencies

- `harbor-stack` for Docker image pulls (Traefik image).
- `apt-cacher-stack` for package cache availability during host provisioning.
- Authentik is **not** a deployment-time dependency: the forward-auth middleware config is written with the Authentik IP at deploy time, but Traefik starts and serves traffic independently. Authentik must exist only at request time for forward-auth to work. This is by design — proxy-stack is part of the Stage 3a edge foundation that boots before Authentik's initial API token bootstrap.

## Persistent State

| Path | Storage | Contents |
|---|---|---|
| `/opt/proxy-stack` | LXC host filesystem / Docker compose project | Compose file, `.env`, `traefik.yml`, `dynamic/` config directory |
| `/opt/proxy-stack/dynamic` | LXC host filesystem | Traefik dynamic config files (Authentik middleware, per-stack router configs) |
| `/opt/proxy-stack/certs` | extra mount (5 GiB) | ACME storage (`letsencrypt/acme.json`, `step-ca/acme.json`) and `combined-ca.crt` |
| Docker volumes from compose | Docker storage (5 GiB) | Traefik runtime state |

## Generated Artifacts

- `dynamic/authentik.yml` — written at deploy time with the Authentik forward-auth middleware definition; the IP is rendered from `LAB_IP_AUTHENTIK`.
- `dynamic/<stack>.yml` files — per-stack router configs published from `terraform/lxc/.generated/traefik/` (the generated source). The source is regenerated from manifests before each provisioning or validation pass.
- `certs/combined-ca.crt` — built at deploy time by concatenating the system CA bundle with the homelab root CA (`/usr/local/share/ca-certificates/homelab-root.crt` if present). Required so the LEGO ACME client trusts both Let's Encrypt roots (system CAs) and the step-ca ACME endpoint (homelab CA) from a single bundle.

## What May Depend on This Stack

- Every service published to the platform edge requires this stack for HTTPS ingress.
- `authentik-stack` uses Traefik as the entry point for its UI and OIDC redirect flows.
- `monitoring-stack` Grafana requires this stack for published access.
- Any future service that registers a Traefik router in the dynamic directory.

## What Must Not Be Edited Casually

- `ACME_EMAIL` (`admin@gibbsgreatly.xyz`) is embedded in `traefik.yml`. Changing it after cert issuance requires clearing the ACME storage files.
- The Let's Encrypt resolver is currently configured to use the **staging** endpoint (`acme-staging-v02`). Switching to production requires a deliberate configuration update and cert flush.
- The `combined-ca.crt` rebuild task is marked `changed_when: true` — it always runs on reconcile. This is intentional; the cert is cheap to rebuild and must stay current.
- `portainer_agent: false` is intentional; proxy-stack is a platform-tier service and does not expose a Portainer agent.
- Do not add router definitions directly to `/opt/proxy-stack/dynamic/` by hand. Use the generated source in `terraform/lxc/.generated/traefik/` to keep routing config under version control.

## Playbook

`deploy-proxy-stack` (plays: Docker base (`lxc_base`, `docker_base`), then Traefik compose deploy via direct tasks — no `direct_stack` role)

## Notes

- This stack has two ACME cert resolvers: `letsencrypt` (Cloudflare DNS-01 challenge, staging endpoint) and `step-ca` (HTTP-01 challenge against the internal CA). Both resolvers use `combined-ca.crt` as the CA trust bundle via `LEGO_CA_CERTIFICATES`.
- The `dynamic/` directory is a live watched file provider; Traefik reloads dynamically when files in this directory change without a full service restart.
- The `certs/letsencrypt/acme.json` and `certs/step-ca/acme.json` files are created with `mode: 0600` at first deploy and are not overwritten on reruns (`force: false`).
