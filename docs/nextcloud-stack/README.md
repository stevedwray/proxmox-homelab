# nextcloud-stack

Status (2026-09-25): **Live and working end-to-end, including real mobile
app access.** Nextcloud is published through Pangolin at
`https://nextcloud.pan.gibbsgreatly.xyz` (confirmed reachable from the
public internet, not just internally) and internally at
`https://nextcloud.lab.gibbsgreatly.xyz`. Auth is **local-account only**
(`steve`) — no Authentik, no Pangolin SSO/MFA gate on this resource
either. See the two retirement sections directly below before anything
else in this file; both describe real, working designs that were tried
and then deliberately reversed, for two different reasons.

**1. Authentik-via-Pangolin is retired (operator decision, 2026-09-25).**
**Authentik must never gain any externally reachable path, direct or via
Pangolin, public or client-only** — the blast radius of exposing the
lab's single IdP in any form was judged too large relative to the
benefit. **New standing policy, applying to every future
Pangolin-published service, not just Nextcloud: no service published
through Pangolin may use Authentik as its login mechanism**, full stop.

**2. Pangolin's own SSO/MFA gate is also dropped for Nextcloud specifically
(operator decision, 2026-09-25)** — not a blast-radius call this time, a
hard compatibility wall: Pangolin's resource-level SSO is a
browser-session model, and it gated `status.php`, the OCS capabilities
endpoint, and even `/index.php/login/v2` (the endpoint the Nextcloud app
uses to *start* its own login) uniformly, with a flat `401` before
Nextcloud ever saw the request. The Nextcloud mobile app's sync/API
traffic has no way to present a browser session cookie, so every
official Nextcloud client failed outright with "malformed server
configuration." This is not fixable by configuration on our side: it's a
[known, currently-open Pangolin bug](https://github.com/fosrl/pangolin/issues/2551)
— path-based "Bypass Auth" rules don't work once a resource is set to
"Protected." Pangolin's supported alternative for headless/API clients
(`P-Access-Token-Id`/`P-Access-Token` headers) requires client-side
support the stock Nextcloud app doesn't have. **Revised standing
policy**: Pangolin's own SSO/MFA is only viable for services accessed
purely through a browser — verify this live for any future service with
a native app/sync/API client before assuming it as an option; don't
repeat this on the next one. Nextcloud's own login (`steve` +
`twofactor_totp`, already installed and enabled) is the sole auth layer
for this resource instead — see "Pangolin SSO dropped for Nextcloud"
below for the full finding.

The historical sections further down (`P3-03b` through `P3-05`, "OIDC
was verified live", the original "Require Pangolin SSO/MFA by default"
decision) are kept as a record of what was built and verified at each
stage, not as current state.

Goal: a self-hosted Nextcloud instance as a durable local storage point,
initially for documentation/reports produced by other lab projects (the
`deep-research` agent, CyberSecEval), later opened to the internet via
Pangolin with monitoring and a deliberately narrow blast radius — see
Phase 3 in [plan.md](plan.md).

## Authentik-via-Pangolin retired (2026-09-25)

**What was built and actually worked, live:** Nextcloud published through
Pangolin (`nextcloud.pan.gibbsgreatly.xyz`), `user_oidc` installed and
enabled, Authentik's OAuth2 provider reconciled with both the LAN and
Pangolin callback URLs, and Authentik itself given a `pangolin.private_host`
route so an authenticated Pangolin client tunnel could reach it for the
OIDC redirect without a public listener. All of it was verified end-to-end
— see the "P3-03b"/"P3-04"/"OIDC was verified live" sections below, kept
as historical record.

**Why it was rolled back anyway:** getting this right required real,
ongoing security discipline that never goes away once built — Authentik's
own hardening guide identifies specific RCE-capable config endpoints
(`/api/v3/policies/expression*`, `/api/v3/propertymappings*`,
`/api/v3/managed/blueprints*`, `/api/v3/stages/{prompt/prompts,captcha}*`)
that must stay blocked at the proxy indefinitely; the browser-facing path
allowlist for the flow executor/static assets could only be established by
live testing, not read from docs; `AUTHENTIK_LISTEN__TRUSTED_PROXY_CIDRS`
had to be kept exactly scoped to the real proxy path forever, since a
mistake there lets any client spoof its IP for every login on the
platform; and split-DNS/issuer-identity questions added further ambiguity.
None of that risk is proportional to "let Nextcloud's login also be SSO"
for one internal file-storage app. Operator call: Authentik's blast radius
if any of that discipline slips is too large — full stop, no exceptions,
no partial/client-only exposure either.

**What changed, concretely:**
- `terraform/lxc/stacks/nextcloud-stack/edge.yaml`: `auth.mode` back to
  `none`; `NEXTCLOUD_OIDC_CLIENT_ID`/`SECRET` annotations removed. The
  `pangolin.public_host`/`private_host` routing (i.e. Nextcloud remaining
  reachable through Pangolin at all) is unaffected — only its auth
  mechanism changed.
- `terraform/lxc/stacks/authentik-stack/edge.yaml`: the `pangolin.private_host`
  block removed entirely. Authentik has no Pangolin route of any kind now.
- `terraform/lxc/discover-authentik-edge.py`: the `nextcloud-stack`/`nextcloud`
  entries removed from `OIDC_ROUTE_CLIENT_IDS`/`SECRETS`, its
  `_oidc_redirect_uris`/`_oidc_grant_types` special cases, and the
  now-unused dual-hostname (`pangolin_public_host`) redirect_uris logic
  that existed only to serve it.
