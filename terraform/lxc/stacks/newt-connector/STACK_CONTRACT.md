# newt-connector — Stack Contract

## Purpose

Minimal host for the Newt connector that tunnels `connector_seg` to the
OCI-hosted Pangolin edge (`/home/steve/git/oci`). No unrelated workloads —
this host runs exactly one thing: the `fosrl/newt` connector, using the
already-issued `lab` Pangolin site's credentials. Newt initiates an
*outbound* WireGuard tunnel to Pangolin/Gerbil on OCI; nothing inbound to
this host is expected or needed beyond the router-level DNS/ICMP rules
every zone gets.

This host's own Ansible playbook (`deploy-newt-connector`) provisions the
base OS/Docker only — `lxc_base`, `docker_base`. It deliberately does **not**
write Newt's own `docker-compose.yml`, `.env`, or credentials. That's an
operator action, same boundary as every other Newt/Pangolin credential in
this plan (control-plane/credential-creating, per
`/home/steve/git/oci/docs/repeatable-operations.md`'s own stated policy).
See "Newt deployment (operator action)" below for the exact config to use.

## Network

| Field | Value |
|---|---|
| Zone | `connector_seg` (VLAN 110) |
| IP | `192.168.110.10/24` |
| Gateway | `192.168.110.1` |
| VMID | 110010 |

`connector_seg`'s only permitted destinations (nextcloud-P3-01's firewall
policy, enforced on the MikroTik, verified live 2026-09-23): `pangolin-proxy`
(192.168.30.11:443, `edge_seg`) and general internet egress (any address
outside `192.168.0.0/16`, protocol-unrestricted — covers both Newt's control
connection and the Gerbil WireGuard tunnel). **No route to `infra_seg`
(Harbor, apt-cacher) or the main `proxy-stack` Traefik (192.168.30.10)** —
this is deliberate, not a gap. See "Inputs" below for what that means for
provisioning.

## Inputs

| Input | Source | Notes |
|---|---|---|
| `apt_cacher_host` | stack.yaml / env | Set for consistency with every other stack, but genuinely unreachable from this zone — `lxc_base`'s own reachability check (`roles/lxc_base/tasks/main.yml`) falls back to direct apt automatically when it times out. Not a bug. |

No `registry_host`/Harbor input: this host's own base provisioning doesn't
pull any Harbor-routed image, and Newt itself (once deployed by the
operator) pulls `fosrl/newt` directly from Docker Hub over the internet
egress rule, not through Harbor.

## Provides

None. This host initiates outbound connections only; it provides no service
other platform stacks depend on.

## Dependencies

Deliberately empty (`depends_on: []`), unlike almost every other stack in
this repo: `harbor-stack` and `apt-cacher-stack` are both unreachable from
`connector_seg` by firewall design, so declaring a dependency on either
would be misleading — this host's provisioning genuinely does not need
them up first.

- Depends on `connector_seg` (nextcloud-P3-01) existing — the zone this
  host lives in.

## Persistent State

None beyond the base LXC filesystem. Newt itself (once deployed by the
operator) is stateless per `artifacts/lab-test/docker-compose.yml` in the
`oci` repo — credentials are passed as container env/args on each start,
not persisted to a mounted volume.

## What May Depend on This Stack

- Any future service published via `pangolin-proxy` — the tunnel this host
  provides is the only path in from OCI to the home network at all.

**Not** a Wazuh agent-events route. That was investigated and retired
(operator decision, 2026-09-23) — the private-resource transport shape
this connector's tunnel provides turned out to be unreachable by a
process co-located with the Pangolin/Gerbil server itself, and OCI-side
monitoring now prioritizes OCI-native control-plane signals instead. The
`connector_seg -> wazuh-stack:1514` firewall rule (`nextcloud-P3-07b`)
has been removed from `pve.yaml`. Full account:
`/home/steve/git/oci/docs/hardening-and-wazuh-plan.md`.

## What Must Not Be Edited Casually

- Do not add a Harbor/apt-cacher firewall rule to `connector_seg` to "fix"
  provisioning — the lack of reach is deliberate (nextcloud-P3-01's whole
  design point is minimizing this zone's lateral reach). Pull images
  directly from the public internet instead, as this host already does.
- Do not write Newt's `docker-compose.yml`/`.env` into this repo's
  automation. Credentials stay operator-managed and out-of-band.

## Playbook

`deploy-newt-connector` (plays: `lxc_base`, `docker_base` only — no compose
deploy, no application-layer tasks).

## Newt deployment (operator action, not automated)

Once the host is provisioned, place a `docker-compose.yml` on
`192.168.110.10` modeled on `/home/steve/git/oci/artifacts/lab-test/docker-compose.yml`'s
`newt` service (drop the test `hello`/`whoami` service — this host runs
Newt only), **plus one addition confirmed necessary live, 2026-09-23**:
the `fosrl/newt` image (Alpine-based) ships with no CA bundle at all, so
TLS verification fails against even a genuinely valid public certificate
without mounting the host's CA store in:

```yaml
services:
  newt:
    image: fosrl/newt:latest
    container_name: newt-connector
    restart: unless-stopped
    environment:
      PANGOLIN_ENDPOINT: https://pangolin.gibbsgreatly.xyz
      NEWT_ID: ${NEWT_ID:?set NEWT_ID in .env}
      NEWT_SECRET: ${NEWT_SECRET:?set NEWT_SECRET in .env}
    volumes:
      - /etc/ssl/certs:/etc/ssl/certs:ro
    network_mode: host
```

`network_mode: host` is required (matches the proven test artifact) — Newt's
WireGuard tunnel needs to bind directly to this host's own interface, not a
Docker bridge network. `NEWT_ID`/`NEWT_SECRET` are the site's already-issued
credentials (`/home/steve/git/oci/docs/repeatable-operations.md`:
"intentionally not stored in this repository or printed in logs") — keep
them in a `.env` file on the host itself, mode `0600`, never in this repo.
Confirmed working live 2026-09-23: `Tunnel connection to server
established successfully!` — see
`/home/steve/git/oci/docs/hardening-and-wazuh-plan.md` Historical Step
3.5 for the full debugging trail (the CA mount above, plus the real
root cause: a stale Let's Encrypt staging cert on the OCI side, now
self-healing).
