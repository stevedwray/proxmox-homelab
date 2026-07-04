# technitium-stack — Stack Contract

## Purpose

Parity-window / eventual replacement for `dns-stack` (CoreDNS) as the
internal authoritative nameserver and recursive resolver for the mgmt_seg
platform network. During the initial bring-up window, Technitium serves a
separate bootstrap/dev zone (`TECHNITIUM_BOOTSTRAP_ZONE`, default
`tech.${LAB_DOMAIN}`; for `pve-test-vm` that is
`tech.test.gibbsgreatly.xyz`) plus recursive resolution for external names.
The live `LAB_DOMAIN` zone stays on CoreDNS until later parity/cutover
phases.

**Status: production parallel live, not yet production-cut over.** This
stack runs alongside `dns-stack` during the migration. The Phase 3 MikroTik
delegate rehearsal has passed on `pve-test-vm`, and production `pve`
parallel bring-up is now complete, but the production MikroTik FWD rule
still points at CoreDNS. Do not treat this stack as the active production
client path for `LAB_DOMAIN` until that delegate change is executed and
validated. See `docs/dns-refactor/README.md` for the full migration
workspace.

## Network

| Field | Value |
|---|---|
| Zone | `mgmt_seg` |
| IP | `${lab_ip_technitium}/24` |
| Gateway | `${lab_gw_mgmt}` |
| VMID | 20015 |

## Resources

| Field | Value |
|---|---|
| CPU | 1 core |
| Memory | 2048 MB |
| Swap | 1024 MB |
| Rootfs | 12 GB |
| Docker storage | 6 GB |

## Inputs

| Input | Source | Notes |
|---|---|---|
| `LAB_DOMAIN` | env var | Lab DNS domain; defaults to `lab.gibbsgreatly.xyz` |
| `TECHNITIUM_BOOTSTRAP_ZONE` | env var | Optional short-lived Technitium-only authority zone; defaults to `tech.${LAB_DOMAIN}` |
| `LAB_IP_TECHNITIUM` | env var | **Mandatory.** IP of this DNS container; used in zone rendering and loopback wait |
| `LAB_IP_PROXY` | env var | **Mandatory.** Traefik proxy IP; used in zone bootstrap and authority probe |
| `LAB_IP_AUTHENTIK` | env var | **Mandatory.** Authentik IP; used in zone bootstrap |
| `LAB_IP_STEP_CA` | env var | **Mandatory.** Step CA IP; used in zone bootstrap |
| `LAB_IP_MONITORING` | env var | **Mandatory.** Monitoring stack IP; used in zone bootstrap |
| `LAB_IP_PORTAINER` | env var | **Mandatory.** Portainer IP; used in zone bootstrap |
| `LAB_IP_HARBOR` | env var | **Mandatory.** Harbor registry IP; used in zone bootstrap and image pulls |
| `LAB_IP_NETBOX` | env var | **Mandatory.** NetBox IP; used in zone bootstrap |
| `LAB_GW_MGMT` | env var | **Mandatory.** Management segment gateway |
| `TECHNITIUM_ADMIN_PASSWORD` | env var (secret) | **Mandatory.** Initial admin password set on first boot via `DNS_SERVER_ADMIN_PASSWORD` |
| `technitium_generated_zone_src` | extra var (provision.sh) | Path to a pre-generated zone-record JSON file; if set, overrides the seed record set at deploy time — the Technitium-equivalent hook for `coredns_generated_zone_src` (see current-state.md and `docs/provisioning-refactor/tasks/08-coredns-renderer.md`) |
| `portainer_server_ip` | stack.yaml / env | Shared platform IP metadata |
| `registry_host` | stack.yaml / env | Harbor registry host, used for Docker Hub proxy pulls |
| `apt_cacher_host` | stack.yaml / env | Apt cache host passed through stack metadata |

No secret values are committed here. All sensitive values must come from the environment.

## Provides

| Service | Port | Protocol | Notes |
|---|---|---|---|
| DNS authority (bootstrap zone) | 53 | UDP + TCP | Authoritative for `TECHNITIUM_BOOTSTRAP_ZONE` during early bring-up; the live `LAB_DOMAIN` zone remains on CoreDNS until cutover |
| DNS recursion | 53 | UDP + TCP | Recursive resolution for external names via upstream forwarder |
| Web console / REST API | 5380 | TCP | Zone/record management and native OIDC-authenticated admin UI; used by the deploy playbook's zone-bootstrap step and API-driven SSO configuration step. Also routed through Traefik at `technitium.${LAB_DOMAIN}` via `edge.yaml` (`step-ca` certResolver, `auth.mode: oidc` — Technitium's own OIDC login is the gate), internal-`${LAB_DOMAIN}`-only, never the public `gibbsgreatly.xyz` zone. Requires the `edge_seg → mgmt_seg tcp/5380` firewall policy (see `network/<env>.yaml`). |

`stack.yaml` service identifiers: `dns-authority` (tcp/53), `dns-authority-udp` (udp/53).

