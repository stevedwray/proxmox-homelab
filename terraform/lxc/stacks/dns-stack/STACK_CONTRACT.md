# dns-stack — Stack Contract

## Purpose

Internal authoritative nameserver and recursive resolver for the pve-test lab environment.
CoreDNS serves as the authoritative authority for `lab.gibbsgreatly.xyz` (mgmt_seg zone)
and provides recursive resolution for external names. All platform and application stacks
resolve lab FQDNs through this service.

## Network

| Field | Value |
|---|---|
| Zone | `mgmt_seg` |
| IP | `${lab_ip_dns}/24` |
| Gateway | `${lab_gw_mgmt}` |
| VMID | 151 |

## Inputs

| Input | Source | Notes |
|---|---|---|
| `LAB_DOMAIN` | env var | Lab DNS domain; defaults to `lab.gibbsgreatly.xyz` |
| `LAB_FQDN_TRAEFIK` | env var | Optional Traefik FQDN override; defaults to `traefik.<LAB_DOMAIN>` |
| `LAB_IP_DNS` | env var | **Mandatory.** IP of this DNS container; used in zone rendering and loopback wait |
| `LAB_IP_PROXY` | env var | **Mandatory.** Traefik proxy IP; used in zone template and authority probe |
| `LAB_IP_AUTHENTIK` | env var | **Mandatory.** Authentik IP; used in zone template |
| `LAB_IP_STEP_CA` | env var | **Mandatory.** Step CA IP; used in zone template |
| `LAB_IP_MONITORING` | env var | **Mandatory.** Monitoring stack IP; used in zone template |
| `LAB_IP_PORTAINER` | env var | **Mandatory.** Portainer IP; used in zone template |
| `LAB_IP_HARBOR` | env var | **Mandatory.** Harbor registry IP; used in zone template |
| `LAB_IP_NETBOX` | env var | **Mandatory.** NetBox IP; used in zone template |
| `LAB_GW_MGMT` | env var | **Mandatory.** Management segment gateway; used in CoreDNS config rendering |
| `COREDNS_LOOPBACK_IP` | env var | **Mandatory.** Loopback IP for post-deploy readiness probe |
| `coredns_generated_zone_src` | extra var (provision.sh) | Path to a pre-generated zone file; if set, overrides the seed zone at deploy time |
| `portainer_server_ip` | stack.yaml / env | Shared platform IP metadata |
| `registry_host` | stack.yaml / env | Harbor registry host passed through stack metadata |
| `apt_cacher_host` | stack.yaml / env | Apt cache host passed through stack metadata |

No secret values are committed here. All sensitive values must come from the environment.

## Provides

| Service | Port | Protocol | Notes |
|---|---|---|---|
| DNS authority (lab zone) | 53 | UDP + TCP | Authoritative for `lab.gibbsgreatly.xyz` |
| DNS recursion | 53 | UDP + TCP | Recursive resolution for external names via upstream forwarder |

`stack.yaml` service identifiers: none defined (platform tier — consumed by all stacks via resolver config).

## Dependencies

- `apt-cacher-stack` for package cache availability during host provisioning.
- `step-ca-stack` for the trust and certificate path used by the broader platform.
- No Docker or Harbor dependency — CoreDNS is installed as a bare binary from a GitHub release tarball.

## Persistent State

| Path | Storage | Contents |
|---|---|---|
| `/usr/local/bin/coredns` | LXC host filesystem | CoreDNS binary (version-locked at deploy time) |
| `/etc/coredns/coredns.conf` | LXC host filesystem | Rendered CoreDNS configuration file |
| `/etc/coredns/lab.zone` | LXC host filesystem | Published authoritative zone file |
| `/etc/coredns/lab.zone.candidate` | LXC host filesystem | Staged zone candidate used during zone publish flow |
| `/etc/systemd/system/coredns.service` | LXC host filesystem | CoreDNS systemd unit |

## Generated Artifacts

- `lab.zone` is rendered at deploy time by substituting all `${LAB_IP_*}` placeholders in the seed zone template (`ansible/files/coredns-lab.zone`).
- When `coredns_generated_zone_src` is set (e.g. by a zone reconciler writing a fresh zone file), the generated zone is used instead of the seed template. Zone syntax is validated with `named-checkzone` before publishing.
- The staged candidate (`lab.zone.candidate`) is validated for required bootstrap authority records (SOA, NS, ns1 A record) before promotion when using the seed zone path.

## What May Depend on This Stack

- All stacks that resolve lab FQDNs (every stack on `mgmt_seg` and `infra_seg` that uses lab-internal hostnames).
- `proxy-stack` and `authentik-stack` require lab zone resolution to function correctly.
- Any stack health or smoke test that resolves an FQDN rather than a bare IP.

## What Must Not Be Edited Casually

- The `coredns_generated_zone_src` extra var is the only safe way to replace the live zone; do not edit `/etc/coredns/lab.zone` directly on the container.
- The zone publish flow (stage → validate → assert bootstrap records → promote) exists to prevent accidental removal of SOA/NS authority records; do not bypass the assert.
- `portainer_agent: false` in this stack is intentional; DNS is a platform-tier service and does not expose a Portainer agent.
- CoreDNS version is pinned at `1.10.1` in the playbook vars; bumping it requires a full redeploy cycle and version probe validation.

## Playbook

`deploy-coredns` (roles: `lxc_base`; remaining steps are direct tasks — no `direct_stack` or Docker)

## Notes

- This stack does not use Docker Compose. CoreDNS runs as a systemd service installed directly from the upstream release tarball.
- The playbook performs a post-deploy authority probe (`dig @loopback traefik.<lab_domain>`) and a recursive probe (`dig @loopback github.com`) before declaring success.
- A temporary public DNS fallback (`nameserver 1.1.1.1`) is written to `/etc/resolv.conf` during provisioning if the container cannot resolve external names at startup. This is intentional and idempotent.
- The seed zone template (`ansible/files/coredns-lab.zone`) is the source of truth for initial zone content; the reconciler-generated zone (if used) must contain all bootstrap authority records to pass the stage-assert gate.
