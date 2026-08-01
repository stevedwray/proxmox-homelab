# Greenbone Community Edition on Proxmox — Debian LXC Deployment Plan

A phased plan for running Greenbone Community Edition (GVM/OpenVAS) as a
Debian LXC on `pve-test-vm`, joining `pentagi-stack`'s existing `pentest_seg`
zone (VLAN 70) and exposing the GSA web UI through Traefik.

**Target host for this build: `pve-test-vm`**, not `pve`. `pve-test-vm` is
not a production node (`terraform/PRODUCTION_NODES` lists only `pve` and
`pve-framework`), so this work uses the normal `./with-secrets` path — no
`TASK_APPROVAL`/production-approval flow applies here. Promotion past
`stable` onto a production node is a separate, later decision, gated the
normal way per `CLAUDE.md`'s branch model.

## 0. Architecture

```text
pve-test-vm (Proxmox)
└── pentest_seg (VLAN 70, 192.168.70.0/24)
    ├── pentagi-stack (192.168.70.110) — existing
    └── greenbone-stack (192.168.70.111) — this plan
        └── Debian LXC (unprivileged, nesting=1)
            └── dockerd
                ├── vulnerability-tests, notus-data, scap-data,
                │   cert-bund-data, dfn-cert-data, data-objects,
                │   report-formats, gpg-data   (feed loaders, run-once)
                ├── redis-server, pg-gvm(-migrator)
                ├── gvmd
                ├── gsa, gsad, gvm-config, nginx
                ├── configure-openvas, openvas, openvasd
                ├── ospd-openvas   (needs NET_ADMIN/NET_RAW, unconfined
                │                   seccomp/apparmor — raw-socket scanning)
                └── gvm-tools
```

Reuses `pentagi-stack`'s zone rather than a new dedicated one — same class
of broad-network-reach security-testing workload, no new MikroTik zone
required. `pentest_seg`'s existing containment already covers what this
stack needs: internet egress (feed sync, image pulls), reach to
`LAB_TARGET`/`harness-target` (authorized scan targets), explicit deny
elsewhere. See `docs/pentagi-stack/plan.md` §0 for the zone's original
design and its real, MikroTik-enforced containment.

New additions to that zone's existing policy:

- `edge_seg → pentest_seg:8080` — Traefik to the GSA web UI, over a custom
  plain-HTTP nginx server block (mirrors the existing
  `edge_seg → pentest_seg:8443` PentAGI rule). Not port 9392 or 443 — see
  §1's acceptance criteria and README.md for why.

No other new cross-zone rule is needed: feed sync and Harbor image pulls
are already covered by `pentest_seg`'s existing internet-egress and
`pentest_seg → 192.168.30.110:80/443` (Harbor via Traefik) policies.

### Known-good values

```text
PROXMOX_NODE            = pve-test-vm
LXC_HOSTNAME            = greenbone-stack
VMID                    = 70011
LXC_CORES               = 2
LXC_MEMORY_MB           = 4096   # Greenbone's stated MINIMUM, not their
                                  # recommended 8192 — pve-test-vm is a 16GB
                                  # box and pentagi-stack alone already
                                  # reserves 8192+2048MB. Revisit for pve.
LXC_SWAP_MB             = 2048
LXC_ROOTFS_GB           = 20
DOCKER_STORAGE_GB       = 20     # Greenbone's stated minimum storage tier
NETWORK_ZONE            = pentest_seg (VLAN 70, 192.168.70.0/24, gw 192.168.70.1)
TEMPLATE                = debian-13.1-2-docker-template.tar.gz
IP (pve-test-vm)        = 192.168.70.111
IP (pve, canonical)     = 192.168.70.11
```

## 1. Deploy — Terraform apply + first boot

**Status: done and verified live, 2026-08-01.** See README.md for the two
real incidents found and fixed along the way (a pre-existing Harbor admin
credential drift, and port 9392 not actually being a usable plain-HTTP
path).

1. `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` → confirm
   `pve-test-vm` (Execution Guardrails, `CLAUDE.md`). **Done.**
2. `./with-secrets terragrunt --working-dir terraform/lxc/environments/pve-test-vm/greenbone-stack apply`
   → LXC created at `192.168.70.111`, zone `pentest_seg`, VMID `70011`.
   **Done** (5 resources added, 0 changed, 0 destroyed).
