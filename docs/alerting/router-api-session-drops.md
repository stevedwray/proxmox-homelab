# Research brief: mktxp's RouterOS API-SSL session keeps ending

Status 2026-10-25: **open, root cause not found.** This brief is written so someone with no access to the lab can research it.
It lists every symptom, every measurement, what was ruled out, what was wrongly claimed and retracted, and the questions worth
answering. Parent docs: [README.md](README.md) (open item 1), [plan.md](plan.md) (Phase 0b).

## 1. One-paragraph summary

A Prometheus exporter, **mktxp 2.1.0**, holds one persistent **API-SSL (tcp/8729)** session to a **MikroTik hAP ax3 on RouterOS
7.25**. The session ends every 6 to 15 minutes. Each end makes one scrape fail, the exporter logs `[Errno 110] Operation timed out`,
and it reconnects. A second API session from another machine, using the same router and a full-access account, is not dropped on
the same schedule. A two-way packet capture of one death shows the router answering normally and **the exporter's host sending the
TCP RST**. That contradicts the exporter's own error message, and nobody has yet explained it.

## 2. Environment

| Part | Detail |
|---|---|
| Router | MikroTik hAP ax3 (`C53UiG+5HPaxD2HPaxD`, arm64, 1 GiB RAM), RouterOS **7.25** (upgraded 2026-10-24 morning; RouterBOARD firmware 7.19.6, upgrade to 7.25 offered, not applied) |
| Exporter | **mktxp 2.1.0**, image `ghcr.io/akpw/mktxp:2.1.0` (pulled via a Harbor proxy-cache), Python **3.14.8**, API library **RouterOS-api 0.21.0**, `prometheus_client` 0.26.0 |
| Exporter host | Docker container `mktxp` (compose service, `restart: unless-stopped`, no published port) inside an unprivileged Proxmox LXC `monitoring-stack`, 192.168.20.12, Linux 7.0.14-15-pve, Docker bridge network |
| Path | container → Docker bridge → LXC `eth0` → Proxmox bridge/VLAN 20 → router's VLAN-20 address **192.168.20.1** (the router is the L3 gateway; traffic is router-local, not forwarded) |
| Scraper | VictoriaMetrics scrapes `mktxp:49090` (`scrape_timeout: 30s`); sessions are logged in and out on the **minute :34** boundary, so the scrape period is probably 60 s (not re-verified) |
| Account | RouterOS user in a custom group `monitoring`: policies `read,api` only (no `write`, `reboot`, `sensitive`, `rest-api`, ...), login allowed from the monitoring host and the flat LAN (`address` list) |
| Service config | `/ip service api-ssl`: certificate `www-ssl-cert`, `tls-version=only-1.2`, `available-from` limited to the monitoring host and 192.168.1.0/24 |
| Router firewall | input-chain accept for 192.168.20.12 → tcp/8729 on `vlan20-mgmt`, placed ahead of the final "Drop all other unhandled input traffic" |
| TCP keep-alive (host) | `tcp_keepalive_time=7200`, `intvl=75`, `probes=9` (kernel defaults) |

### mktxp settings that matter (`mktxp.conf`, `_mktxp.conf`)

- `use_ssl = True`, `ssl_certificate_verify = False`, `no_ssl_certificate = False`, `plaintext_login = True`, `port = 8729`.
- `[MKTXP]`: **`persistent_router_connection_pool = True`**, `socket_timeout = 5`, `initial_delay_on_failure = 120`,
  `max_delay_on_failure = 900`, `delay_inc_div = 5`, `fetch_routers_in_parallel = False`, `minimal_collect_interval = 5`.
- Collectors on: system health, interface traffic, routerboard, `check_for_updates` (done from the exporter side). Everything else off.

## 3. Symptoms

1. **Session ends on a scrape.** The router logs `user mktxp logged out from 192.168.20.12 via api` on the same second as
   mktxp's error, always on a `:34` second.
2. **mktxp error sequence on each death** (container log):
   `Error getting system identity info ...: [Errno 110] Operation timed out`, then four lines
   `Error getting ... info ...: No network connection to router`, then `Connecting to router ...`, then
   `Connection to router ... has been established`. The first failing call is always `/system/identity`.
3. **Errno 110 arrives instantly.** It is logged within about a millisecond of the scrape starting, not after the configured 5 s
   socket timeout. A genuine ETIMEDOUT after retransmissions would take far longer.
4. **Metric gap.** Router metrics are missing for about 1 to 2 minutes around each death. This made the original "router has
   restarted" alert flap (`uptime < 3600` with gaps) and was fixed in the alert rules (PRs #536, #537).
