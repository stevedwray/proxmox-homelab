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
must be root-owned (`0700`) and read their environment only from a root-owned
systemd `EnvironmentFile` (`0600`). Never expose the Icinga API outside the
two-Pi cluster merely to send a notification.

**Stage 0 gate:** endpoint matrix complete; dedicated notification secrets
exist; both notification destinations have an operator-confirmed test path;
and no new OCI or home-inbound rule is proposed.

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
overall timeouts. Set each script `root:icinga`, `0750`; do not place tokens
on command lines, in service object variables, or in Icinga debug logs.

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
| 0 — inventory and secrets | Planned | — | — |
| 1 — HA base | Planned | — | — |
| 2 — core checks | Planned | — | — |
| 3 — notifications | Planned | — | — |
| 4 — SmokePing | Planned | — | — |

## References

- [Icinga distributed monitoring and HA zones](https://icinga.com/docs/icinga-2/latest/doc/06-distributed-monitoring/)
- [Icinga monitoring basics](https://icinga.com/docs/icinga-2/latest/doc/03-monitoring-basics/)
- [Icinga API security](https://icinga.com/docs/icinga-2/latest/doc/12-icinga2-api/)
- [SmokePing project documentation](https://oss.oetiker.ch/smokeping/)
