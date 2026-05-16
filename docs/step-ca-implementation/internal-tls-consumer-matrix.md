# Internal TLS Consumer Matrix

## Scope

This matrix classifies internal consumers into:

- trust-only consumers
- active certificate issuance consumers
- weak flows to migrate first
- DNS-sensitive consumers that require in-container/internal-runtime resolution checks

Classification is based on current repo behavior, not a future redesign.

## 1. Stack Classification: Trust-Only Vs Active Issuance

| Stack / flow class | Trust-only first | Active issuance first | Active issuance later | Notes |
| --- | --- | --- | --- | --- |
| `dns-stack` | Yes | No | No | Primarily trust consumer |
| `ci-runner-01` | Yes | No | Maybe | Future API clients may need verified internal HTTPS |
| `apt-cacher-stack` | Yes | No | No | No immediate direct cert requirement |
| `authentik-stack` direct endpoint | No | Yes | No | First direct issuance target |
| `monitoring-stack` host OS | Yes | No | N/A | Host trust needed before Grafana verified HTTPS client migration |
| `monitoring-stack` Grafana container -> Authentik token/API | No | Yes | No | First proven backchannel; also first explicit DNS-sensitive container client |
| `monitoring-stack` direct Grafana endpoint | No | No | Yes | Lower priority than Grafana outbound Authentik migration |
| `harbor-stack` host OS | Yes | No | N/A | Host trust first |
| `harbor-stack` OIDC/web backchannel -> Authentik | No | No | Yes | Needs internal DNS verification from container runtime when migrated |
| `harbor-stack` direct registry/API endpoint | No | No | Yes | High-blast-radius later workstream |
| `netbox-stack` host OS | Yes | No | N/A | Trust first |
| `netbox-stack` direct API/UI endpoint | No | No | Yes | Later case-by-case |
| `portainer-stack` host OS | Yes | No | N/A | Trust first |
| `portainer-stack` OAuth/resource backchannel -> Authentik | No | No | Yes | DNS-sensitive container consumer when migrated |
| `portainer-stack` direct API/UI endpoint | No | No | Yes | Later case-by-case |
| Portainer agent mTLS endpoints | No | No | Yes | Later, security-driven issuance use case |
| Internal-only Traefik routes using `step-ca` resolver | No | Yes (selective) | Yes (broader) | Only where route is intentionally internal and clients trust homelab CA |

## 2. Existing step-ca Consumers Today

| Flow | Current state | Trust posture |
| --- | --- | --- |
| Traefik ACME client -> `step-ca` ACME directory | Active via `step-ca` resolver and `combined-ca.crt` | Strongest existing cross-service internal TLS consumer |
| `step-ca` local health checks | `step ca health` with local root | Strong but host-local only |
| Grafana -> Authentik token/API | Active on internal HTTPS with explicit Grafana DNS pin to `LAB_IP_DNS` | Strongest current proof that trust plus in-container DNS both matter |

## 3. Flows To Move First

Move these first to verified HTTPS on Authentik direct-access naming:

1. Grafana token/API backchannel -> Authentik
2. Harbor OIDC reconcile/health path -> Authentik
3. Portainer OAuth token/resource path -> Authentik
4. Traefik forward-auth backchannel -> Authentik

Migration rule for each of the above:

1. verify host trust
2. verify in-runtime DNS resolution for the internal Authentik FQDN
3. only then switch the client URL from HTTP/IP to HTTPS/FQDN

## 4. Weak/Internal Flows Still Present

| Flow | Current behavior | Why weak |
| --- | --- | --- |
| Traefik -> Authentik forward-auth | direct HTTP to Authentik service IP/port | cleartext cross-stack backchannel |
| Harbor/Portainer container DNS for future internal Authentik names | mostly inherited host/gateway resolver state | can fail as `NXDOMAIN` even when host DNS is correct |
| Harbor Authentik health/reconcile helpers | HTTP and no-verify style behavior | no verified server identity |
| Portainer -> Authentik OAuth URLs | HTTP/IP-based URLs | no verified TLS path |
| Authentik local bootstrap/admin API | local HTTP bootstrap path | acceptable initially, but not final direct-TLS posture |
| Harbor registry consumers | insecure-registry posture for broad clients | largest weak-trust exception |

## 5. DNS Readiness Matrix

| Consumer class | DNS check location | Why it matters |
| --- | --- | --- |
| systemd/host-native client | host OS | Host resolver is the real client runtime |
| Docker-backed app calling internal FQDN | inside the application container | Docker embedded DNS may use different upstreams than host |
| reverse proxy using internal HTTPS upstream | proxy container/runtime | Wrong resolver upstream can look like TLS or auth failure |

Current repo lesson:

- host trust and host DNS are necessary but not sufficient for Docker-backed
  internal TLS consumers
- Grafana succeeded only after its container DNS was explicitly pinned to the
  lab DNS server

## 6. Flows That Should Stay As-Is For Now

| Flow | Reason |
| --- | --- |
| Browser-facing Traefik routes on `letsencrypt` | Current architecture keeps browser clients on public certs |
| ACME HTTP challenge callback behavior | Protocol requirement, not a missed hardening step |

## 7. Naming Constraint For Direct TLS

Current CoreDNS behavior matters:

- direct-access records remain available (including `*-bg` naming)
- browser-route records can point same base names at Traefik

Near-term planning rule: first non-browser direct TLS work should use current
direct-access naming behavior, not assume browser names and direct names are
identical.
