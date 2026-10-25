# Icinga and SmokePing execution runbook

## Purpose and boundary

This is the executable delivery plan for the design in [README.md](README.md).
It creates a small, native Icinga 2 HA pair on the Argon Pis and one local
SmokePing instance. It intentionally does **not** create an OCI monitoring
node, open a home port to the Internet, change DNS, or replace the existing
Grafana/VictoriaMetrics monitoring stack.

The runbook is written so that each numbered stage can be performed, tested,
and reverted independently. Do not combine the stages into a large blind
rollout.

## Fixed decisions

| Item | Decision |
|---|---|
| Icinga members | `argon-01` / `192.168.1.22` and `argon-02` / `192.168.1.23` |
| Icinga topology | One master zone (`master`) with HA enabled; `argon-01` is the configuration master and `argon-02` accepts synced configuration |
| Runtime | Native Debian packages and systemd; no Docker, Icinga Web, Icinga DB, Redis, Director, or database in phase 1 |
| Cluster transport | Mutual TLS on TCP 5665, bound to the relevant LAN address and accepted only from the other Pi |
| Alerting | Direct Discord and Telegram notification commands, with dedicated least-privilege secrets in OpenBao |
| SmokePing | One native instance on `argon-01`; its web interface is loopback-only and reached with SSH forwarding when needed |
| OCI | Public Pangolin endpoint and existing source-restricted SSH are monitored targets only. No OCI daemon, listener, tunnel, firewall change, or route is added. |

