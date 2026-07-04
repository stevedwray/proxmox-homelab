# DNS Refactor — Decisions

Durable design decisions for the CoreDNS → Technitium migration, in the
format used by [docs/provisioning-refactor/decisions.md](../provisioning-refactor/decisions.md):
one `## Decision N: Title` per settled choice, with context and the actual
decision. Add entries here as Phase 0 (see [plan.md](./plan.md)) resolves
each open question — do not record something here until it's actually
decided.

## Decision 1: Why Technitium

Context: CoreDNS satisfies the current DNS-authority contract but has no
management UI (flat Corefile + zone files only), no built-in DoH/DoT/DNSSEC
(would require plugins), and — critically — no DHCP capability at all, which
is a dead end against the stated program end goal of eventually retiring
MikroTik as the `bridgeLocal` DHCP server (see "Future: DHCP takeover from
MikroTik" below and in plan.md).

Decision: Migrate from CoreDNS to Technitium DNS Server.

Rationale:
- **Unified DNS+DHCP path.** Technitium ships a DHCP server in the same
  binary/product, giving a credible eventual replacement for MikroTik's
  `lan`/`bridgeLocal` DHCP role via RouterOS DHCP-relay — a path CoreDNS
  simply doesn't have.
- **Web UI / manageability.** Zone and record management via a web console
  and REST API, rather than hand-edited flat zone files validated only by
  `named-checkzone` at deploy time.
- **DoH/DoT/DNSSEC built in.** No plugin chain required for encrypted
  transport or zone signing, unlike CoreDNS.

## Decision 2: Deployment shape — Docker

Context: `dns-stack` runs CoreDNS as a bare binary under systemd — no
Docker, no Harbor pull, no Portainer agent. Technitium's primary supported
distribution is a Docker image; a native Linux install path exists but is
less consistently documented upstream than the Docker image.

Decision: `technitium-stack` deploys Technitium via Docker Compose, using
the existing Harbor-proxied image pull pattern (`registry_host`,
`docker login`, `docker compose pull && up -d`) already used by
`netbox-stack`/`harbor-stack`/etc.

Rationale: matches Technitium's best-supported/most-current distribution
channel and the repo's existing Docker-stack pattern (`docker_base` role,
Harbor proxying), at the cost of adding `docker_storage_size`/`docker_mount`
fields and Docker-daemon config to `stack.yaml` that `dns-stack` never
needed. Per `deployment_tier: platform` convention (see
`PLATFORM_CONTRACT.md`), `portainer_agent` stays `false` even though Docker
is now in play — this is a platform-tier service, not an app-tier one.

## Decision 3: Stack identity — new VMID/IP, parity window

Context: current-state.md's deploy/destroy-order analysis shows nearly the
entire platform deploys after DNS and tears down before it — an in-place
VMID/IP swap would break every dependent stack's name resolution mid-cutover
with no rollback path.

Decision: `technitium-stack` stands up on a **new** VMID and a **new**
`mgmt_seg` IP, dual-running alongside `dns-stack` through Phases 1-3.
Cutover is a MikroTik FWD-rule repoint (see plan.md Phase 0 task 5), not a
stack replacement. `dns-stack` is only removed in Phase 6, after Technitium
is validated on `pve` and the operator confirms no rollback is needed.

Rationale: gives an independent validation window (`dig @<technitium-ip>`
against the real service before anything depends on it) and a cheap
rollback (repoint the FWD rule back to CoreDNS) if Technitium fails
post-cutover validation. Per the "Stated program goal" note below, this new
IP is also Technitium's **permanent** identity — not a throwaway address —
since a future DHCP-relay config will target it directly.

**Stack identity chosen:** `technitium-stack`, VMID `20015` (next free
`mgmt_seg` VMID — `20014` is already `graylog-stack`), IP allocated
per-environment following the existing `LAB_IP_DNS` pattern
(`LAB_IP_TECHNITIUM` env var → `${lab_ip_technitium}` in `stack.yaml`).
Concrete values, following the existing `LAB_IP_DNS` (pve) /
`+100` offset (pve-test-vm) convention: `192.168.20.15` (pve, base
`.env.template` default) / `192.168.20.115` (pve-test-vm,
`.env.pve-test-vm.template`); `.env.pve.template` uses the placeholder
`<operator-confirmed-mgmt-ip>` pending explicit production confirmation, per
that file's existing convention for every other `LAB_IP_*` value. **The
templates are updated; the real gitignored `.env` / `.env.pve-test-vm` files
still need the operator to copy the new line in.**

## Decision 4: Web console/API auth and exposure

Context: Technitium's admin console (port 5380, also serves the REST API)
needed a decision on whether/how it's reachable through Traefik and how
it authenticates, matching the pattern already used for other internal
admin UIs.