- `terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml`: the
  `user_oidc` install/enable/register-provider tasks and the
  `allow_local_remote_servers` SSRF-trust task removed; replaced with a
  single `occ user:add ... --group=admin steve` task.
- `terraform/lxc/stacks/nextcloud-stack/docker-compose.yml`:
  `NEXTCLOUD_ADMIN_USER` changed from `admin` to `steve`
  (`NEXTCLOUD_ADMIN_PASSWORD` renamed `NEXTCLOUD_STEVE_PASSWORD` to match
  — new SOPS key, see "Still genuinely open" below).
- On the Authentik dashboard itself (manual, not automatable per this
  repo's credential-creation policy): delete the `nextcloud` OAuth2
  Provider/Application object.
- On the running host (mutating, needs the production approval flow):
  `occ app:disable user_oidc` + `occ app:remove user_oidc`; since it's not
  yet holding real user data, a clean `docker compose down -v` + wipe of
  `/var/lib/nextcloud-persistent/{data,postgres}` + redeploy is the
  simpler path rather than patching the live instance's account list
  (`admin`, `nxc`, and an OIDC-provisioned `Steve` account all currently
  exist — a fresh install collapses that to just `steve`).

**Standing policy, permanent, applies beyond Nextcloud:** no service
published through Pangolin may use Authentik as its login mechanism, in
any form — full public exposure, path-scoped exposure, or
Pangolin-client-only exposure are all out. Each Pangolin-published service
gets its own local/native login, or relies solely on Pangolin's own
SSO/MFA (which is already architecturally separate from Authentik — see
"Pangolin's own dashboard login is NOT Authentik-backed" below) —
**but confirm the latter actually works for the service's real clients
first; see "Pangolin SSO dropped for Nextcloud" immediately below for why
this isn't a safe default for anything with a native app/sync/API
client.**

## Pangolin SSO dropped for Nextcloud (2026-09-25)

**Symptom:** the Nextcloud mobile app, pointed at
`nextcloud.pan.gibbsgreatly.xyz`, failed immediately with "malformed
server configuration" — not a login failure, a connection-setup failure.

**Root cause, confirmed live by curling every endpoint the app calls on
first connect**, all three came back an identical flat `401` with a
13-byte plain-text body (`Unauthorized`), from Pangolin's own edge, before
Nextcloud was ever reached:
- `status.php` (server discovery — app expects JSON like
  `{"installed":true,...}`)
- `/ocs/v2.php/cloud/capabilities` (feature discovery)
- `/index.php/login/v2` (the endpoint the app itself POSTs to in order to
  *start* its own login flow)

Getting a bare 401 text response where strict JSON is expected is exactly
what produces "malformed server configuration" — the app can't parse it
at all. Critically, the third one means the app can't even begin
authenticating: Pangolin's resource-level SSO/MFA (`nextcloud-users` role)
was applied uniformly across the entire hostname, gating the login
handshake's own entry point.

**Why this can't be fixed with Pangolin configuration alone:** Pangolin's
SSO gate is a browser-session-cookie model. It works correctly for a
person opening a web browser (confirmed earlier: hitting the same
hostname from a plain browser-equivalent `curl` from an external network
correctly returned `401` — the gate itself works as designed). It does
not extend to a mobile/desktop app's background sync/WebDAV/OCS traffic,
which has no way to carry a Pangolin browser session. Checked what
Pangolin itself offers for this:
- Path-based "Bypass Auth" rules exist for exactly this class of problem,
  but there's an [open, currently-unfixed Pangolin bug (#2551)](https://github.com/fosrl/pangolin/issues/2551):
  bypass-auth rules don't work once a resource is set to "Protected" —
  unauthenticated requests are redirected to the auth wall regardless of
  matching rules.
- Pangolin's supported headless-client mechanism is Access Token auth
  (`P-Access-Token-Id`/`P-Access-Token` request headers) — but this
  requires the *client app* to know to send those headers. Some apps
  (Immich is documented as one) have been specifically adapted for it;
  the stock Nextcloud app has no such support and can't be made to add
  it from our side.

**Fix:** the Pangolin resource for `nextcloud-public` no longer requires
SSO/MFA — the auth layer for this resource is Nextcloud's own local login
only. Confirmed working end-to-end afterward: all three endpoints above
return correctly, and the actual Nextcloud mobile app connects normally.

**Compensating control, since Pangolin's outer MFA is gone for this
resource:** Nextcloud ships `twofactor_totp` (authenticator-app codes)
and `twofactor_backupcodes` (recovery codes) already installed and
enabled — confirmed live via `occ app:list`. Enable TOTP for the `steve`
account (Settings → Security → Enable TOTP, scan the QR code, save the
backup codes) so there's still a real second factor. This works cleanly
with the app because the TOTP challenge renders inside Nextcloud's own
login page during the same Login Flow v2 browser handshake the app
already opens — a genuine interactive browser session, not a background
API call, so none of the session-cookie mismatch above applies to it.
**Not yet done as of this writing — TOTP is available but not yet
enabled for `steve`.**

**Revised standing policy (supersedes the paragraph above it):**
Pangolin's own SSO/MFA is a safe default only for services accessed
purely through a browser (a dashboard, an admin UI with no native
client). For anything with a mobile app, desktop sync client, or its own
API consumers, verify live — with the actual client, not just `curl` —
before assuming Pangolin's SSO is viable, and prefer the service's own
native MFA (if it has one) instead. This generalizes: `nextcloud-P3-05`'s
original "Require Pangolin SSO/MFA by default" decision is retired for
this reason, and any future Pangolin-published service should treat this
as a real design question up front, not a default to fall back on.

## Current execution state (2026-09-24) — historical, describes the retired design above

**`connector_seg` is now live on `pve`** — `nextcloud-P3-01` executed:
zone/vnet/subnet applied via `pvesh` under the production approval flow
(VLAN 110, `192.168.110.0/24`, `tvnewt`), verified with `pvesh get` and
`ip link show vmbr0.110`. Two real VLAN collisions were caught and
fixed along the way (both from checking the actual physical switch
config against what the plan assumed was free): `connector_seg` moved
off VLAN 100 (already `cse_seg` on `pve-tiny`) to 110, and `apps_seg`
(nextcloud's own zone, not yet built) moved off VLAN 90 (already
`test_dhcp_seg` on `pve-test-vm`, nested inside `pve`) to 120 — see
Decisions below for both.

**MikroTik enforcement is also live (2026-09-23).** Applied by the
operator directly on the router, verified read-only afterward via
`terraform/lxc/stacks/netbox-stack/integrations/mikrotik_client.py`:
VLAN 110 interface + bridge-vlan tagging (`ether1`,`ether5`, matching
every other zone), gateway `192.168.110.1`, 3 input rules (ping/DNS to
the router, placed before the input catch-all — the exact ordering bug
hit live in `media-stack-lab`'s Stage B), and forward rules scoped to
`192.168.110.0/24`: accept to `pangolin-proxy` (192.168.30.11:443),
the shared Graylog TCP syslog ingress (192.168.20.14:514), accept general
internet egress (covers both the Newt control connection and the Gerbil
WireGuard tunnel — protocol-unrestricted, modeled on `cse_seg`'s egress
rule), then default-deny. `connector_seg`
is now enforced end-to-end (Proxmox SDN + MikroTik), not just declared
in `pve.yaml`.

**`newt-connector` is also live (2026-09-23)** — `nextcloud-P3-02`
executed: base LXC (192.168.110.10, Docker only, no Newt credentials in
this repo's automation) deployed via `provision.sh`, smoke test stable
after fixing two real bugs (256MB OOM-killed `apt install`; bare `ssh`
in `smoke-test.sh` worked standalone but failed silently under
`provision.sh`'s subprocess environment — fixed with explicit
`-F`/`-i`/`-n`). **Newt itself is now connected
to the OCI Pangolin edge** — `lab` site recreated (original credentials
unrecoverable, Community Edition gates regeneration behind Enterprise),
tunnel confirmed up. Two more real bugs found and fixed on the OCI side
getting there — see `/home/steve/git/oci/docs/hardening-and-wazuh-plan.md`
Historical Step 3.5 for the full account (a missing CA bundle in the `fosrl/newt`
image, and the real blocker: a stale Let's Encrypt *staging* cert that
`roles/pangolin/tasks/main.yml`'s ACME storage policy was silently
protecting from ever being corrected — now self-healing, not a one-off
manual fix).

**Newt maintenance and Wazuh coverage are live (2026-09-24).** Its local
Wazuh agent is enrolled and connected to the manager through the narrowly
scoped `connector_seg -> 192.168.40.15:1514,1515` policy and matching
MikroTik rule. FIM watches only `/opt/newt-connector/docker-compose.yml`,
not its credential-bearing `.env`; Docker monitoring is enabled for this
single-workload host. Security-only unattended updates are enabled (without
automatic reboots), and a weekly image-refresh timer runs the existing
`newt` Compose service on Sundays at 03:15 host-local time with up to
30 minutes of jitter. It does not run during provisioning or prune old
images.

**Wazuh is retired for the OCI edge (decision 2026-09-23).** The failed
path added a privileged endpoint agent, private resource, firewall
exception, and a relay sharing Gerbil's namespace, but could not provide
tamper-resistant evidence and briefly affected public-edge availability
during recovery. The `connector_seg -> wazuh-stack:1514` desired-state
rule has been removed. The OCI agent, relay, manager registration,
Pangolin resource/client, and MikroTik rule `*A3` are gone; the router
was re-queried read-only and has no matching TCP/1514 rule. The `lab`
Newt site and its credentials remain for future published services. OCI
monitoring
now prioritizes control-plane logs/alarms, public-port scans, external
HTTPS/TLS probes, and tested off-host recovery. The investigation is
retained as historical context in
`/home/steve/git/oci/docs/hardening-and-wazuh-plan.md`.

**`apps_seg` and `nextcloud-stack` are live on `pve` (2026-09-24):** VLAN 120,
`192.168.120.0/24`, gateway `192.168.120.1`, and `tvapps` are applied on
Proxmox and the MikroTik. Its policy permits only the planned application
dependencies, shared TCP syslog, internet package/image egress, the Wazuh
agent manager ports, and an explicit deny for everything else.

`nextcloud-stack` is LXC `120010` at `192.168.120.10`: a 16G rootfs and 30G
Docker mount on `apps-containers`, with a 200G durable mount on
`storage-containers` at `/var/lib/nextcloud-persistent`. It runs Nextcloud
35.0.0, PostgreSQL 16 Alpine, Redis, and cAdvisor. `status.php` is healthy;
the Wazuh agent is enrolled; Docker uses the local rsyslog/syslog relay for
Graylog forwarding. The main Traefik and Technitium authority publish
`nextcloud.lab.gibbsgreatly.xyz` to `192.168.30.10` and proxy it to the LXC.
`pangolin-proxy` is live on `pve` as LXC `30011` at `192.168.30.11` in
`edge_seg`; its Traefik metrics smoke test passed on 2026-09-24. It has no
generated application routes and therefore publishes no service. Its tracked
production Terragrunt entrypoint is
`terraform/lxc/environments/pve/pangolin-proxy/`. The active production
convention uses both that per-environment directory and the named `pve`
Terraform workspace: `.env.pve` exports `TF_WORKSPACE=pve`, and the live
state for existing environment-scoped stacks is stored under each stack's
`terraform.tfstate.d/pve/`. Pangolin-proxy has no such state yet, so the
first production initialization must create its `pve` workspace from
`default`; it must not be initialized against an assumed default-workspace
state. The 2026-09-24 plan attempts stopped before calculating or changing
infrastructure.

**P3-03b is verified.** From both `pangolin-proxy` and the established main
proxy, `authentik-int.lab.gibbsgreatly.xyz` resolves directly to Authentik
(`192.168.20.10`) and the forward-auth endpoint returns the same
Authentik/Nginx response. This rules out a route through either Traefik and
therefore the potential proxy loop. The unauthenticated endpoint response is
an identical `404` on both hosts; no route currently invokes the middleware.

**P3-04 internal route readiness is verified.** The generated root-level
`route-nextcloud-stack.yml` router on `pangolin-proxy` serves
`nextcloud.pan.gibbsgreatly.xyz/status.php` with HTTP 200 when resolved
internally to `192.168.30.11`. Nextcloud persistently trusts that hostname
and the dedicated proxy IP, while Authentik's reconciled provider contains
both LAN and Pangolin `user_oidc` callbacks. This is not public exposure:
this internal-route result is merely its prerequisite. Public publication was then
completed through Pangolin at `https://nextcloud.pan.gibbsgreatly.xyz` (see
`nextcloud-P3-05` below for the verified policy and remaining rollback test).

**OIDC was verified live.** The `user_oidc` app is installed and enabled;
Authentik manages the strict callback
`https://nextcloud.lab.gibbsgreatly.xyz/apps/user_oidc/code` and the required
authorization-code grant. Nextcloud has `allow_local_remote_servers=true` so
its server-side OIDC client can resolve the internal Authentik endpoint. This
is a deliberate SSRF-hardening trade-off: restrict and review features that
can make arbitrary outbound requests, and rely on the apps-segment firewall
for network containment.

**But the OCI side of Phase 3 has real, live progress**, tracked in its
own repo's plan, `/home/steve/git/oci/docs/hardening-and-wazuh-plan.md`
(that repo has no `.git` — not a commit history, just a live file):

- **OCI instance hardened**: NSG confirmed clean (80/443/UDP tunnel
  ports only); subnet security list stripped of 8 leftover rules from
  the box's prior life as a Minecraft server (Minecraft ports, an
  `"obsidian"` sync rule, a `"crawl4ai"` rule); SSH restricted to the
  operator's egress IP at both the OCI security-list layer and a new
  host-level `ufw` layer (`roles/os_hardening/` in the `oci` repo).
  Bastion was considered and explicitly rejected — IP restriction was
  judged sufficient, updated by hand if the operator's IP changes.
- **OCI Wazuh path retired:** a uniquely pre-registered `oci-pangolin`
  credential was safer than fleet-wide enrollment, but the resulting
  private route, agent, and Gerbil-netns relay had more security and
  availability cost than value for this one-purpose edge host. The
  agent, relay, manager registration, private resource/client, and
  router rule have been removed. The `lab` Newt site remains intact for
  future Pangolin-published services.
- **OCI monitoring priority:** OCI Audit, public-port scanning, and external
  HTTPS/TLS checks—not a home-lab Wazuh connection. VCN Flow Logs are
  deliberately skipped to protect the free tenancy's shared Logging allowance;
  Cloud Guard is unavailable. External checks and off-host backup remain
  recommended but are deliberately deferred for this rollout.

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Intended to be executed with
`.github/prompts/implement-step.prompt.md`.

See [plan.md](plan.md) for the full step-by-step plan.

## Decisions (resolved 2026-09-22, operator-confirmed)

- **App:** Nextcloud over ownCloud — richer WebDAV/OCS API and CLI (`occ`)
  for programmatic writes from other stacks, larger app ecosystem;
  ownCloud has been shedding features into its paid Infinite Scale
  rewrite.
- **Zone:** `apps_seg` SDN zone (VLAN 120, `192.168.120.0/24`), not
  reusing `infra_seg` or `media_seg` — keeps a future
  internet-exposed-via-Pangolin app isolated from core infra and media
  traffic, matching the existing per-purpose zone pattern
  (`media_seg`, `game_seg`, `pentest_seg`, `ai_seg`). Originally scoped
  for VLAN 90; changed 2026-09-23 after confirming on the physical
  switches that VLAN 90 is already live as `test_dhcp_seg`
  (`terraform/lxc/network/pve-test-vm.yaml`, labeled `dhcp_test` on the
  switch) — `pve-test-vm` is nested inside `pve` and shares its
  physical trunk, so it would have collided. Same class of gap as the
  `connector_seg`/VLAN 100 fix below; 120 is the next tag free across
  `terraform/lxc/network/*.yaml` as of 2026-09-23.
- **Database:** PostgreSQL — matches Authentik/NetBox/Wazuh, already
  operated on this platform; Nextcloud's own docs prefer it over MariaDB
  for new installs.
- **Storage:** rootfs and Docker storage use `platform-apps-zfs` (the
  ZFS-backed `apps-containers` pool); a 200G `durable-zfs` mount on
  `storage-containers` holds both user files and PostgreSQL data under
  separate directories. No NAS mount is part of the first deployment.
- **Auth:** Authentik OIDC (`user_oidc` app) wired from day one, via the
  same `edge-<stack>-<route>` reconciler pattern (`discover-authentik-edge.py`
  / `reconcile-authentik-edge.py`) already used for Harbor, Grafana,
  Portainer, Technitium, OpenWebUI, OpenSearch Dashboards, Wazuh
  Dashboard, Jellyfin, and Immich.
- **Ingestion (deep-research / CyberSecEval docs):** WebDAV push, keyed
  off the existing `reports/<project>/<run-id>/` storage convention
  (`docs/reporting-platform/CONVENTION.md`) rather than a bespoke path —
  see [plan.md](plan.md) Phase 2 for what that means concretely and what's
  still genuinely open (cross-node reach to CyberSecEval on `pve-tiny`).
- **Pangolin exposure (Phase 3, 2026-09-23):** not deprioritized after
  all — rolled into this plan. Anchored to a separate, already-existing
  repo, `/home/steve/git/oci`, which designs the OCI-hosted Pangolin edge
  and home-side Newt connector in real detail. The OCI instance hasn't
  changed since that design was written (operator-confirmed), so it's
  treated as current, not stale, and this plan adapts it rather than
  re-deriving it. Key constraint carried over: Newt gets a firewall rule
  only to a Traefik, **never** directly to `apps_seg` — a dedicated
  `connector_seg` VLAN and working OCI-side monitoring/logging are
  shared infrastructure, not nextcloud-specific one-offs.
- **LAN/Pangolin Traefik isolation (decided 2026-09-23): Option
  B — a second, dedicated Traefik instance (`pangolin-proxy`,
  192.168.30.11, `edge_seg`), not a second entrypoint on the existing
  shared Traefik.** `connector_seg`'s one firewall rule points only at
  `pangolin-proxy`; the main, LAN-facing Traefik (192.168.30.10) is
  unreachable from `connector_seg` entirely, by construction. Rejected
  the entrypoint-on-shared-instance option because its isolation is
  *policy* (the renderer must always assign entrypoints correctly as
  services get added) rather than *structural* (a second process simply
  has no router for anything not deliberately published to it). This
  generalizes beyond nextcloud-stack: any future Pangolin-published
  service (cse-panel, deep-research, others) rides the same
  `pangolin-proxy` instance and the same `connector_seg → pangolin-proxy`
  rule — no new VLAN or firewall rule per service, only a new opt-in
  entry in that service's own `edge.yaml`.
- **Authentik login for Pangolin-published routes:** `pangolin-proxy`
  needs its own copy of the shared `forwardAuth` middleware
  (`nextcloud-P3-03b`) — confirmed this works for free, no new firewall
  rule, because the middleware calls an internal-only hostname
  (`LAB_FQDN_AUTHENTIK_INTERNAL`) that resolves straight to Authentik,
  not through either Traefik, and `pangolin-proxy` sits in `edge_seg`
  alongside the main Traefik so it inherits the same existing
  `edge_seg → mgmt_seg:9443` rule. The real open item is OIDC-mode
  routes (not `forwardAuth`-mode ones like cse-panel/deep-research):
  `discover-authentik-edge.py` computes each route's expected
  `redirect_uris` from a single `host:` field, so a service published
  under two hostnames (LAN + `.pan.`) needs the reconciler taught to
  register both callback URLs against the same OAuth client — not yet
  built, see `nextcloud-P3-03c`.
- **Pangolin's own dashboard login is NOT Authentik-backed.** Checked
  the actual `oci` repo config (`group_vars/pangolin.yml`,
  `roles/pangolin/tasks/main.yml`) — no OIDC/SAML/IdP wiring exists for
  it. Every "Authentik" reference in that repo's docs is about
  *published applications'* own middleware, never about federating
  Pangolin's own login. Pangolin's dashboard uses its own native
  owner/user/MFA system, entirely separate from Authentik's centralized
  policies (session lifetime, group-based review, MFA enforcement).
  Since compromising the Pangolin dashboard means an attacker can
  define what gets published from the lab and to whom, it's arguably
  the single highest-value target in this whole design — treated as
  needing standalone hardening, not inherited from anything else here.
- **Security assessment (2026-09-23) of the Phase 3 design itself,
  updated after the Wazuh investigation:** Wazuh telemetry from OCI
  increased `connector_seg`'s blast radius (a second lateral target
  beyond `pangolin-proxy`) while a host agent could still be blinded by
  a compromised host. It is therefore retired in favor of OCI-native
  VCN Flow Logs/Audit/Cloud Guard, external checks, and recovery.
  `pangolin-proxy` (Option B) limits
  lateral *scope* from a compromised connector but does not eliminate
  Traefik-CVE exposure — two Traefik instances now need tracking on the
  same patch cadence, and the smaller, quieter one is the more likely to
  be forgotten. Full writeup: `nextcloud-P3-07` and
  `/home/steve/git/oci/docs/hardening-and-wazuh-plan.md`.
- **OCI SSH access: IP-restriction, not Bastion (decided 2026-09-23).**
  OCI's native Bastion service was considered for `nextcloud-P3-01`-
  adjacent reasoning (session-based, no persistent open port) but
  rejected: Bastion sessions are ephemeral (TTL-bound), which would
  require new wrapper tooling around Ansible and
  `scripts/pangolin-backup.sh` (both assume a static, always-reachable
  SSH host) just to keep existing OCI workflows working. The operator's
  egress IP is effectively static for this purpose; updated by hand via
  the OCI CLI if it ever changes. Executed live — see
  `hardening-and-wazuh-plan.md` Phase 1.
- **Wazuh retirement (decided 2026-09-23):** revoke and remove the
  pre-registered `oci-pangolin` agent rather than trying to repair its
  private route. Keep the historical record for auditability, but do
  not create a replacement home-lab route to Wazuh **for OCI-originated
  traffic through the tunnel** — that transport shape is what was
  retired, not home-lab Wazuh coverage in general.
- **nextcloud-stack and newt-connector monitoring (added 2026-09-24):**
  the OCI retirement above is specific to the Pangolin/Gerbil tunnel
  path and does not extend to ordinary same-network hosts. Both
  `nextcloud-stack` (Phase 1, `apps_seg`) and `newt-connector` (Phase 3,
  `connector_seg`) join the existing 6-host home-lab Wazuh agent pilot
  (`authentik-stack`, `proxy-stack`, `harbor-stack`, `technitium-stack`,
  `apt-cacher-stack`, `pve` — see `docs/wazuh-stack/README.md`), each via
  a narrowly-scoped new `<zone> -> wazuh-stack:1514,1515` firewall rule
  (`nextcloud-01c`, `nextcloud-P3-02b`) and the shared `wazuh_agent` role
  (`nextcloud-02d`, `nextcloud-P3-02c`). `newt-connector` is a
  particularly high-value target for this — it's the only host holding
  the live credential-bearing tunnel to OCI. Container-level metrics
  (cadvisor, `nextcloud-02c`/`02f`) and Docker→Graylog log forwarding
  (`nextcloud-02d`) are also now part of nextcloud-stack's first deploy,
  matching the pattern already live on `authentik-stack`/`netbox-stack`/
  `media-stack-lab` rather than treating monitoring/logging as a later
  add-on. See `plan.md` for the literal steps.
- **nextcloud-stack is hand-authored, not scaffolded (decided
  2026-09-24).** `scaffold-stack.sh`'s generic five-file path was dropped
  in favor of directly authoring `stack.yaml`/`terragrunt.hcl`/
  `docker-compose.yml`/the deploy playbook (`nextcloud-02`–`02e`),
  matching the precedent `wazuh-stack`/`opensearch-stack`/
  `greenbone-stack` already set — this plan had grown five separate
  hand-written patch steps on top of a generated playbook (registry-host
  fix, monitoring, Graylog forwarding, Wazuh agent, OIDC bootstrap), at
  which point the generator was only producing a skeleton immediately
  rewritten by hand anyway.
- **`connector_seg` network placement (recap):** VLAN
  110, `192.168.110.0/24`, gateway `192.168.110.1`, single host
  `newt-connector` at `192.168.110.10`. Changed from the originally
  planned VLAN 100 on 2026-09-23 after confirming on the physical
  switches that VLAN 100 is already live as `cse_seg`
  (`terraform/lxc/network/pve-tiny.yaml`) — 110 is the next tag not
  already claimed by any zone across `terraform/lxc/network/*.yaml`
  (10/20/30/40/50/60/70/80/90/100 all in use). Its only application
  destination is `pangolin-proxy` (192.168.30.11, `edge_seg`) on 443;
  TCP syslog to Graylog (192.168.20.14:514) is separately allowed through
  the shared managed-zone sender policy —
  the `connector_seg → wazuh-stack:1514` rule that briefly existed
  alongside it has been removed (Wazuh retired, see "Current execution
  state" above). Everything else explicit-deny; internet egress stays
  open for the actual Gerbil/Newt tunnel. See `nextcloud-P3-01` for the
  literal `pve.yaml` content.

## Research this plan is based on

- Zone/firewall shape modeled on `media_seg`'s real block in
  `terraform/lxc/network/pve.yaml` (lines 124–141, 256–260, 513–569),
  including three real gaps `media_seg` only discovered live after
  deploy (rsyslog forwarding to Graylog, node_exporter TLS from step-ca,
  and OIDC token exchange actually routing via `edge_seg` through
  Traefik rather than direct to `mgmt_seg:9443`) — `apps_seg`'s policy
  block below bakes all three in from the start instead of rediscovering
  them.
- **`scaffold-stack.sh` was tried first, then dropped (2026-09-24)** in
  favor of hand-authoring `stack.yaml`/`terragrunt.hcl`/
  `docker-compose.yml`/the deploy playbook directly, matching
  `wazuh-stack`/`opensearch-stack`/`greenbone-stack`'s existing
  precedent — the generic scaffolder stopped earning its keep once five
  separate hand-written patch steps had piled up on top of its generated
  playbook anyway. See plan.md's `nextcloud-02` for the full reasoning.
- Authentik OIDC wiring modeled on `media-stack-lab`'s real
  `edge.yaml` and its two `OIDC_ROUTE_CLIENT_IDS`/`OIDC_ROUTE_CLIENT_SECRETS`
  entries in `terraform/lxc/discover-authentik-edge.py`.
- Durable-storage shape modeled on `harbor-stack/stack.yaml`'s
  `extra_mount_path`/`extra_mount_size`/`extra_mount_profile: durable-zfs`/
  `extra_mount` block.
- Compose shape (pinned image tags, Harbor pull-through
  `${REGISTRY_HOST}/dockerhub/...` prefix, password-via-env convention)
  modeled on `netbox-stack/docker-compose.yml`'s
  app+Postgres+Redis pattern — **but not its `REGISTRY_HOST` resolution**,
  which resolves to `LAB_IP_HARBOR` (the bare Harbor IP) and is a known,
  twice-confirmed-live bug (`docker login`/pull gets "connection refused"
  on 443 against the raw IP — Harbor's TLS only works via the FQDN
  through Traefik). `nextcloud-02`/`02d` resolve `LAB_FQDN_HARBOR`
  instead from the start, the same way `media-stack-lab`'s playbook
  does.
- **apt-cacher, monitoring, and security-scan integration researched
  directly against the real, running platform, not assumed from the
  media-stack-lab precedent alone:**
  - `apt_cacher_host` is a `stack.yaml` field consumed by the `lxc_base`
    role (`terraform/lxc/ansible/roles/lxc_base/tasks/main.yml`) to point
    `apt` at `apt-cacher-ng:3142` — every existing stack sets it;
    `nextcloud-02`'s `stack.yaml` includes it.
  - Harbor (443) and apt-cacher (3142) reachability from a new zone is
    already covered by an existing blanket rule (`from: all_zones, to:
    infra_seg, ports: [80, 443, 3142]`) — no bespoke firewall rule needed
    for either.
  - VictoriaMetrics scrape targets are a fully manual, hardcoded static
    list living inside `deploy-monitoring-stack.yml` itself (lines
    183–264 as of this plan's writing) — there is no NetBox-driven
    auto-discovery for metrics despite NetBox tracking the host.
    `nextcloud-02f` adds the new target and redeploys `monitoring-stack`.
  - GVM/Greenbone scan coverage of a new SDN zone is explicitly treated
    by `docs/greenbone-stack/network-scan-rollout-plan.md` as a
    deliberate widening action, not a routine add — `nextcloud-01b`
    follows that doc's own process rather than inventing a new one.
- Reports convention read from `docs/reporting-platform/CONVENTION.md`
  and `docs/reporting-platform/README.md` — **this is the same convention
  the current `feat/reporting-cyberseceval-phase2` branch's work belongs
  to.** `deep-research` (on `pve`, `ai-services-stack`, `ai_seg`) already
  writes `reports/deep-research/<run-id>/{report.md,manifest.json}`;
  CyberSecEval writes the equivalent on `cse-controller`/`cse-panel-stack`,
  which live on the separate `pve-tiny` node. `docs/reporting-platform/README.md`
  explicitly defers cross-node unification (its own Phase 3) as "real,
  deliberate follow-up work, not something to build speculatively" —
  this plan follows that same discipline: Phase 2 below only covers the
  same-node (`pve`) `deep-research` push, and does not invent a
  `pve`↔`pve-tiny` ingestion path ahead of that upstream work landing.

## Still genuinely open

- **`NEXTCLOUD_STEVE_PASSWORD` SOPS key needed (added 2026-09-25).**
  Replaces `NEXTCLOUD_ADMIN_PASSWORD` following the Authentik-via-Pangolin
  rollback — the compose file and playbook now expect this exact name.
  `NEXTCLOUD_OIDC_CLIENT_ID`/`SECRET` are no longer read anywhere; leaving
  them in SOPS is harmless but they can be removed on a future SOPS
  edit pass.
- **Credential rotation.** The first bootstrap produced an over-verbose
  database exception log. Rotate `NEXTCLOUD_DB_PASSWORD` with a coordinated
  PostgreSQL, Compose, and SOPS update; do not treat this as a simple `.env`
  edit. The other first-deploy secrets are present in SOPS. `NEXTCLOUD_IMAGE_TAG`
  is non-secret and pinned in the operator's local `.env` to `35.0.0-apache`;
  review and deliberately update it during a future Nextcloud upgrade.
- **Monitoring validation.** The cAdvisor sidecar, Wazuh agent, and local
  Docker-to-rsyslog relay are deployed. Confirm the VictoriaMetrics/Grafana
  scrape and a real Graylog search before declaring metrics and log delivery
  end-to-end validated.
- **Deep-research → Nextcloud push implementation.** `nextcloud-P2-01`
  below identifies *where* this needs to hook in
  (`docs/reporting-platform/plan.md`'s Phase 1 adopter code path for
  `deep-research`) but the actual push code has not been written or
  scoped into a literal step yet — needs a follow-up research pass
  reading that code directly before it can become a real step block.
- **CyberSecEval → Nextcloud push, scoped 2026-09-25, not yet
  implemented.** Superseded the earlier "out of scope until
  `docs/reporting-platform/plan.md` Phase 3 lands" framing — pushing
  straight into Nextcloud turned out to be a simpler, separate design
  from that plan's shared viewer, doesn't need Phase 3's cross-node
  ingestion endpoint, and isn't blocked on it. Real step blocks are
  written (`nextcloud-P2-03` through `-05` below), but none have been
  executed yet: needs a new `cse_seg -> apps_seg:8080` MikroTik rule, a
  scoped Nextcloud service account + SOPS keys, then the code/Ansible
  edits and a `cse-controller` redeploy. See this file's Phase 2 and
  `docs/reporting-platform/plan.md` §5a.
- **EdgeManifest Pangolin opt-in mechanism (Phase 3) — done, live, and
  confirmed working with a real client.** `pangolin-proxy` is deployed,
  its generated `nextcloud.pan.gibbsgreatly.xyz` route serves Nextcloud,
  and Pangolin's dashboard resource `nextcloud-public` publishes that
  hostname through the `lab` site. The `nextcloud-users` role/SSO
  requirement was since removed from the resource (see "Pangolin SSO
  dropped for Nextcloud" above) — Nextcloud's own local login is the sole
  gate now. Confirmed end-to-end from the public internet: DNS resolves
  to the real OCI public IP, an unauthenticated request correctly gets
  `401` from Nextcloud's own auth (not Pangolin's), and the actual
  Nextcloud mobile app connects and syncs normally. The independent
  rollback test (disabling the Pangolin resource or route each
  independently blocks access) remains a maintenance-window task.
- **TOTP not yet enabled for `steve`.** `twofactor_totp`/
  `twofactor_backupcodes` are installed and enabled on the instance
  (confirmed via `occ app:list`), but nobody has actually gone through
  Settings → Security → Enable TOTP yet. Until this is done, `steve`'s
  local password is the only auth factor on a now-public resource.
- **Stale-route orphan-cleanup bug, found and fixed (2026-09-25).**
  Removing Authentik's `pangolin.private_host` route from `edge.yaml`
  didn't clean up its previously-rendered file — `write_rendered_files()`
  in `render-edge-traefik.py` only ever added/updated files, never
  removed one for a stack that stopped rendering. The stale
  `route-authentik-stack.yml` was still live on `pangolin-proxy`,
  actually serving real `302` responses from Authentik, until manually
  deleted; the next `provision.sh` run would have silently recreated it
  from the equally-stale local `.generated/pangolin-traefik/` file.
  Fixed at the source: the writer now does a full sync (add current,
  remove anything else matching `*.yml`) rather than only adding. Applies
  to both the LAN and Pangolin render paths. Regression test added; all
  39 tests pass.
- **OCI-side monitoring/logging.** Fully designed in
  `pangolin-observability-and-graylog-plan.md` but not yet implemented
  end-to-end. The shared lab Graylog TCP/514 transport and authenticated
  API were verified on 2026-09-24. OCI-native signals, external probes, and
  off-host recovery are intentionally deferred for this rollout and remain
  documented resilience follow-ups. Cloud Guard is excluded because it is not
  available to this free tenancy.
- **nextcloud-stack and Newt telemetry are deployed.** `nextcloud-stack` has
  its Wazuh agent, cAdvisor, Docker-to-rsyslog relay, and the
  `apps_seg -> wazuh-stack:1514,1515` policy/MikroTik mirror.
  `newt-connector` has a connected local Wazuh agent and its Compose-only
  FIM watch; its weekly refresh and security-only update timers are enabled.
  Do not add broad FIM watches such as `/root` or the whole Compose directory.
- **Greenbone scan reach (`nextcloud-01b`) not yet applied.** Confirmed
  live 2026-09-24: `apps_seg` has no `greenbone-stack`-sourced discovery
  rule in `pve.yaml`, and `192.168.120.10` isn't registered as a GVM scan
  target. This step was deliberately deferred until the host was real and
  reachable (per its own note in plan.md) — that precondition is now met,
  so this is actionable, just not yet done.
- **Monitoring-stack scrape target (`nextcloud-02f`) confirmed not
  applied live 2026-09-24** — `deploy-monitoring-stack.yml` has no
  `nextcloud` reference yet, matching the "Monitoring validation" item
  above; listed here explicitly so it doesn't get missed as a discrete
  redeploy step.
- **Wazuh critical package findings remediated on Nextcloud and Newt
  (2026-09-24).** A deliberate maintenance-window `apt-get upgrade` was
  completed on both hosts. Each reports zero remaining upgrades, no reboot
  requirement, and an active connected Wazuh agent; Nextcloud's status
  endpoint and Newt's Pangolin tunnel were also verified afterward. Wazuh
  will clear the historical findings on its next vulnerability inventory.
  The original Nextcloud findings were base-OS packages only (openssl,
  perl, glibc, libssh2, gnutls), not application-layer issues.
- **Nextcloud is enrolled in security-only unattended upgrades
  (`nextcloud-02g`, 2026-09-24).** `unattended-upgrades` is installed and
  both apt daily timers are enabled; automatic reboots remain disabled.
  The ongoing point-release policy is still a fleet-wide decision:
  glibc/perl fixes delivered only through Debian `trixie/main` require a
  deliberate maintenance upgrade under the current policy. Widening
  `Origins-Pattern` remains a separate decision and was not made here.