5. **Session lifetimes are regular, not random** (all are whole minutes).

## 4. Measurements

### 4.1 Session lifetimes (router log, which is also forwarded to Graylog)

| Period | Lifetime of each mktxp session |
|---|---|
| 2026-10-24 16:47 to ~18:40 (after monitoring access was created) | **one session, 1 h 44 min** |
| Accidental router power cycle 2026-10-24 ~18:40 until the next reboot | **15.0 min, 49 times in a row** (to the second) |
| Deliberate reboot 2026-10-25 07:50, sessions after it | **8:00, 6:00, 8:00, 6:00** (07:52:34 to 08:00:34, 08:01:34 to 08:07:34, 08:08:34 to 08:16:34, 08:17:34 to 08:23:34) |
| Reconnect delay | next login exactly 60 s after each logout |

So the lifetime changed after each reboot (long, then 15, then an 8/6 alternation), and is always a multiple of 2 minutes.

### 4.2 Two-way capture of one death (2026-10-25 08:07:34, `tcpdump` on the container host's `eth0` and the Docker bridge)

Router = 192.168.20.1:8729, client = 192.168.20.12:57186. Times are seconds past 08:07:

```
:25.43  client ACK   (idle keep-alive-style ACK exchange, router answers)
:34.2859 client PSH 52 bytes   (request)
:34.2860 router ACK
:34.2860 client PSH 67 bytes   (second request, same scrape)
:34.2862 router ACK
:34.2878 router PSH 67 bytes   (the router's reply)
:34.2878 client ACK
:34.2895 client RST+ACK        <-- the CLIENT resets, 1.7 ms after the reply
```

- The router acknowledged every client segment immediately; no retransmissions, no zero window.
- Ping to 192.168.20.1 from the host ran every 0.5 s through the capture: **no gaps**.
- Both captures were taken on the client side of the router, so they show what the client received. They cannot show what the
  router does internally. They do show the **RST originates at the client**.
- The router's 67-byte reply is much smaller than a normal `/system/identity` reply would be if it carried data in the usual way
  over TLS; the content is encrypted and was not inspected. A TLS alert or an API `!fatal`/`!trap` reply of that size is plausible.
  This has not been decoded.

### 4.3 Control session

A session held open from the **workstation** (192.168.1.104, different VLAN, routed through the router) as the full-access
`api-user`, using `librouteros` and requesting `/system/resource` every 30 s: **still alive after the full 18 minutes (36 good requests, 07:58:38 to 08:16:38)**, while four mktxp sessions died in the same
window at 8, 6, 8 and 6 minutes. Run again for longer to be sure. Differences from mktxp: different library, different account/group, different source VLAN, 30 s cadence.

### 4.4 Kernel-level socket state

A sampler (`ss -tnoi`) on the exporter's host showed the mktxp socket carrying a TCP keep-alive timer. The exporter's container
shares the LXC's network namespace via the Docker bridge, so `ss` in the LXC does not show the container's own bridge-namespace
socket; the container's namespace must be inspected with `nsenter`.

## 5. What has been ruled out or weakened

| Idea | Why it is weak or ruled out |
|---|---|
| Router sends a FIN or RST after a fixed 15 min idle timer | **Retracted.** Came from a capture that saw only router→container packets, so it could not show who closed. Lifetimes are not fixed (15, 8, 6), and the 4.2 capture shows a client RST |
| Network path loss, NAT or conntrack timeout | Router-local traffic, no NAT; no ping gaps; acks flow normally in the capture |
| Router resource exhaustion | CPU 0 %, ~690 MB free of 1 GiB, uptime stable |
| A scheduler or script on the router | None exists; router config checked |
| Someone changing the router | The router's change log (kept in Graylog across reboots) shows no changes between the 16:47 access change and the power cycle |
| Account/permission problem | Login succeeds; read calls succeed until the death |
| TLS handshake failure | Handshake works every time; the old failure (no certificate on api-ssl) was fixed on 2026-10-24 |
| The web UI "SSL error" messages | Traced to port 443 (`www`, once a minute from 08:57 on 2026-10-24); unrelated to API-SSL on 8729. Client unknown, unrelated to this fault so far |

## 6. Open questions and hypotheses to research

Ordered by how well they fit the evidence.