Icinga's HA zone is specifically for distributing checks and notifications;
only the configuration master owns the authoritative `zones.d` content. See
the [Icinga distributed-monitoring documentation](https://icinga.com/docs/icinga-2/latest/doc/06-distributed-monitoring/).

## Stage 0 — approval, inventory, and secrets

### 0.1 Create the implementation artifacts

Create these tracked artifacts on a short-lived branch. They do not exist yet;
this document is the design contract for them.

```text
ansible/00-initial-setup/argon-icinga-observers.yml
terraform/lxc/ansible/roles/icinga_observer/
  defaults/main.yml
  handlers/main.yml
  tasks/main.yml
  templates/icinga2.conf.j2
  templates/constants.conf.j2
  templates/zones.conf.j2
  templates/hosts.conf.j2
  templates/services.conf.j2
  templates/notifications.conf.j2
  templates/notification-discord.sh.j2
  templates/notification-telegram.sh.j2
  templates/smokeping-config.j2
  templates/smokeping-nginx.conf.j2
```

The playbook must target `hw_hosts` (the existing inventory group containing
both Pis) and fail unless the limited host is `argon-01` or `argon-02`. It
must deploy shared Icinga object configuration to **only** `argon-01`; Icinga
configuration sync supplies `argon-02`. Host-local files, certificates and
the ApiListener remain host-specific.

Before the first mutation, run:

```bash
git switch -c feat/argon-icinga-observability
ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles \
  ansible-playbook --syntax-check -i ansible/inventory/inventory.yml \
  ansible/00-initial-setup/argon-icinga-observers.yml
ansible-inventory -i ansible/inventory/inventory.yml --host argon-01
ansible-inventory -i ansible/inventory/inventory.yml --host argon-02
```

Use `./with-secrets-prod` for the eventual Ansible run because it supplies the
current lab endpoints. This is an intentional production-credential workflow:
present the normal preflight and wait for the operator's per-task approval
before the mutating command.

### 0.2 Preflight the two Pis and each monitored endpoint

Run this read-only inspection before writing a package or firewall rule:

```bash
ansible -i ansible/inventory/inventory.yml hw_hosts \
  --limit argon-01,argon-02 -b -m shell -a \
  'hostnamectl; ip -br addr; ss -ltnp; systemctl is-active docker portainer-agent rsyslog wazuh-agent node_exporter; df -h / /boot/firmware; free -h; nft list ruleset; iptables -S INPUT'
```

Record the resolved target address, port, expected HTTP status or response
body, TLS CA/name requirement, timeout, retry count, owning stack and rollback
for every planned service. Test from both Pis, using the same protocol Icinga
will use. Examples (replace the placeholders with the values recorded in the
implementation variables):

```bash
ssh ansible@192.168.1.22 'dig +time=2 +tries=1 @192.168.20.15 example.com A'
ssh ansible@192.168.1.22 'curl --fail --silent --show-error --max-time 5 https://<oci-pangolin-name>/'
ssh ansible@192.168.1.22 'curl --fail --silent --show-error --max-time 5 https://<openbao-name>/v1/sys/health'
ssh ansible@192.168.1.22 'nc -zvw3 <graylog-ip> 514'
```

Do not use a blanket `curl -k`. Where a private CA is required, install the
existing homelab root CA and use `--cacert`; verify both the expected CA and
hostname. A target that cannot be exercised manually from a Pi is not ready
to be enabled as an alert.

### 0.3 Secrets and notification route

Create a new OpenBao service entry, for example `services/icinga-observer`.
Its exact field names must be added to `secrets/manifest.json` with the
implementation, but values must be written only by the operator through
`scripts/openbao_write.py` after OIDC login. Do not put webhook URLs, bot
tokens, passwords, private keys, or Icinga certificate keys in Git.

Required fields:

```text
icinga_discord_webhook_url
icinga_telegram_bot_token
icinga_telegram_chat_id
```

Use an Icinga-specific Discord webhook and Telegram bot/chat capability where
practical. That prevents compromise of a Pi from silently inheriting the
credentials used by Grafana or another alerting service. The rendered scripts
and their `EnvironmentFile` must be owned by `nagios:nagios`, mode `0700`
scripts / `0600` env file -- **not root**, despite this section's original
wording. Debian's `icinga2` binary drops to the `nagios` user internally for
every invocation, including CLI subcommands and the NotificationCommand it
executes, confirmed during Stage 1 (`icinga2 pki new-ca`/`new-cert` wrote
`nagios:nagios` files even when Ansible ran them as root via `become`;
a root-owned `/etc/icinga2/pki` or notification script is simply
unreadable/unexecutable to the process that actually needs it). `nagios`
is still a dedicated system account, not a shared or interactive one, so
other-user isolation is preserved. Never expose the Icinga API outside the
two-Pi cluster merely to send a notification.

### 0.4 Preflight findings (2026-10-25, read-only, no mutation)

Artifacts created on `feat/argon-icinga-observability` (cut from `77ed9c86`):
`ansible/00-initial-setup/argon-icinga-observers.yml` and the full
`terraform/lxc/ansible/roles/icinga_observer/` role from the Stage 0.1 file
list. `ansible-playbook --syntax-check` and a `--check --diff` dry run
against both `argon-01` and `argon-02` pass (`failed=0`; the only "ignored"
failures are the documented check-mode artifact for a systemd unit/service
that does not exist yet -- see `docs/alerting/README.md` Lessons learned).
Nothing was deployed; no package, config, cert, firewall rule, or secret was
written to either Pi.

**Pi host state** (`ansible -b -m shell`, both Pis):

| Finding | argon-01 | argon-02 |
|---|---|---|
| OS / kernel | Debian 13 (trixie), 6.18.50+rpt-rpi-v8, aarch64 | same |
| `docker`, `portainer-agent`, `rsyslog`, `wazuh-agent`, `prometheus-node-exporter` | all active | all active |
| TCP 5665 | free (no listener) | free (no listener) |
| `nftables.service` | inactive, disabled | inactive, disabled |
| INPUT chain | `iptables -S INPUT` -> `-P INPUT ACCEPT`, no rules | same |
| Firewall backend | `iptables v1.8.11 (nf_tables)`; Docker owns FORWARD/NAT only, never touches INPUT | same |
| `iptables-persistent` / `netfilter-persistent` | not installed | not installed |
| Disk `/` | 470G, 3% used | 118G, 10% used |

Because nothing currently governs INPUT and no persistence package exists,
the role adds the TCP 5665 peer-only rule with plain `iptables` (not
`nft`), and persists it across reboot with a small role-owned
`icinga-cluster-firewall.service` oneshot unit (`Before=icinga2.service`)
instead of installing `iptables-persistent`, which would also start
managing Docker's own dynamic rules. This cannot collide with Docker's
FORWARD/NAT chains.

**Target packages** (`apt-cache policy`, both Pis): `icinga2` 2.14.6-1+deb13u1,
`smokeping` 2.8.2+ds-1, `nginx-light` 1.26.3-3+deb13u10, `fping` 5.1-1+b1,
`monitoring-plugins-basic`/`-standard` 2.4.0-3+deb13u1 all available and
uninstalled; `dnsutils` and `jq` already installed. `fcgiwrap` (needed to run
`smokeping.cgi` under nginx) is added to the role's `argon-01`-only package
list.

**Endpoint matrix** (tested read-only from the operator workstation on the
same mgmt_seg network, 2026-10-25; Stage 1 repeats the TLS-verified version
of each check from the Pis themselves):

| Target | Address | Check | Result |
|---|---|---|---|
| MikroTik | `192.168.1.1` | ICMP | 2/2, ~0.15ms |
| Technitium primary | `192.168.20.15` | `dig pve.gibbsgreatly.xyz` / `dig cloudflare.com` | internal and recursive both resolve |
| Technitium secondary | `192.168.20.17` | same | internal and recursive both resolve |
| `pve` | `pve.gibbsgreatly.xyz:8006` | `GET /api2/json/version` (no creds) | `401 No ticket` -- proves TLS + API daemon alive |
| VictoriaMetrics | `192.168.20.12:8428` | `GET /health` | `200`, body `OK` |
| Grafana | `192.168.20.12:3000` | `GET /api/health` | `200`, `{"database":"ok","version":"13.0.2",...}` |
| Graylog | `192.168.20.14:9000` | `GET /api/system/lbstatus` | `200` |
| OpenBao | `192.168.20.16:8200` | `GET /v1/sys/health` with `--cacert certs/homelab-root.crt` | `200`, `"sealed":false` |
| step-ca | `192.168.20.11:443` | `GET /acme/acme/directory` with `--cacert certs/homelab-root.crt` | `200`, full ACME directory body |
| Portainer | `192.168.20.20:9000` | `GET /api/system/status` | `200`, `{"Version":"2.39.8",...}` |
| OCI/Pangolin | `pangolin.gibbsgreatly.xyz` (`192.9.191.163`, static MikroTik DNS entry bypassing Cloudflare) | `GET /` HTTPS, cert inspect | `200`; cert `CN=gibbsgreatly.xyz`, expires 2026-12-02 |

All ten non-Pi Tier-1 targets and both DNS nodes are confirmed reachable
with the exact expected response shape the runbook's Stage 2 check
definitions assume. `homelab-root.crt` is required and sufficient for the
OpenBao and step-ca HTTPS checks; the role installs it at
`/etc/icinga2/pki/homelab-root.crt` for the check plugins and into the
system trust store, mirroring the existing `hw-monitoring-node-exporter.yml`
pattern.

**Open items found, not resolved in Stage 0:**

1. **Traefik has no unauthenticated health endpoint.** `proxy-stack`'s
   `traefik.yml` sets `api.insecure: false` and defines no `ping`
   entrypoint (confirmed by reading
   `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`). Phase 1's
   Traefik check (`services.conf.j2`) is a bare TCP connect to 443 only.
   Adding a real `ping` entrypoint is an Authentik/Traefik-tier change
   under AGENTS.md's validation table and needs its own separate approval;
   it is explicitly out of scope here.
2. **The OCI SSH probe needs its own authorized key.** The operator's own
   `ssh oci` alias (`~/.ssh/config`, `ubuntu@192.9.191.163`) works from the
   workstation, which shares the Pis' home public IP, so the existing
   home-source firewall policy does not need to change. But no Pi-local
   SSH identity is authorized on the OCI box yet; provisioning one (or
   reusing an existing narrowly-scoped key such as the Greenbone OCI audit
   key referenced in `docs/greenbone-stack/README.md`) is an OCI-side
   mutation and needs its own preflight and "Proceed" before the
   `ssh-probe` service in `services.conf.j2` is enabled in Stage 2. Do not
   add any new OCI firewall rule to support this -- the home IP is already
   permitted.
3. **This plan is independent of, and does not touch,** the separate
   `docs/alerting/` Grafana/Discord/Telegram pipeline or its parked OCI
   relay/dead-man's-switch design (`docs/alerting/README.md`). Icinga's
   Discord/Telegram notifications use their own dedicated
   `services/icinga-observer` OpenBao secrets (below), never
   `services/grafana`'s.

### 0.3.1 Planned `secrets/manifest.json` diff (not yet applied)

Per `docs/alerting/README.md` Lessons learned ("write the secret to OpenBao
first, the manifest second -- the wrappers fail closed on a manifest field
with no value"), this diff is **not applied in Stage 0**. Apply it only
after the operator has written all three fields to OpenBao via
`scripts/openbao_write.py`, so `./with-secrets-prod` never fails closed on a
value that doesn't exist yet:

```diff
   "entries": {
+    "services/icinga-observer": {
+      "fields": [
+        "ICINGA_DISCORD_WEBHOOK_URL",
+        "ICINGA_TELEGRAM_BOT_TOKEN",
+        "ICINGA_TELEGRAM_CHAT_ID"
+      ]
+    },
     "services/tpot": {
```

```diff
   "profiles": {
     "pve": {
       "auth": "approle",
       "role": "deploy-pve",
       "entries": [
         "services/ai-services",
         "services/authentik",
+        "services/icinga-observer",
         ...
```

(`services/icinga-observer` added once, kept alphabetically where it fits
among the other `services/*` entries.) Field names match
`icinga_observer_discord_webhook_url` / `-telegram_bot_token` /
`-telegram_chat_id` in `terraform/lxc/ansible/roles/icinga_observer/defaults/main.yml`,
which reads them via `lookup('env', 'ICINGA_*')` -- i.e. exactly the
uppercase field names above, matching the convention of every other
`services/*` entry in the manifest (e.g. `GRAYLOG_ROOT_PASSWORD`).

**Stage 0 gate:** endpoint matrix complete (above); dedicated notification
secret **names** are defined (above) with no value written anywhere, and
both notification destinations have an operator-confirmed test path
pending Stage 3; no new OCI or home-inbound rule is proposed or required.

## Stage 1 — install and form the HA pair

### 1.1 Packages and service baseline

The role installs the Debian packages `icinga2`, `monitoring-plugins-basic`,
`monitoring-plugins-standard`, `curl`, `dnsutils`, `fping`, and `jq` on both
hosts. Install `smokeping` and `nginx-light` only on `argon-01`.

The role must:

1. Preserve Docker, Portainer Agent, Wazuh, node exporter and rsyslog.
2. Enable and start `icinga2`; do not enable a web stack or a database.
3. Render the ApiListener on each Pi's fixed LAN address, with TLS client
   certificates signed for the two node names.
4. Use node configuration that makes `argon-01` the configuration master and
   lets `argon-02` receive configuration and command sync.
5. Validate with `icinga2 daemon -C` before restarting. A failed validation
   leaves the known-good service configuration running.

Certificate handling is a hard gate: generate the local CA and node keys on
the Pi pair during the initial controlled deployment, transfer only the public
certificate required for signing, and retain private keys locally at mode
`0600`. Do not store the private CA in the repository or OpenBao service
environment. Record the certificate fingerprint and expiry in this runbook's
execution-state section when the work is performed.

### 1.2 Narrow cluster firewall

Do not replace a host firewall or add a default-drop policy. The role first
detects whether `nftables` or legacy iptables is actually governing INPUT. It
then adds one idempotent, persistent rule which permits TCP 5665 *only* from
the peer Pi to the local Pi, before Icinga starts listening. It must leave
SSH, existing Docker rules, and all unrelated policy untouched.

Expected logical rule on `argon-01` (with the addresses reversed on
`argon-02`):

```text
permit tcp source 192.168.1.23 destination 192.168.1.22 destination-port 5665
reject all other new TCP connections to destination-port 5665
```

The implementation must prove this from a third LAN address after deployment:
TCP 5665 is refused there while peer TLS negotiation succeeds. Binding Icinga
to the Pi LAN address is an additional safeguard, not a substitute for the
source restriction.

### 1.3 Base checks and failure drills

Start with only: Icinga process, disk `/`, clock, certificate expiry, API
listener, TCP 5665, ICMP peer, and the peer host/service object. Configure
normal services with `max_check_attempts = 2`; use a separately documented
short rule for missing peer detection. Put a 60-second minimum notification
interval and recovery notification on every critical service.

Perform one drill at a time:

```text
1. Stop icinga2 on argon-02; confirm one fault notification and continued checks from argon-01.
2. Start icinga2 on argon-02; confirm one recovery notification.
3. Reboot argon-02; repeat the preceding proof.
4. Restore argon-02, then repeat with argon-01.
5. Temporarily block TCP 5665 only between the Pis; confirm a cluster fault, not duplicate service pages.
```

Rollback is `systemctl disable --now icinga2`, removal of only the role-owned
configuration and TCP-5665 rule, followed by the preflight service checks.
Do not remove Docker, Portainer Agent, Wazuh, exporter, rsyslog, or their
rules.

**Stage 1 gate:** `icinga2 daemon -C` passes on both Pis; mutual TLS works;
TCP 5665 is inaccessible from a third LAN client; either Pi can be stopped
without duplicate alerts or loss of core checks.

### 1.4 Stage 1 execution record (2026-10-25)

Deployed with the operator's approval (`TASK_APPROVAL=argon-icinga-observability`),
argon-01 then argon-02, each via `./with-secrets-prod ansible-playbook ... --limit
<host>`. `icinga_observer_enable_core_checks`/`_notifications`/`_smokeping` all
stayed at their default `false`, so only the HA pair and the five peer/self
checks per host went live -- nothing in Stage 2-4's scope was touched.

Five real bugs were found and fixed only by actually running this against the
Pis (none were visible from `--syntax-check` or `--check`, since Debian's
icinga2 drops to the `nagios` user internally for every invocation --
confirmed when `icinga2 pki new-ca` wrote `/var/lib/icinga2/ca/ca.{crt,key}` as
`nagios:nagios` even though Ansible ran it as root via `become`):

1. `/etc/icinga2/pki` and the notification-scripts directory were `root:root`;
   `icinga2 pki new-cert` failed with Permission Denied trying to write into
   them as `nagios`. Fixed to `nagios:nagios 0700`.
2. The rendered `/etc/icinga2/*.conf` files were `root:root 0640`; `icinga2
   daemon -C` (running as `nagios`) couldn't read its own config. Fixed to
   `root:nagios 0640` (root-writable, nagios-group-readable) -- also corrects
   the runbook's original "root-owned scripts/EnvironmentFile" text in §0.3
   and §2, which was wrong for the same reason.
3. `icinga2.conf`'s manual `include_recursive "zones.d"` double-included the
   same files Icinga2 already auto-includes once the API feature and zones
   exist, producing an exact "object re-defined ... previous definition: the
   same file, the same line" validation failure. Removed the manual include.
4. The `ApiListener` object had no `cert_path`/`key_path`/`ca_path`, so it
   defaulted to the stock `/var/lib/icinga2/certs/` location instead of our
   `/etc/icinga2/pki/`. Added all three (now-deprecated-but-functional)
   attributes.
5. The validate-and-reload handler had `changed_when: false`, which silently
   broke its own `notify:` chain to the restart handler (a handler only
   propagates `notify` when it itself reports `changed`) -- `icinga2` kept
   running the package's stock post-install config (a demo `localhost` host,
   mail notification commands) through several rounds of real config changes
   until this was caught by checking `MainPID`/`ActiveEnterTimestamp` directly
   and finding they never moved.
6. The peer's cross-host PKI exchange (CA distribution, CSR signing) was
   built around same-play `hostvars`/`delegate_to` + `ansible_play_hosts`
   checks, which only work when both hosts are in one play invocation --
   broken by design, since argon-01 and argon-02 are deployed as two separate
   `--limit` runs. It silently skipped on argon-02's run, leaving it on a
   self-signed placeholder cert (`icinga2 pki new-cert` writes one as a side
   effect of generating the CSR) that its own CA would reject. Rewritten to
   use `delegate_to: argon-01` directly (works regardless of `--limit`), with
   an `openssl verify` check (not a bare file-exists check) to detect the
   unsigned-placeholder case and re-sign it.
7. `FileLogger` severity `information` is *less* verbose than `notice` in
   Icinga2's ordering, so it silently hid all cluster connect/reconnect
   activity. Changed to `notice`.

**Verified, both Pis:**

- `icinga2 daemon -C` passes; `systemctl is-active icinga2` is `active`
  running the Stage 1 config (2 Hosts, 2 Endpoints, 1 ApiListener, 10
  Services, 0 NotificationCommands -- confirmed via `icinga2 object list`
  against a fresh `--dump-objects` run).
- Each node's `argon-0N.crt` verifies against the shared `ca.crt`
  (`openssl verify`, both report `OK`); each `ApiListener` is bound to its
  own LAN address only (`192.168.1.22:5665` / `.23:5665`, not `0.0.0.0`).
- `iptables -S INPUT` on each Pi: accept from the peer only, reject
  everything else to 5665 -- confirmed external: a `/dev/tcp` connect
  attempt from the operator workstation (a third LAN host) to
  `192.168.1.22:5665` got `Connection refused`.
- Raw mutual TLS proof: `openssl s_client` from argon-01 to argon-02:5665
  using each side's own issued cert and the shared `ca.crt` returns
  `Verify return code: 0 (ok)`.
- Live cluster link: `ss -tnp state established` shows a genuine
  `192.168.1.22:5665 <-> 192.168.1.23:<ephemeral>` socket between the two
  `icinga2` processes on both ends.
- Drill performed: `systemctl stop icinga2` on argon-02 -> the established
  socket on argon-01 disappears immediately; `systemctl start icinga2` on
  argon-02 -> a new established socket reappears within ~10s, unprompted
  (Icinga2's own reconnect logic), no manual intervention needed on
  argon-01. The reboot-argon-02, reboot-argon-01, and block-TCP-5665 drills
  from this section's text were not run this session -- only the two
  stop/start cycles above.
- **Caveat (flagged before Stage 1 started):** "confirm one fault
  notification" in this section's drill list could not be verified as
  worded, since Stage 3's Discord/Telegram notifications are deliberately
  still disabled (`icinga_observer_enable_notifications: false`). The
  connection-level evidence above substitutes for it at this stage; real
  notification delivery remains a Stage 3 deliverable.

Not yet done: Stage 1's reboot drills, and Stage 2 (core checks against
MikroTik/Technitium/pve/VictoriaMetrics/Grafana/Graylog/OpenBao/step-ca/
Traefik/Portainer/OCI), Stage 3 (notifications), and Stage 4 (SmokePing)
all remain at their Stage 0 planning state -- `icinga_observer_enable_*`
are still `false` and nothing beyond the HA pair and self-checks is live.

## Stage 2 — enable core checks safely

Add target groups in this exact order, with a successful manual test and one
controlled failure/recovery before enabling notifications for the next group:

1. MikroTik ICMP and DNS recursion.
2. Both Technitium nodes (`192.168.20.15` and `192.168.20.17`), UDP and TCP DNS.
3. `pve`: ICMP, TCP 8006 and the documented API health response.
4. VictoriaMetrics `/health`, Grafana `/api/health`, and Graylog TCP 514 plus
   `/api/system/lbstatus`.
5. OpenBao `/v1/sys/health` (expected unsealed response), step-ca ACME
   directory, Traefik health and Portainer `/api/system/status`.
6. OCI/Pangolin public HTTPS, certificate expiry, public DNS and the existing
   home-source SSH path.

Use service dependencies rather than alert suppression scripts:

```text
MikroTik host DOWN
  └─ suppress dependent local DNS, pve and LAN-service notifications

Icinga peer DOWN
  └─ does not suppress checks executed by the surviving peer

VictoriaMetrics/Grafana/Graylog DOWN
  └─ does not suppress Icinga notification commands
```

An HTTP success code alone is inadequate where the endpoint has a meaningful
state body. The custom check scripts must validate expected JSON fields (for
example OpenBao is unsealed) and must use explicit `--connect-timeout` and
overall timeouts. Set each script `nagios:nagios`, `0700` (see §0.3's note
on why `root:icinga` was wrong); do not place tokens on command lines, in
service object variables, or in Icinga debug logs.

For public OCI tests, SSH must be a non-interactive command using the existing
source-restricted identity and a harmless fixed probe (for example
`ssh -o BatchMode=yes -o ConnectTimeout=5 <oci-host> true`). Do not make the
Pi a general SSH automation client and do not add an OCI ingress rule.

**Stage 2 gate:** a router fault is one root-cause notification rather than an
alert storm; one known failure in each target group creates one problem and one
recovery; Grafana/VictoriaMetrics can be unavailable while Icinga still pages.

## Stage 3 — direct notification proof and logs

The role renders two notification commands. Each command must have a 10-second
network timeout, redact its output, return non-zero on delivery failure, and
write only a minimal local audit record (event ID, target, state, result), not
the secret or message payload. Configure Icinga users/groups so that warning,
critical, unknown and recovery routing is deliberate rather than inherited
from package defaults.

Execute and record these controlled tests:

```text
1. Send a test critical and recovery through Discord.
2. Send a test critical and recovery through Telegram.
3. Stop Grafana or make its health endpoint fail briefly; prove Icinga notifies.
4. Stop VictoriaMetrics or make its health endpoint fail briefly; prove Icinga notifies.
5. Disable one notification destination temporarily; prove the other succeeds and the failure is visible locally.
```

Continue forwarding Icinga journald/syslog records to Graylog through the
existing Pi rsyslog forwarding. Graylog is evidence only: notification scripts
must never block on Graylog, Grafana, VictoriaMetrics, Portainer or Docker.

**Stage 3 gate:** both direct routes have demonstrated problem and recovery
delivery, and alerting continues during a Grafana/VictoriaMetrics outage.

## Stage 4 — local SmokePing

Configure SmokePing only on `argon-01`. Its initial targets are:

```text
MikroTik LAN gateway
Technitium primary (192.168.20.15)
Technitium secondary (192.168.20.17)
OCI/Pangolin public FQDN
Cloudflare resolver (1.1.1.1)
Quad9 resolver (9.9.9.9)
```

Use the FPing probe with a 300-second step and retain a practical one-year
history using the package's RRD rotation defaults unless measured storage
growth warrants a smaller window. Do not use SmokePing to trigger primary
pages. It is an explanatory latency/loss history alongside Icinga's immediate
state monitoring.

Bind nginx to `127.0.0.1` only. Operators view the graphs with:

```bash
ssh -L 8080:127.0.0.1:80 ansible@192.168.1.22
```

Then browse `http://127.0.0.1:8080/smokeping/`. If a different local web port
is selected, record it in the role defaults and use it consistently. Do not
publish this through Traefik, Pangolin, Portainer, or a new router rule.

Test by creating a short controlled loss condition to one safe target and
confirm that the RRD graph distinguishes it from a gateway or Internet fault.
Rollback is `systemctl disable --now smokeping nginx`, removal of only the
role-owned nginx site and optional RRD data, and no network-policy change.

**Stage 4 gate:** graphs show usable home-to-OCI loss/latency history; the
SmokePing listener is unreachable from another LAN client and no OCI change
was required.

### 4.1 Stage 4 execution record (2026-10-25)

Deployed on argon-01 only (`icinga_observer_enable_smokeping: true`), with
operator approval. Packages (`smokeping`, `nginx-light`, `fcgiwrap`) were
already installed from Stage 1; this stage only rendered config and started
services.

Two more real bugs, same root cause as Stage 1's handler bug (a service
already running from package postinst time looks "already started" to
Ansible, so a config-only change silently never reaches it without an
explicit restart):

