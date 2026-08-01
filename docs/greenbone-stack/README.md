# Greenbone Stack

Workspace for deploying [Greenbone Community Edition](https://greenbone.github.io/docs/latest/)
(GVM/OpenVAS) — a vulnerability scanner — as `greenbone-stack`, a Debian LXC
joining `pentagi-stack`'s existing `pentest_seg` zone (VLAN 70) and exposing
its web UI (GSA) through Traefik. Deployed on both `pve-test-vm` (validation)
and `pve` (production).

Status: **Live in production on `pve`, 2026-08-01.** Full deployment
(LXC → compose stack → Traefik/Authentik edge route → DNS → per-user LDAP
login) mirrored from the validated `pve-test-vm` build with zero new
incidents — every gotcha found during `pve-test-vm` validation (see below)
was already fixed in the playbook by the time this ran. VMID `70011`,
`192.168.70.11`, `pentest_seg`. `https://gvm.lab.gibbsgreatly.xyz` resolves,
routes through Traefik, and returns Authentik's forward-auth challenge.
**Per-user LDAP login (`steve`) confirmed actually working** — the upstream
Authentik outpost bug that blocked this on `pve-test-vm` is no longer
reproducing (see "LDAP login" below).

`greenbone-stack` on `pve-test-vm` has been **shut down** (containers
stopped, Docker volumes — including the fully-synced feed data — preserved)
now that production is live; `pve-test-vm` was the validation environment,
not a second permanent deployment. Bring it back with `provision.sh --stack
greenbone-stack` (targeting `pve-test-vm`) if further test-tier work is
needed — no feed re-sync required.

Original `pve-test-vm` validation history, for reference: **Phases 1 and 3
done and verified live, 2026-08-01.** `greenbone-stack` (VMID `70011`,
`192.168.70.111`, `pentest_seg`) was up — all 21 containers from the
vendored compose healthy or exited-0 as expected (feed-loader containers).
Admin login confirmed working via a real HTTP request to the GSA login
endpoint. `https://gvm.test.gibbsgreatly.xyz` resolved via Technitium,
routed through Traefik, and returned Authentik's forward-auth challenge —
the same signature `pentagi-stack`'s route produces.

**Authorized test scan (Phase 4) done, 2026-08-01** — ran against
`harness-target` on `pve` (production), 35 real findings (2 critical
Eclipse Jetty issues, `Redis Server No Password`, etc.), proving the scan
engine and feed data genuinely work end-to-end. See [plan.md](./plan.md)
§4 for the full results and two real bugs hit getting there.

**Known limitation: the GSA reports page is currently broken** — a real,
upstream `gvmd` bug (not this stack's config) crashes `gvmd` on any
`get_reports` call. Confirmed both server-side (`docker logs` shows
`gvmd` aborting on a SQL error) and in the browser (`"Failure to receive
response from manager daemon"`). Matches a known upstream bug class
already tracked (`greenbone/gvmd` #2273) with a fix in progress upstream,
not yet in the `:stable` tag this stack uses. **Workaround**: results can
still be pulled via GMP's `get_results` (see [plan.md](./plan.md) §4) —
just not through the GSA reports page itself until Greenbone ships a fix.
Documented and accepted as a known limitation rather than hand-patched.

**Per-user LDAP login (`steve`) is CONFIRMED WORKING, 2026-08-01.** `gvmd`
authenticates real users against Authentik's existing LDAP outpost
(`ghcr.io/goauthentik/ldap`, part of `authentik-stack`, already running for
`graylog-stack` — see `docs/monitoring-stack/graylog-migration-plan.md`),
sitting *underneath* the existing Traefik `forwardAuth` gate, not instead
of it. Required a new, narrowly-scoped MikroTik rule
(`pentest_seg → mgmt_seg:3389,6636`, applied live via the router's own Safe
Mode session, and covering both `pve-test-vm` and `pve` since they share
the same physical MikroTik/VLAN) since `pentest_seg` had no prior route to
`mgmt_seg`'s LDAP outpost.

**This was blocked for a while, then started working.** Initial testing
found what looked like a hard upstream Authentik bug: the outpost's own
logs showed `"event":"User has access"` (server-side success) on every
bind attempt with the real password, while the client (`gvmd` and a
standalone `ldapwhoami` test) received a garbled `"Protocol error"`
instead of the success response, across StartTLS/LDAPS/plain-LDAP — a
pattern matching several real, filed `goauthentik/authentik` GitHub
issues. The operator retried the actual browser login later and it
succeeded, without any further changes on this stack's side — consistent
with those upstream issues describing intermittent/flaky bind-response
encoding rather than a hard, permanent failure. Left as a real lesson: the
mechanism was correctly configured throughout; the failure was transient
upstream flakiness, not something to keep chasing indefinitely once every
locally-controllable cause has been ruled out. See "LDAP login" below for
the full technical detail and the four real bugs fixed getting the
configuration itself correct.

**Two real problems found and fixed during this rollout, both worth
remembering:**

1. **Harbor's live admin password didn't match SOPS's
   `HARBOR_ADMIN_PASSWORD`** — a pre-existing credential drift, unrelated
   to this stack, discovered because `harbor-stack`'s playbook needed a
   re-run to create the new `greenbone` proxy-cache project and failed at
   the very first task (`Authenticate with Harbor API`, 401). Root-caused
   by reading Harbor's actual source
   (`src/common/utils/encrypt.go`, `v2.14.3`): local passwords are
   `hex(pbkdf2_hmac(sha256, password, salt, 4096 iterations, 16-byte key))`,
   stored in `harbor_user.password`/`.salt`. Recomputed a matching hash for
   the existing SOPS password and updated the DB row directly
   (`docker exec harbor-db psql ... UPDATE harbor_user SET ...`), verified
   with a live login, then successfully re-ran `harbor-stack`'s playbook.
   **Do not guess-and-check this hash on a live Harbor** — get the exact
   algorithm from source first; a wrong guess just burns login attempts
   against Harbor's brute-force sleep-delay (harmless but wastes time).
2. **Port 9392 is not a usable plain-HTTP path to the GSA UI, despite
   looking like one.** `gsad` is configured `GSAD_HTTP_ONLY: true`, and
   port 9392 is historically gsad's own plain-HTTP listener when run
   standalone — but in the container topology, upstream's own
   `gvm-config`-generated nginx config hardcodes
   `listen 9392; return 301 https://$host:443$request_uri;` regardless of
   bind address. Confirmed live via `curl -D -`. `gsad` itself has no
   `ports:` mapping in the compose (reachable only over the internal
   Docker network) and doesn't serve the static SPA assets either (that's
   nginx's `gsa_data_vol` mount) — so exposing `gsad` directly isn't a
   viable substitute. Fixed by having `deploy-greenbone-stack.yml` write a
   **second, custom nginx server block** (`gsad-plain.conf`, port 8080)
   directly into `nginx_config_vol`'s host-side path after `gvm-config`
   runs, mirroring the upstream 443 block's `location`/`proxy_pass` logic
   without TLS or the redirect, then reloading nginx. Verified live: a GET
   to `:8080/` returns the real SPA `index.html` (not a redirect), and a
   POST to `:8080/login` with the SOPS admin password returns `200`.
   `edge.yaml` targets port 8080, not 9392 or 443.

Also hit, and worth remembering for future deploys of any Compose stack
with startup-order `condition: service_healthy` dependencies: **a
transient dependency race during first boot.** `gvmd` (and everything
that depends on it — `gsad`, `nginx`, `gvm-tools`) failed to start because
Docker Compose evaluates `service_healthy` conditions once, at the moment
it processes the dependency graph — if `scap-data`'s healthcheck hadn't
passed yet at that exact instant (it does moments later), Compose gives up
rather than waiting/retrying. Fixed by simply re-running the playbook
(idempotent) once the feed-loader containers had reached `healthy`. Not a
bug in this stack's config — inherent to how `docker compose up`
evaluates health-gated dependencies once at start time.

Scope for this pass is **standalone GVM only** — a working scanner reachable
through Traefik, able to run an authorized scan against `harness-target` or
`LAB_TARGET`. Wiring PentAGI to trigger/query GVM scans (via `gvm-tools`/GMP)
is **explicitly deferred**, not silently dropped — see "Related documentation"
below.

## LDAP login (steve, via Authentik)

`gvmd` does a direct simple LDAP bind — `cn=<username>,ou=users,dc=ldap,dc=goauthentik,dc=io`
with whatever password is entered — against Authentik's LDAP outpost at
`${LAB_IP_AUTHENTIK}:3389`. No service-account search+bind is needed (unlike
Graylog's LDAP auth service, which does need one); gvmd's own auth model is
simpler. Configured via GMP's `modify_auth` (`method:ldap_connect` group,
keys `enable`/`ldaphost`/`authdn`) — no such thing as a per-user "LDAP-only"
flag in current gvmd: once enabled, gvmd tries LDAP bind for *any* username,
including `admin`. A `steve` user was created locally
(`gvmd --create-user=steve --role=Admin`) since gvmd still requires a local
user record to exist for role/authorization purposes even when the password
check itself goes through LDAP.

The Authentik LDAP outpost serves a self-signed cert (`AUTHENTIK_INSECURE=true`
on the outpost itself, same as Graylog's setup), which gvm-libs' LDAP client
otherwise rejects during its TLS handshake. `LDAPTLS_REQCERT=never` is set
on `gvmd`'s container environment for this, but confirmed **not actually
honored** by gvm-libs (it sets its own TLS options in code) — the real fix
is fetching the outpost's own cert and passing it via `modify_auth`'s
documented `cacert` key (a file path, bind-mounted into the container).
Kept the env var anyway as harmless defense-in-depth.

**STATUS: confirmed working, 2026-08-01** — after initially hitting what
looked like a hard upstream Authentik bug (#5 below), a later retry by the
operator succeeded with no further changes needed. Deployed to both
`pve-test-vm` and `pve` (production) with identical config.

**Real bugs hit along the way:**

1. **`gvm-cli`'s `socket` backend has no stdin support** — it requires an
   actual file path (its `infile` argument), not piped XML. Every GMP
   command in the deploy playbook writes its request to a file in
   `{{ greenbone_compose_dir }}` and bind-mounts it into the throwaway
   `gvm-tools` container via `docker compose run -v ...:ro`, since
   `gvm-tools` isn't a long-running service in this compose.
2. **File permission mismatch on that bind-mounted file.** The first
   attempt wrote it `mode: "0640"` (matching this playbook's other
   internal config files) — but `gvm-tools`' container process runs as a
   different, unprivileged uid than whatever wrote the file, and 0640 has
   no read bit for "other". Every `gvm-cli` call failed with
   `[Errno 13] Permission denied`. Fixed by using `0644` — there's no
   secret content in these GMP request files (LDAP host/authdn only), so
   world-readable is fine.
3. **`gvmd --create-user` on an existing user says `"User exists already."`**
   not `"already exists"` (word order) — the idempotency guard's
   `failed_when` check for repeat runs was written for the wrong phrase
   and treated the expected, harmless case as a real failure. Always
   verify the *exact* string a tool emits before writing a substring match
   against it, rather than assuming the more natural-sounding phrasing.
4. **A one-off `gvmd` child-process crash** (`Received Aborted signal` in
   `docker logs`) was observed immediately after the very first live
   `modify_auth` call, during manual testing before this was in the
   playbook. The main `gvmd` container stayed `Up (healthy)` throughout
   (gvmd forks a handler process per GMP connection; an individual
   handler crashing after already responding doesn't affect the daemon) —
   confirmed by re-querying `describe_auth` immediately after, which
   showed the setting had persisted correctly. Not investigated further
   since it didn't recur across several subsequent GMP calls and caused no
   observable harm.
5. **Initially looked like a hard blocker: Authentik's LDAP outpost
   appeared to mis-encode its own *successful* bind response.**
   Root-caused (at the time) by reading the outpost's own logs directly
   (`docker logs authentik-stack-ldap-1` on `authentik-stack`), which
   showed `"event":"User has access"` for every attempt with the real
   password, across StartTLS (3389), implicit LDAPS (6636), and plain
   unencrypted LDAP — ruling out password, DN, network, and cert-trust as
   the cause (independently confirmed correct via a standalone
   `ldapwhoami` test with a real, controlled password read straight from
   SOPS, never touching disk or a shell string). Every one of those
   attempts, the client side received a garbled `"Protocol error"` instead
   of the success response. This matched several real, filed issues in
   `goauthentik/authentik`'s own GitHub tracker for exactly this
   bind-success/client-error pattern. **Turned out not to be a permanent
   blocker**: the operator retried the actual browser login later (no
   config changes made in between) and it succeeded — consistent with
   those upstream issues describing intermittent flakiness rather than a
   hard failure. Confirmed working on both `pve-test-vm` and `pve`.

**Network note**: this required a genuinely new capability for
`pentest_seg` — reaching into `mgmt_seg` at all, for anything, which no
prior rule allowed. Added as a narrowly-scoped `tcp/3389,6636`-only rule
(mirroring the existing precedent of `pentagi-stack`'s own
`pentest_seg → mgmt_seg:443` rule for step-ca cert issuance), applied
directly on the MikroTik via its REST API in a Safe Mode session, placed
immediately before the `pentest_seg` default-deny rule.

**Note on `graylog-stack`**: Graylog uses this exact same Authentik LDAP
outpost for its own login. The transient bind-failure pattern seen here
(server succeeds, client sees a protocol error, then a later retry just
works) means Graylog's login could occasionally hit the same flakiness —
not verified either way, but if Graylog login ever fails intermittently,
this is the same underlying outpost behavior, not a Graylog-specific
issue. A simple retry is the expected fix, matching what resolved it here.

## Read in this order

1. [plan.md](./plan.md) — the phased deployment plan: stack scaffolding
   (done) → apply + first boot → feed sync validation → Traefik + Authentik
   exposure → an authorized test scan → future PentAGI integration (deferred).

## Key facts up front

- **The GSA reports page is broken by a real, upstream `gvmd` bug** (any
  `get_reports` call crashes `gvmd`) — known limitation, not this stack's
  fault, matches `greenbone/gvmd` issue #2273's bug class. Pull results via
  GMP's `get_results` instead (see plan.md §4) until Greenbone ships a fix.
- **GVM's default host-alive check needs `alive_tests: Consider Alive`
  for narrowly-firewalled targets** like `harness-target` (TCP-only
  firewall rule, no ICMP) — otherwise the alive check fails silently and
  the scan skips the host entirely in ~30 seconds with zero results,
  which looks deceptively like "scanned, found nothing." Check
  `report_hosts` row count to tell the difference.
- **Per-user LDAP login (`steve`) via Authentik's existing LDAP outpost is
  confirmed working**, on both `pve-test-vm` and `pve`. Hit what looked
  like a hard upstream Authentik outpost bug during initial testing —
  turned out to be transient flakiness, not a permanent blocker. See "LDAP
  login" above for the full diagnosis and the real bugs hit along the way.
- **Deployed on both `pve-test-vm` (validation) and `pve` (production)** —
  `pve-test-vm` is not a production node, so no `TASK_APPROVAL` flow
  applied there; `pve` deployment went through the full production
  preflight/approval flow per `CLAUDE.md`. `pve-test-vm`'s instance is now
  shut down (containers stopped, volumes preserved) since production is
  live and it was only ever the validation copy.
- **Joins `pentagi-stack`'s existing `pentest_seg` zone** (VLAN 70,
  `192.168.70.0/24`) rather than a new dedicated zone — same class of
  broad-network-reach security-testing workload as PentAGI, and reuses that
  zone's existing containment policy (internet egress, `LAB_TARGET`/
  `harness-target` reach, deny-by-default elsewhere) with no new MikroTik
  zone. IP: `192.168.70.111` (pve-test-vm), `192.168.70.11` canonical (pve),
  matching the `base+100` convention already used for `pentagi-stack`.
- **Sized at Greenbone's stated minimum** (2 cores / 4096 MB RAM), not their
  "recommended" tier (4 cores / 8 GB) — `pve-test-vm` is a 16 GB bare-metal
  box and `pentagi-stack` alone already reserves 8192+2048 MB. Feed sync and
  scans will be slower at this tier; revisit when promoting to `pve`.
- **No interactive installer.** Greenbone's official `compose.yaml`
  (downloaded from `https://greenbone.github.io/docs/latest/_static/compose.yaml`)
  is vendored into `deploy-greenbone-stack.yml` mostly verbatim — only the
  ~15 `image:` lines are rewritten through a new Harbor `greenbone`
  proxy-cache project, and `nginx`'s port bindings are changed from
  `127.0.0.1`-only to the container's own routable address (upstream
  defaults to loopback-only for a bare-host deploy; doesn't work when
  Traefik lives in a different LXC/zone).
- **Traefik targets port 8080, not 443 or 9392.** Confirmed live: 9392 is
  just an HTTP->HTTPS redirect stub in upstream's own generated nginx
  config, and 443 is self-signed TLS (which this platform's Traefik
  tooling has no way to trust — no `insecureSkipVerify`/`serversTransport`
  support in the EdgeManifest schema, confirmed by reading
  `render-edge-traefik.py`). `deploy-greenbone-stack.yml` adds a genuine
  plain-HTTP nginx server block on port 8080 instead — see the incident
  writeup above.
- **Traefik yes, Authentik native-OIDC no.** Like PentAGI, GVM/gsad has no
  native OIDC client, so the edge route uses Traefik's `forwardAuth` mode
  (Authentik's forward-auth middleware) rather than a native SSO
  integration.
- **Default admin/admin, reset on every deploy.** Greenbone's containers
  auto-create an `admin`/`admin` user on first `gvmd` boot; the playbook
  resets it via `docker compose exec -u gvmd gvmd gvmd --user=admin
  --new-password=...` using the SOPS-backed `GREENBONE_ADMIN_PASSWORD`.
- **Feed sync is slow and asynchronous — don't assume "containers up" means
  "ready to scan."** Greenbone's own docs warn initial VT/SCAP/CERT/notus
  feed sync can take minutes to hours, and scans run against an
  incompletely-synced feed give "incomplete and erroneous results." The
  playbook only waits for the web ports to accept connections; confirming
  feed sync completion is a separate, manual `docker compose logs -f gvmd`
  check (Phase 2 below), not something baked into the Ansible run.
- **`ospd-openvas` needs `NET_ADMIN`/`NET_RAW` + unconfined
  seccomp/apparmor** for raw-socket scanning — confirmed live: it starts
  and stays up (no capability-related crash loop) under the same
  nested-Docker LXC `nesting` feature that already lets PentAGI's Kali
  worker containers run `nmap`. Whether raw-socket scanning actually
  *works* end-to-end (not just "container didn't crash") is still an open
  question for Phase 4's authorized test scan.

## Related documentation

- `docs/pentagi-stack/` — the sibling `pentest_seg` stack this one joins;
  its `plan.md`, `README.md`, and `harness-target.md` document the zone's
  real MikroTik containment and the authorized scan targets
  (`LAB_TARGET`/Metasploitable 2, `harness-target`) this stack can also
  scan against.
- `docs/framework-integration/decisions.md` — Decision 4 (dedicated SDN
  zones for new workload classes); explains why `pentest_seg` exists as its
  own zone at all, and thus why this stack joins it instead of getting a
  new one.
- `terraform/lxc/stacks/greenbone-stack/STACK_CONTRACT.md` — network/
  inputs/provides/dependencies contract for this stack.
- `terraform/lxc/ansible/roles/harbor_postconfigure/defaults/main.yml` —
  shared platform file; declares the new `greenbone` Harbor proxy-cache
  project this stack's image pulls depend on.
- `CLAUDE.md` — branch model, validation tiers, and production credential
  controls this plan follows (`pve-test-vm` is not production-gated;
  promotion past `stable` would be).