1. **mktxp or RouterOS-api closes the socket itself after receiving an unexpected reply.** The 67-byte reply followed by an
   immediate client RST looks like an application-level abort (for example `SO_LINGER 0`, an exception path calling
   `socket.close()` with unread data, or a TLS alert handled badly). Questions: what does RouterOS-api 0.21.0 do on a `!fatal`,
   `!trap`, or a reply it cannot parse? Does mktxp's connection-pool health check or its `socket_timeout = 5` path wrap the
   exception as `Errno 110`? Does Python 3.14's `ssl` module treat something differently (for example `SSLWantReadError`,
   `unexpected_eof_while_reading`, TLS 1.2 close_notify, TLS session tickets)?
2. **The router closes the session at the application level and the client then resets.** RouterOS 7.25 could send `!fatal` with a
   reason (for example "session closed" or "too many sessions") before dropping, and mktxp reacts by resetting. This fits "router
   logs `logged out` on the same second" and the 67-byte reply. The `:34` alignment and the 2-minute multiples would then be a
   router-side counter checked at each request.
3. **A per-account, per-group or per-session limit in RouterOS.** The lifetime changed with each reboot. Is there an API-SSL
   session budget, certificate-handling quirk, or `monitoring`-group policy interaction (the group lacks `sensitive`, `rest-api`
   and others) that ends a session after N requests or N bytes? 15 min at 60 s is 15 scrapes; 8 min is 8; 6 min is 6.
   **Count requests per session** and compare with 4.1.
4. **A resource that wears out per session** on the router (memory, a file-descriptor or TLS-session cache) triggered by the
   specific calls mktxp makes (`/system/identity`, `/system/resource`, `/system/routerboard`, `/system/health`, `/interface`,
   update check) but not by `/system/resource` alone (the control session).
5. **Unprivileged-LXC / Docker network behaviour** closing idle-looking connections. Weak: the death happens mid-scrape with
   acks flowing, and other long-lived connections from the same host are fine.

## 7. Experiments that would separate the hypotheses

1. **Decode the dying exchange.** Capture inside the container's network namespace and either terminate TLS with a debugging
   proxy or set `SSLKEYLOGFILE` in the mktxp container to log TLS 1.2 secrets, then read the 67-byte reply in Wireshark. This
   directly tests hypotheses 1 and 2. (Do not publish the key log; it contains session secrets.)
2. **Run mktxp with `verbose_mode = True`** and read the stack trace around `Errno 110`.
3. **Count requests per session**, then see whether sessions end after a fixed number of requests (hypothesis 3).
4. **Replicate with a script** in the same container (RouterOS-api 0.21.0, the same account) issuing mktxp's exact call set
   every 60 s, then each call alone. Do the same with `librouteros` from the same host.
5. **Swap one variable at a time:** run the control script with the `monitoring` account; with the `api-user` account from the
   monitoring host; mktxp with `persistent_router_connection_pool = False` (new session each scrape, which sidesteps the fault
   and tells you whether the cost is only the login churn); `tls-version` left at default; Python version (an older mktxp image).
6. **Router-side:** `/log` with `topics=api,debug` enabled temporarily (the router forwards logs to Graylog) to see its view of
   each logout.
7. Search mktxp and RouterOS-api issue trackers, the MikroTik forum and RouterOS 7.20 to 7.25 changelogs for API session
   handling, `!fatal`, `Errno 110`, and "logged out" every few minutes.

## 8. Current mitigation

The alert rules tolerate the gaps: gauge queries use `last_over_time(...[5m])`, the restart rule uses
`last_over_time(mktxp_system_uptime[30m]) < 900` with `for: 2m`, and the "router metrics missing" rule uses
`absent_over_time(...[5m])`. Nothing pages because of this fault. The fault costs some metric resolution and about one error log
burst per death; it does not currently hide a router failure for longer than the 5-minute window.

## 9. Where the evidence lives

- Router log: Graylog (192.168.20.14) holds the forwarded router log and survives router reboots; the router's own memory log
  keeps 1000 lines.
- Container log: `docker logs mktxp` on 192.168.20.12 (timestamps in UTC; NZ time is UTC+13 in October).
- Configuration: `terraform/lxc/stacks/monitoring-stack/mktxp/{mktxp.conf,_mktxp.conf}`; router access change:
  `ansible/00-initial-setup/mikrotik-monitoring-access.yml`; compose service in
  `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`.
- Capture files from 2026-10-25 08:03 to 08:25 are in `/tmp/obs/` on 192.168.20.12 and are lost at reboot; copy them if they are
  needed for analysis.

## 10. Lessons already learned about this fault

- A capture that sees one direction cannot show who closed a connection.
- A number that repeats 49 times (15.0 min) looks like a law until the next session breaks it.
- Check the device's change history before blaming the device.
- An error message (`Errno 110`) does not prove the mechanism; compare it with the wire.