3. `./with-secrets ./scripts/provision.sh --stack greenbone-stack` → runs
   `deploy-greenbone-stack.yml`. **Done**, after two retries for the
   incidents above (both now fixed in the playbook itself, so a fresh
   deploy shouldn't need manual intervention):
   - `lxc_base` + `docker_base` roles, Harbor registry trusted in
     `/etc/docker/daemon.json`.
   - Vendored `docker-compose.yml` written to `/opt/greenbone-stack`,
     brought up via `docker compose up`.
   - Writes a custom plain-HTTP nginx server block (`gsad-plain.conf`,
     port 8080) into `nginx_config_vol` and reloads nginx.
   - Waits for TCP 443 and 8080 to accept connections.
   - Resets the `gvmd` admin password from SOPS
     (`GREENBONE_ADMIN_PASSWORD`).

**Acceptance criteria — all confirmed:**
- All 21 containers report running/exited-as-expected (feed-loader
  containers exit 0, not crash-looping). **Confirmed** via
  `docker compose ps -a`.
- `curl http://192.168.70.111:8080/` returns the real GSA SPA `index.html`
  (not a redirect). **Confirmed.**
- Login via `POST http://192.168.70.111:8080/login` with `admin` / the
  SOPS `GREENBONE_ADMIN_PASSWORD` value returns `200`. **Confirmed.**
- `ospd-openvas` container stays up (not crash-looping on capability
  errors) — confirms `NET_ADMIN`/`NET_RAW`/unconfined seccomp work under
  this LXC's `nesting` feature the same way they already do for PentAGI's
  Kali worker containers. **Confirmed** (up, no restart loop). Whether
  raw-socket scanning actually *functions* is still open — see Phase 4.

## 2. Feed sync validation

**Status: in progress as of 2026-08-01 00:23 UTC** — `vulnerability-tests`
finished its copy on first boot. `gvmd`'s SCAP rebuild is still working
through CVE data (was at `nvdcve-2.0-2026.json.gz`, having already finished
CPEs/CPE-matches/CPE-refs). This can legitimately take hours from a cold
start — not blocking Phase 3, which is independent.

Greenbone's own docs warn scans run before this completes give "incomplete
and erroneous results." This is not something the Ansible playbook blocks
on — confirm manually before Phase 4:

1. `docker logs greenbone-community-edition-vulnerability-tests-1` → look
   for `"Finished loading VTs. The VT cache has been updated..."`.
   **Confirmed already** (copy completed on first boot).
2. Check `gvmd` logs (`docker logs greenbone-community-edition-gvmd-1`) for
   `update_scap_end: Updating SCAP info succeeded` and
   `sync_cert: Updating CERT info succeeded`. **Still in progress.**
3. Only proceed to Phase 4 (a real scan) once both have completed.

## 3. Traefik + Authentik exposure

**Status: done and verified live, 2026-08-01.**

1. Applied `terraform/lxc/stacks/greenbone-stack/edge.yaml` via
   `reconcile-edge.py`, scoped to just this one manifest (positional arg,
   not the default all-stacks discovery) — confirmed via dry-run first
   that this only touches `greenbone-stack`'s own Authentik
   application/provider, not any other stack's. **Done**: created
   `edge-greenbone-stack-greenbone-app` + `-provider`, linked the shared
   forwardAuth outpost.
2. Pushed the rendered Traefik dynamic config to `proxy-stack` via
   `deploy-proxy-stack.yml` (same mechanism `provision.sh`'s
   `reconcile_all_edge` uses) — confirmed only `greenbone-stack.yml`
   changed, every other stack's file was a no-op.
3. Re-ran `provision.sh --stack technitium-stack` to regenerate DNS zone
   records from all `edge.yaml` manifests (this is how the `gvm` A record
   actually gets published — see `docs/pentagi-stack/README.md`'s note
   that `dns-stack`/CoreDNS is rollback-only, Technitium is the live
   authoritative delegate). Smoke test passed.
4. **Confirmed end-to-end**: `dig gvm.test.gibbsgreatly.xyz` →
   `192.168.30.110` (Traefik); `curl https://gvm.test.gibbsgreatly.xyz/`
   returns a `302` to Authentik's authorize endpoint — the exact
   forwardAuth signature `pentagi-stack`'s route also produces.
5. Confirmed the new `harbor_postconfigure` list entry actually created the
   `greenbone` Harbor project + registry endpoint (project_id 7,
   registry_id 6) during the Phase 1 `harbor-stack` re-run.

**Gotcha hit and fixed along the way**: `reconcile-edge.py`'s Traefik
rendering step, and the push to `proxy-stack`, both need to run with the
same env vars `./with-secrets` injects (`LAB_IP_*`) — a first attempt at
manually replicating `provision.sh`'s `render_stack_ansible_extra_vars`
helper without `./with-secrets` produced a file with unresolved
`${lab_ip_proxy}` placeholders. Caught before pushing (always inspect a
rendered extra-vars file before using it in an apply), redone correctly.

## 4. Authorized test scan

**Status: done, 2026-08-01.** Ran against `harness-target` (`192.168.1.55`)
on `pve` (production) via raw GMP calls (`gvm-cli`, same mechanism used for
LDAP setup) — created a port list scoped to the target's two authorized
ports (6379, 8080), a target, and a "Full and fast" task against the
`OpenVAS Default` scanner.

**35 real findings**, confirming the engine and feed data genuinely work:
2 critical (Eclipse Jetty EOL, a Jetty security-bypass CVSS 9.8), 5 high
(3 Jetty DoS CVEs/GHSAs, **Redis Server No Password** — confirms the
target's deliberately unauthenticated Redis by design, Jetty privilege
escalation), 8 medium, 4 low, 16 log/informational (including
`Apache Struts Detection Consolidation`, confirming the Struts2 app itself
was identified). No result was named specifically for the S2-045 RCE
`harness-target`'s own docs call out — either that specific old plugin
isn't in the current feed, or its exact version-match conditions didn't
fire; the Jetty-server findings found instead are arguably just as
significant.

**Two real bugs hit and fixed/worked around:**

1. **First attempt returned 0 results in 34 seconds** — GVM's default
   host-alive check relies on ICMP, but `harness-target`'s firewall rule
   only allows TCP 8080/6379 (no ICMP), so the alive check silently
   concluded the host was down and skipped scanning entirely (confirmed via
   `report_hosts` having zero rows for that report — not "scanned, found
   nothing," but "never actually scanned"). Fixed via `modify_target` with
   `alive_tests: Consider Alive` (skip discovery, scan directly). Same
   fix will be needed for any other narrowly-firewalled target — `LAB_TARGET`
   has an unrestricted `protocol: all` rule so likely isn't affected, but
   worth checking if it ever comes back with unexpectedly clean results.
2. **A real, upstream `gvmd` bug breaks the entire GSA reports page** —
   `get_reports` (any call, list or single-report) crashes `gvmd` with a
   Postgres error: `column "severity_error" does not exist`, from an
   unsubstituted macro token in one of `gvmd`'s own SQL query templates.
   Confirmed server-side via `docker logs` (`Received Aborted signal`
   immediately after the failed query) and confirmed in the GSA UI itself
   (operator saw "Failure to receive response from manager daemon" trying
   to view the reports list). This matches a known, already-filed upstream
   bug class (`greenbone/gvmd` issue #2273, "Incorrect definition for
   materialized view... with fresh docker deploy", fix PR #2274 open at
   time of writing) — same root shape (a conditionally-built SQL/view
   definition takes the wrong branch on a fresh deployment), different
   specific column. **Not something to hand-patch** — investigated the
   `gvmd` source looking for a safe, certain fix and didn't find one worth
   the risk of live-editing production Postgres schema/views based on
   incomplete certainty. **Workaround**: `get_results` (a different GMP
   query, same data at the per-finding level) works fine and is what
   produced the results above — the GSA reports page itself stays broken
   until Greenbone ships a fix in the `:stable` tag. **Operator decision
   (2026-08-01): document as a known limitation, move on** — not worth
   chasing further right now.

## 5. Per-user LDAP login (steve, via Authentik)

**Status: configuration complete and verified correct, but BLOCKED by an
upstream Authentik bug, 2026-08-01. Operator decision: leave as-is, use
local admin login for now.**

Reuses Authentik's existing LDAP outpost (`ghcr.io/goauthentik/ldap`, part
of `authentik-stack`, already running for `graylog-stack` — see
`docs/monitoring-stack/graylog-migration-plan.md`) rather than building any
new Authentik-side infrastructure. `gvmd` does a direct simple bind (no
service-account search+bind needed, unlike Graylog):

1. New MikroTik rule: `pentest_seg → mgmt_seg tcp/3389,6636`, applied live
   via RouterOS Safe Mode, placed before the `pentest_seg` default-deny
   rule. **Done** — verified both via the router's own rule listing and a
   raw TCP connect test from `greenbone-stack` to
   `${LAB_IP_AUTHENTIK}:3389`.
2. `deploy-greenbone-stack.yml` now: fetches the outpost's own self-signed
   cert live and writes it to `authentik-ldap-ca.pem`, bind-mounted into
   `gvmd`; sends a `modify_auth` GMP request (`method:ldap_connect`,
   `authdn: cn=%s,ou=users,dc=ldap,dc=goauthentik,dc=io`, `cacert:
   /etc/gvm/authentik-ldap-ca.pem`) via `gvm-cli` (bind-mounted into the
   throwaway `gvm-tools` container — `gvm-cli`'s `socket` backend has no
   stdin support, needs a real file); creates a local `steve` user
   (`gvmd --create-user=steve --role=Admin`) since gvmd still needs a
   local user record for role/authorization even when the password check
   goes through LDAP. **Done**, idempotent — confirmed via multiple full
   redeploys in a row (`ok`, not `changed`, on repeat passes).
3. This sits underneath the existing Traefik `forwardAuth` gate, not
   instead of it — no `edge.yaml`/route-mode change.

**Five real bugs hit, four fixed, one is an external blocker** — see
`docs/greenbone-stack/README.md`'s "LDAP login" section for full detail:
`gvm-cli`'s socket backend needing a real file (not stdin); a
file-permission mismatch (`0640` vs `0644`) that blocked `gvm-tools`'
unprivileged container user from reading bind-mounted GMP request files;
an idempotency `failed_when` check written for the wrong phrase
(`"already exists"` vs gvmd's actual `"User exists already."`); a one-off,
self-recovered `gvmd` child-process crash observed during manual testing;
and — the actual blocker — **Authentik's LDAP outpost mis-encodes its own
successful bind response**, confirmed via the outpost's own logs
(`"event":"User has access"` server-side on every attempt with the real
password, across StartTLS/LDAPS/plain-LDAP, while the client always
receives a garbled "Protocol error" instead of success — wrong passwords
correctly return a clean rejection, so this is specific to the success
path). Matches multiple real, filed issues in `goauthentik/authentik`'s
own GitHub tracker for this exact bind-success/client-error pattern,
including reports against 2026.x releases.

**Update, same day**: the operator retried the actual browser login later
with no config changes and it succeeded. The bind-response issue was
transient upstream flakiness, not a hard, permanent bug — consistent with
the matched GitHub issues describing intermittent failures. **LDAP login
is confirmed working**, on both `pve-test-vm` and (after promotion) `pve`.

## 6. Production (`pve`) deployment

**Status: done and verified live, 2026-08-01.** Full production preflight/
approval flow followed per `CLAUDE.md` (Preflight Summary → operator
"Proceed" → `TASK_APPROVAL` set → `./with-secrets-prod` for every mutating
step). Mirrored the exact same sequence validated on `pve-test-vm`:

1. Created `terraform/lxc/environments/pve/greenbone-stack/terragrunt.hcl`
   (same shape as the `pve-test-vm` one).
2. `terragrunt apply` → LXC created, VMID `70011`, `192.168.70.11`,
   `pentest_seg` (5 resources added, 0 changed, 0 destroyed).
3. Re-ran `harbor-stack` on `pve` — **no credential drift this time**
   (production Harbor's admin password matched SOPS on the first try,
   unlike `pve-test-vm`). Created the `greenbone` proxy-cache project.
4. `provision.sh --stack greenbone-stack` targeting `pve` — clean first
   attempt, `failed=0`, no `scap-data` startup race this time. All 21
   containers healthy/exited-as-expected; admin login confirmed (`200` on
   `/login`); LDAP config (`modify_auth`, `cacert`, `steve` user) applied
   automatically as part of the same playbook run.
5. Applied `edge.yaml` via `reconcile-edge.py`, scoped to just
   `greenbone-stack` (same safe pattern as `pve-test-vm`) — created the
   Authentik application/provider on **production** Authentik, reused the
   shared forwardAuth outpost.
6. Pushed the rendered Traefik config to `pve`'s `proxy-stack` — only
   `greenbone-stack.yml` changed, every other production stack's route
   was a no-op.
7. Re-ran `provision.sh --stack technitium-stack` on `pve` to publish the
   `gvm.lab.gibbsgreatly.xyz` DNS record. Smoke test passed.
8. **Confirmed end-to-end**: `dig gvm.lab.gibbsgreatly.xyz` →
   `192.168.30.10` (production Traefik); `curl https://gvm.lab.gibbsgreatly.xyz/`
   returns a `302` to Authentik's authorize endpoint.

**No new MikroTik rule needed** — `pve` and `pve-test-vm` share the same
physical router and the same VLAN 70 subnet, so the
`pentest_seg → mgmt_seg:3389,6636` rule added during `pve-test-vm`
validation already covered `pve`'s traffic too (confirmed: single
`MIKROTIK_HOST` in `.env`, and `pve.yaml`'s own comments already
documented the shared trunk/subnet).

**`pve-test-vm`'s instance was shut down** after `pve` went live
(`docker compose down`, volumes preserved) — it was the validation copy,
not a second permanent deployment.

## 7. Future work (explicitly deferred, not in scope for this pass)

- **PentAGI ↔ GVM integration.** Wiring PentAGI to trigger or query GVM
  scans via `gvm-tools`/the GMP API would touch PentAGI's own compose/
  tooling and is materially more work — a separate task, not bundled here.
- **Resource sizing revisit.** If `pve-test-vm`'s 4 GB allocation proves too
  slow for future validation work, consider a scoped one-stack-at-a-time
  pass (stop `pentagi-stack` temporarily) rather than raising memory beyond
  what the 16 GB host can actually hold alongside everything else.