**Verified via web research (2026-07):**
- Technitium DNS Server **v15.0+ has native OIDC SSO support**
  (introduced in v15.0, refined through v15.2 — current latest release).
  authentik publishes an official integration guide
  ([integrations.goauthentik.io/networking/technitium](https://integrations.goauthentik.io/networking/technitium/)):
  a direct OIDC provider/application integration configured under
  Technitium's own Administration > Single Sign-On (SSO) page (Authority
  URL, Client ID/Secret, scopes), with authentik's `roles` claim mapped to
  Technitium's local groups. **No LDAP outpost required for this path.**
- Technitium has **no native LDAP authentication client** — unlike
  Graylog (which does support an LDAP backend, hence why the
  Authentik-LDAP-outpost pattern works for it). LDAP auth for Technitium
  is an open, unimplemented upstream feature request as of this check. The
  Graylog LDAP pattern is **not directly portable** to Technitium.

Decision:
- **Primary auth: native OIDC SSO against Authentik**, configured per the
  authentik integration guide above, with the Authentik
  provider/application created by `reconcile-authentik-edge.py` and the
  Technitium-side settings pushed by `deploy-technitium-stack.yml` through
  `api/admin/sso/get` / `api/admin/sso/set`.
- **Fallback (if OIDC setup fails or regresses): Traefik `forwardAuth`
  via the existing `authentik` middleware** (session-gate the browser
  route, Technitium's own local admin account stays behind it) — **not**
  LDAP, since Technitium can't consume it. This is a narrower fallback
  than originally suggested; noted here so a future session doesn't
  chase a Graylog-style LDAP integration that Technitium can't use.
- **Docker image tag must move off the `13.5.0` pin** used in the Phase 1
  scaffold — OIDC requires v15.0+. Retargeted to `15.2.0` (current
  latest).
- **Traefik exposure:** route both the web console and REST API (same
  host:port in Technitium — it doesn't separate them) through Traefik
  using the **`step-ca` certResolver** (already defined in
  `proxy-stack`'s `traefik.yml`, currently unused by any live route) —
  not `letsencrypt` — per operator preference for infra-internal
  certificates. Host stays under `${LAB_DOMAIN}` (`lab.gibbsgreatly.xyz` /
  `test.gibbsgreatly.xyz`, the internal-only zone CoreDNS/Technitium is
  authoritative for), never the public `gibbsgreatly.xyz` zone Cloudflare
  serves — this is what keeps it unreachable from a workstation's default
  resolver, matching every other internal admin route in this repo
  (`authentik.${LAB_DOMAIN}`, etc.).
- `auth.mode: none` in `edge.yaml` (no `forwardAuth` middleware on the
  primary route was the initial design intent, but after implementing the
  OIDC provider/application ownership in the edge reconciler the effective
  manifest now uses `auth.mode: oidc`, matching the same Authentik-owned
  OIDC route model used by other native-OIDC stacks. This remains the
  single auth gate; we still do **not** layer Traefik `forwardAuth` on top.
  If the fallback above is ever exercised, that's when `auth.mode` would
  flip to `forwardAuth`.
- **New firewall policy required:** `edge_seg → mgmt_seg tcp/5380`
  (Traefik → Technitium), mirroring the existing `edge_seg → mgmt_seg
  tcp/9000,9443` entry that exists for Authentik forward-auth callbacks.
  Added to `network/pve-test-vm.yaml` and `network/pve.yaml` `policies:`.
- **Authentik direct TLS also needs standard `443` on the internal
  `authentik-int.${LAB_DOMAIN}` host**, not just `:9443`. During live bring-up
  Technitium successfully fetched metadata from `:9443`, but the metadata
  itself advertised follow-up endpoints on `443`; exposing the direct TLS
  sidecar on `443` resolved that mismatch cleanly.

Rationale: native OIDC is a first-class, actively-maintained upstream
feature with a vendor-published Authentik guide — building custom
forward-auth-only gating when a real SSO integration exists would be
worse UX (double login) and worse audit posture (Technitium's own
group/role mapping goes unused). step-ca over Let's Encrypt matches the
operator's explicit preference for infra-internal certs and reuses an
already-provisioned-but-idle Traefik resolver rather than adding a new
one.

## Stated program goal (constrains Phase 0 decisions, not itself a Phase 0 task)

Operator has stated the end goal: eventually replace MikroTik as the DHCP
server with Technitium, in addition to the DNS role this workspace covers.
This is **not in scope for the current CoreDNS → Technitium migration** — see
[plan.md](./plan.md)'s "Future: DHCP takeover from MikroTik" section — but
every decision made below must not preclude it. Concretely: don't give
Technitium a throwaway identity/IP for the parity window, don't shrink its
resource sizing below `dns-stack`'s current allocation, and keep
`stack.yaml`/`STACK_CONTRACT.md` inputs extensible rather than hardcoding a
DNS-only shape.

## Format

```markdown
## Decision N: Title

Context: why this needed a decision, what constraint or trade-off forced it.

Decision: the actual choice, stated as a fact, not a discussion.

Rationale: why this option over the alternatives considered.
```

## Pending (tracked in plan.md's Open Questions)

- Whether Technitium's DHCP feature is in scope, or this migration is
  DNS-only — **decided: DNS-only for this workspace; DHCP takeover is a
  stated future goal, tracked separately (see plan.md's "Future: DHCP
  takeover" section), not a Phase 0-6 task here**
- The MikroTik FWD-rule cutover procedure (Phase 0 task 5) — see plan.md,
  designed but not yet rehearsed.
- Technitium's bootstrap REST API calls in `deploy-technitium-stack.yml`
  have now been exercised successfully against a live instance for login,
  zone creation, record publication, and SSO configuration. What remains
  unconfirmed is the fuller zone-import/parity workflow for replacing
  `coredns_generated_zone_src`.