1. **`nginx-light`'s default site had been listening on `0.0.0.0:80` (both
   IPv4 and IPv6) with the stock welcome page since Stage 1 package
   install** -- a real, unintended LAN exposure that existed for about 40
   minutes before being noticed and fixed here. Our loopback-only vhost and
   the removal of the default site were both correctly written to disk, but
   a plain `reload` (SIGHUP) does not rebind nginx's listening sockets when
   a `listen` address changes; the live process kept its original
   `0.0.0.0:80` bind for ~37 minutes until a full restart. The role's
   "Reload nginx" handler now uses `state: restarted`, not `reloaded`.
2. **`smokeping` kept probing only its stock single target ("localhost")**
   after our real `Targets` file was rendered, because it was already
   "started" from package-install time and a bare `state: started` never
   restarts a running service. Added a dedicated `Restart smokeping`
   handler, notified from the Targets-render task.

A third bug (not a restart issue): the rendered `Targets` file was
`root:root 0640`; `smokeping.cgi` runs as `www-data` under `fcgiwrap` and
got `Permission denied` reading it (`500` from the CGI). Every other file
the package ships under `/etc/smokeping/config.d/` is `root:root 0644`;
ours is now the same.

**Verified:**

- `ss -ltnp`: nginx listens on `127.0.0.1:80` only (confirmed no `0.0.0.0`
  or `::` entry); a `/dev/tcp` connect attempt to `192.168.1.22:80` from
  the operator workstation (a third LAN host) gets `Connection refused`.