## Dependencies

- `apt-cacher-stack` for package cache availability during host provisioning.
- Harbor (`registry_host`) for the Docker Hub proxy pull of the Technitium image.
- No hard `depends_on` gate on `dns-stack` — the two run independently
  during the parity window; only the MikroTik FWD rule couples them, and
  that coupling is external to Terraform/Ansible (manual, TM-09).

## Persistent State

| Path | Storage | Contents |
|---|---|---|
| `/opt/technitium-stack/docker-compose.yml` | LXC host filesystem | Rendered Docker Compose definition |
| `/opt/technitium-stack/.env` | LXC host filesystem | Compose secrets (admin password, registry host) |
| Docker named volume `technitium-config` | Docker volume (`docker_storage_size`) | Technitium's embedded config/zone database (`/etc/dns` in-container) — **this is where zone data lives; it is not a flat file like CoreDNS's `lab.zone`** |

## Generated Artifacts

- Zone bootstrap for the short-lived Technitium-only authority zone is
  applied via Technitium's REST API (`/api/zones/create`,
  `/api/zones/records/add`) during the deploy playbook's bootstrap phase,
  not by copying a zone file into the container — Technitium owns zone
  state in its own database.
- When `technitium_generated_zone_src` is set, the playbook posts the
  generated record set from that file instead of the static seed record
  list — this is the integration point for the provisioning-refactor
  DNS-ownership reconciler (see current-state.md for the CoreDNS-side
  equivalent this must match).
- A pre-publish guard (equivalent to CoreDNS's stage → `named-checkzone` →
  assert bootstrap records → promote flow) must confirm SOA/NS/admin
  bootstrap records exist in the proposed record set before it is applied
  via the API. This guard has now been exercised against live Technitium
  instances in both `pve-test-vm` and `pve`; keep hardening idempotence and
  parity checks in the deploy playbook as the production cutover packet is
  prepared (see `docs/dns-refactor/plan.md`).

## What May Depend on This Stack

- Nothing production-facing yet — during the bootstrap-zone phase this stack
  is queried directly for validation only. Once cut over, the same
  dependents as `dns-stack` apply: all `mgmt_seg`/`infra_seg` stacks
  resolving lab FQDNs, especially `proxy-stack` and `authentik-stack`.

## What Must Not Be Edited Casually

- `technitium_generated_zone_src` is intended as the only safe way to
  replace the bootstrap record set programmatically; do not hand-edit
  zone records through the Technitium web console for anything that must
  survive a redeploy.
- `portainer_agent: false` is intentional — this is a platform-tier
  service (`deployment_tier: platform`), even though it uses Docker
  (see `docs/dns-refactor/decisions.md` Decision 2).
- Do not point the MikroTik FWD rule at this stack's IP until the Phase 3
  cutover rehearsal in `docs/dns-refactor/plan.md` has passed on
  `pve-test-vm`, and do not mutate the production delegate until the
  manually reviewed cutover packet is approved.

## Playbook

`deploy-technitium-stack` (roles: `lxc_base`, `docker_base`; Docker Compose
deploy + REST API zone bootstrap — no `direct_stack`)

## Notes

- This stack does not reuse `dns-stack`'s VMID or IP — see
  `docs/dns-refactor/decisions.md` Decision 3 for why (deploy/destroy
  ordering makes an in-place swap unsafe; a parity window with independent
  validation and cheap rollback is required).
- The original scaffold matched `dns-stack`'s smaller footprint, but live
  observation in `pve-test-vm` showed Technitium spending meaningful time in
  swap and consuming close to 1 GB of boot-disk space early in the run. The
  default stack sizing was therefore raised before `pve` bring-up so
  production does not inherit the tighter test baseline.
- The playbook performs a post-deploy authority probe
  (`dig @<technitium-ip> traefik.<technitium_bootstrap_zone>`) and a
  recursive probe (`dig @<technitium-ip> github.com`) directly against the
  container's own IP — independent of the MikroTik forward path, since that
  path is not repointed here.
- Image is pulled through Harbor's Docker Hub proxy
  (`${REGISTRY_HOST}/dockerhub/technitium/dns-server`), matching the
  `netbox-stack`/`harbor-stack` convention, per Decision 2.
- Image is pinned to `15.2.0` (not the `13.5.0` originally scaffolded) —
  v15.0+ is required for Technitium's native OIDC SSO support. See
  `docs/dns-refactor/decisions.md` Decision 4.
- Admin console auth is native Technitium OIDC against Authentik (per the
  [authentik integration guide](https://integrations.goauthentik.io/networking/technitium/)),
  is automated through the existing Authentik edge reconciler plus
  `deploy-technitium-stack.yml` calling Technitium's
  `api/admin/sso/get` / `api/admin/sso/set` endpoints. Technitium has no
  native LDAP client, so that automation pattern doesn't transfer here —
  if OIDC setup ever needs a fallback, it's Traefik `forwardAuth`
  (`auth.mode: forwardAuth` in `edge.yaml`), not LDAP.