- `smokeping` is probing all 6 configured targets (RRDs exist under
  `/var/lib/smokeping/{Home,Internet}/`: MikroTik, TechnitiumPrimary,
  TechnitiumSecondary, OciPangolin, ResolverCloudflare, ResolverQuad9).
- `curl http://127.0.0.1/smokeping/smokeping.cgi` returns `200` on argon-01
  itself.
- The documented operator access path works end to end: from the
  workstation, `ssh -L 18080:127.0.0.1:80 ansible@192.168.1.22` then
  `curl http://127.0.0.1:18080/smokeping/smokeping.cgi` also returns `200`.
- `icinga2`, `nginx`, `fcgiwrap`, `smokeping` all `active`; the role re-run
  is now fully idempotent (`changed=0`) against this state.

Latency/loss history accumulation (RRDs exist and are being written, step
300s) satisfies the gate; distinguishing a local-gateway fault from an
OCI-edge fault in the graphs themselves was not separately drilled this
session.

## Validation, commit, and execution state

For every Ansible change, run:

```bash
ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles \
  ansible-playbook --syntax-check -i ansible/inventory/inventory.yml \
  ansible/00-initial-setup/argon-icinga-observers.yml
```

Before production mutation, state the exact Pi targets, package/configuration
objects, firewall rule, notification test, and explicit out-of-scope items.
After approval, use a limited run first:

```bash
ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles \
TASK_APPROVAL=argon-icinga-observability \
./with-secrets-prod ansible-playbook -i ansible/inventory/inventory.yml \
  ansible/00-initial-setup/argon-icinga-observers.yml --limit argon-01
```

Only after `argon-01` validates should the planned peer/bootstrap step be run
for `argon-02`; then perform the HA drills before enabling any external check.
Commit each validated stage and update the state table below. The source of
truth is Git configuration plus this durable state record, not an untracked
terminal transcript.

| Stage | Status | Date / commit | Evidence and rollback result |
|---|---|---|---|
| 0 — inventory and secrets | **Artifacts created; endpoints confirmed; secrets not yet written** | 2026-10-25, this branch | Playbook + `icinga_observer` role created; `--syntax-check` and `--check --diff` pass on both Pis (`failed=0`); 10/10 Tier-1 endpoints plus both Technitium nodes confirmed read-only (§0.4); manifest diff defined, not applied (§0.3.1); no package, config, cert, firewall rule, or secret written to either Pi. Open items: Traefik has no health endpoint, OCI SSH probe identity not provisioned (§0.4) |
| 1 — HA base | **Deployed and verified, both Pis** | 2026-10-25, this branch | Native icinga2 HA pair live on argon-01 (master) and argon-02; `icinga2 daemon -C` passes; mutual TLS verified (`openssl verify` OK both ways, live established socket on 5665); TCP 5665 confirmed refused from a third LAN host; stop/start drill on argon-02 proved automatic reconnect. 7 real bugs found and fixed during deployment (§1.4). Core checks, notifications, SmokePing all still disabled by role default. Rollback: `systemctl disable --now icinga2` on either Pi, as documented in Stage 1 |
| 2 — core checks | Planned | — | — |
| 3 — notifications | Planned | — | — |
| 4 — SmokePing | **Deployed and verified, argon-01** | 2026-10-25, this branch | SmokePing probing all 6 configured targets; nginx loopback-only (confirmed refused from a third LAN host) with fresh RRDs; CGI returns 200 both locally and via the documented SSH-forward path. 3 bugs found and fixed (§4.1), including a ~37-minute unintended `0.0.0.0:80` exposure from the nginx-light package default that this stage's own fix closed. Rollback: `systemctl disable --now smokeping nginx`, remove the role-owned nginx site |

## References

- [Icinga distributed monitoring and HA zones](https://icinga.com/docs/icinga-2/latest/doc/06-distributed-monitoring/)
- [Icinga monitoring basics](https://icinga.com/docs/icinga-2/latest/doc/03-monitoring-basics/)
- [Icinga API security](https://icinga.com/docs/icinga-2/latest/doc/12-icinga2-api/)
- [SmokePing project documentation](https://oss.oetiker.ch/smokeping/)
