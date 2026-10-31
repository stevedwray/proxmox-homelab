# Research brief: mktxp's RouterOS API-SSL session keeps ending

Status 2026-10-26: **cleared by restarting the exporter; root cause still not found.** The mechanism is narrowed to "the exporter closes its own socket" (4.5), and a restarted exporter has run 21 hours with no session death (4.6). This brief is written so someone with no access to the lab can research it.
It lists every symptom, every measurement, what was ruled out, what was wrongly claimed and retracted, and the questions worth
answering. Parent docs: [README.md](README.md) (open item 1), [plan.md](plan.md) (Phase 0b).

## 1. One-paragraph summary

A Prometheus exporter, **mktxp 2.1.0**, holds one persistent **API-SSL (tcp/8729)** session to a **MikroTik hAP ax3 on RouterOS
7.25**. After an accidental router power cycle the session started ending every 6 to 15 minutes. Each end makes one scrape
fail, the exporter logs `[Errno 110] Operation timed out`, and it reconnects. Packet captures show the **exporter** closing its
own socket within a millisecond of sending the first request of a scrape (FIN or RST from the client side, router replying
normally). A session held open from another machine on the same router was not affected. **Restarting the exporter container
cleared the fault**: the new process has held one session for 21+ hours (and 1260 consecutive metric samples). Why the old
process failed, and why Errno 110 appears on a socket that is working, is unexplained.

## 2. Environment

| Part | Detail |
|---|---|
| Router | MikroTik hAP ax3 (`C53UiG+5HPaxD2HPaxD`, arm64, 1 GiB RAM), RouterOS **7.25** (upgraded 2026-10-24 morning; RouterBOARD firmware 7.19.6, upgrade to 7.25 offered, not applied) |
| Exporter | **mktxp 2.1.0**, image `ghcr.io/akpw/mktxp:2.1.0` (pulled via a Harbor proxy-cache), Python **3.14.8**, API library **RouterOS-api 0.21.0**, `prometheus_client` 0.26.0 |
| Exporter host | Docker container `mktxp` (compose service, `restart: unless-stopped`, no published port) inside an unprivileged Proxmox LXC `monitoring-stack`, 192.168.20.12, Linux 7.0.14-15-pve, Docker bridge network |
| Path | container → Docker bridge → LXC `eth0` → Proxmox bridge/VLAN 20 → router's VLAN-20 address **192.168.20.1** (the router is the L3 gateway). The container is 172.20.0.6 on a Docker bridge, so its traffic is **source-NATted (masqueraded)** to 192.168.20.12 on the way out |
| Scraper | VictoriaMetrics scrapes `mktxp:49090` (`scrape_timeout: 30s`); sessions are logged in and out on the **minute :34** boundary, `scrape_interval: 60s`, one scraper only (confirmed) |
| Account | RouterOS user in a custom group `monitoring`: policies `read,api` only (no `write`, `reboot`, `sensitive`, `rest-api`, ...), login allowed from the monitoring host and the flat LAN (`address` list) |
| Service config | `/ip service api-ssl`: certificate `www-ssl-cert`, `tls-version=only-1.2`, `available-from` limited to the monitoring host and 192.168.1.0/24 |
| Router firewall | input-chain accept for 192.168.20.12 → tcp/8729 on `vlan20-mgmt`, placed ahead of the final "Drop all other unhandled input traffic" |
| TCP keep-alive | host defaults are 7200/75/9, but **RouterOS-api sets per-socket keep-alive of 10 s idle, 3 s interval, 5 probes** (verified in the installed `api_socket.py`), so the host defaults do not apply to this socket. OpenSSL 3.5.9 in the image; image digest `sha256:dfd7269dadfe8789e3c8386eedb7b056caa2c6ec243cd610caaf455274efeec5` |

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
5. **Session lifetimes are regular, not random** (all are whole minutes, because deaths are detected on a 60 s scrape).

## 4. Measurements

### 4.1 Session lifetimes (router log, which is also forwarded to Graylog)

| Period | Lifetime of each mktxp session |
|---|---|
| 2026-10-24 16:47 to ~18:40 (after monitoring access was created) | **one session, 1 h 44 min** |
| Accidental router power cycle 2026-10-24 ~18:40 until the next reboot | **15.0 min, 49 times in a row** (to the second) |
| Deliberate reboot 2026-10-25 07:50, sessions after it | **8:00, 6:00, 8:00, 6:00** (07:52:34 to 08:00:34, 08:01:34 to 08:07:34, 08:08:34 to 08:16:34, 08:17:34 to 08:23:34) |
| Reconnect delay | next login exactly 60 s after each logout |

So the lifetime changed after each reboot (long, then 15, then an 8/6 alternation). Earlier drafts said "always a multiple of 2 minutes"; that was wrong (15 is not).

### 4.2 Two-way capture of one death (2026-10-25 08:07:34, `tcpdump` on the container host's `eth0` and the Docker bridge)

Router = 192.168.20.1:8729, client = 192.168.20.12:57186. Times are seconds past 08:07:

```
:25.43  client ACK   (idle keep-alive-style ACK exchange, router answers)
:34.2859 client PSH 52 bytes   (request)
:34.2860 router ACK
:34.2860 client PSH 67 bytes   (second client data segment, same scrape)
:34.2862 router ACK
:34.2878 router PSH 67 bytes   (the router's reply)
:34.2878 client ACK
:34.2895 client RST+ACK        <-- the CLIENT resets, 1.7 ms after the reply
```

- The router acknowledged every client segment immediately; no retransmissions, no zero window.
- Ping to 192.168.20.1 from the host ran every 0.5 s through the capture: **no gaps**.
- Both captures were taken on the client side of the router, so they show what the client received. They cannot show what the
  router does internally. They do show the **RST originates at the client**.
- **The 67-byte reply is normal.** Every healthy scrape in the capture starts with the same client 52 + 67 bytes and the same
  67-byte router reply (the `/system/identity` exchange), then continues. TLS record headers (parsed from the pcap without
  decrypting) show the reply is one record of type 23 (application data), not a TLS alert (type 21). The sizes fit TLS 1.2
  AES-GCM exactly: the 52 bytes are one record, the 67 bytes are two records (37 + 30; the capture snaplen of 100 cut off the
  second header). So 52 + 67 is one ordinary command, not "request, then second request". Earlier drafts here wrongly treated
  67 bytes as a possible error.

### 4.3 Control session

A session held open from the **workstation** (192.168.1.104, different VLAN, routed through the router) as the full-access
`api-user`, using `librouteros` and requesting `/system/resource` every 30 s: **still alive after the full 18 minutes (36 good requests, 07:58:38 to 08:16:38)**, while mktxp sessions ended at 08:00:34, 08:07:34 and 08:16:34 inside that window (a fourth, 08:23:34, fell just after it). Run again for longer to be sure. Differences from mktxp: different library, different account/group, different source VLAN, 30 s cadence.

### 4.4 Kernel-level socket state

A sampler (`ss -tnoi`) on the exporter's host showed the mktxp socket carrying a TCP keep-alive timer. The exporter's container
shares the LXC's network namespace via the Docker bridge, so `ss` in the LXC does not show the container's own bridge-namespace
socket; the container's namespace must be inspected with `nsenter`.

### 4.5 The three deaths in the capture are not identical, but all are closed by the client

| Death (NZ time) | Session age | What the wire shows |
|---|---|---|
| 08:07:34 | 6 min | client sends the usual 52 + 67 bytes; the router sends its normal 67-byte reply and the client ACKs it; then the client sends **RST+ACK** 1.7 ms later |
| 08:16:34 | 8 min | client sends 52 + 67 bytes and, **in the same millisecond, FIN+ACK**; the router answers FIN+ACK; no reply data at all |
| 08:23:34 | 6 min | identical to 08:16:34 |

In each case the exporter closes the socket within a millisecond of writing the **first request of a scrape** (`/system/identity`),
without waiting for a normal reply. A FIN means close with nothing unread; the RST at 08:07:34 is what Linux sends on `close()`
when unread data (the reply that had just arrived) is still in the receive buffer. So the router did not drop these sessions: the
exporter's own `close()` ended them, and the router's "logged out" line is the consequence.

What the code says about who closes: in persistent-pool mode the only call to `disconnect()` is RouterOS-api's
`CloseConnectionExceptionHandler`, which runs when a socket error or `!fatal` is raised. So some exception is raised immediately
after the first write. The logged `[Errno 110]` would then be a real OSError(ETIMEDOUT) from the socket read. That is the
remaining puzzle: a kernel ETIMEDOUT on a socket that has just carried a write successfully and has recent keep-alive replies is
unexpected. mktxp's `identity_ds` prints only the message, not a traceback, and `verbose_mode` does not add one.

### 4.6 Result of the instrumented restart (2026-10-25 08:57 to 2026-10-26 06:27)

| Fact | Value |
|---|---|
| Change made | patched logging into the running container (backups `*.orig`): a diagnostic line on any socket send/recv error and a stack trace on every `close()`, plus a traceback in `identity_ds`; then `docker restart mktxp` |
| Session since restart | **one session, logged in 08:57:41, no logout in 21.5 h** (router log), still up at 06:27 next day |
| Diagnostic lines | **none**: no socket error, no `close()`, no identity error since the restart |
| Metric continuity | 1260 samples of `mktxp_system_uptime` in 21 h (one per minute, no gaps) |
| Router | uptime 22.6 h, no reboot; CPU 0 % |
| Before the restart | the same process had run about 16 h and produced sessions of 15 min (x49), then 8/6 min |

What this implies, and what it does not:

- The fault was **not in the router, the network path or the account**: none of those changed, and the same router now keeps
  the session. It lives in the old exporter process, or in the process's interaction with something that the restart reset.
- That process lasted 1 h 44 min on its first session (before the power cycle), then failed repeatedly after the router went away
  and came back. Candidate state: connection or TLS objects reused across reconnects, the failure-backoff counters, the update-check
  cache. mktxp's backoff resets on every successful connect, so those counters alone do not explain it.
- The 15.0-minute lifetimes equal mktxp's `max_delay_on_failure = 900` s. This may be a coincidence; it has not been explained.
- It is **not proven** that the restart (and not the logging patch or chance) cured it. The long-lived process had the fault for
  16 hours straight, so chance is unlikely, but a second occurrence is the real test.
- Only the original capture survives of a failing death: with the patched logging in place nothing has failed yet, so the
  exception chain was never captured.

## 5. What has been ruled out or weakened

| Idea | Why it is weak or ruled out |
|---|---|
| Router sends a FIN or RST after a fixed 15 min idle timer | **Retracted.** Came from a capture that saw only router→container packets, so it could not show who closed. Lifetimes are not fixed (15, 8, 6), and the full capture (4.5) shows the client closing first in all three deaths |
| Network path loss or a conntrack timeout | No ping gaps (note: pings come from the LXC, not the container's NAT path); acks flow normally in the capture. The container's traffic is masqueraded by Docker, so conntrack is not formally excluded |
| Router resource exhaustion | CPU 0 %, ~690 MB free of 1 GiB, uptime stable |
| A scheduler or script on the router | None exists; router config checked |
| Someone changing the router | The router's change log (kept in Graylog across reboots) shows no changes between the 16:47 access change and the power cycle |
| Account/permission problem | Login succeeds; read calls succeed until the death |
| TLS handshake failure | Handshake works every time; the old failure (no certificate on api-ssl) was fixed on 2026-10-24 |
| The web UI "SSL error" messages | Traced to port 443 (`www`, once a minute from 08:57 on 2026-10-24); unrelated to API-SSL on 8729. Client unknown, unrelated to this fault so far |

## 6. Open questions and hypotheses to research

Ordered by how well they fit the evidence.

0. **State that went bad inside the old exporter process after the router outage, cleared by a restart** (section 4.6). This is the
   leading explanation. It does not name the mechanism; hypotheses 1 and 2 are candidate mechanisms.

1. **A socket or TLS error is raised on the first read of a scrape and normal cleanup closes the socket.** Fits 4.5 and the
   code. The unknown is what raised it: the original exception chain is not logged. Needed: a traceback and a syscall trace.
2. **Concurrent use of one non-thread-safe API connection** (mktxp serves HTTP from 16 threads; RouterOS-api has an open issue
   about thread safety). Weak on its face: there is one scraper at 60 s intervals and a 5 s minimum collect interval. Check that
   nothing else (a manual `curl`, a second scrape job) calls `:49090`.
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

1. **Capture the original exception.** Add `traceback.print_exc()` to the handler in `mktxp/datasource/identity_ds.py` (verbose
   mode does not print one), and log class, errno, thread and file descriptor where RouterOS-api wraps the socket error.
2. **Correlate a syscall trace with a packet capture of one death**: `nsenter -t <container pid> -n tcpdump ...` plus
   `strace -ff -ttt -T -yy -e trace=network,read,write,close,poll` on the process. Does a `recv` return ETIMEDOUT before
   `close`? Do not poll `SO_ERROR` (reading it clears it). Optionally set `SSLKEYLOGFILE` before the container starts so the
   TLS stream can be decrypted (the log contains session secrets; do not share it).
3. **Count requests per session**, then see whether sessions end after a fixed number of requests (hypothesis 3).
4. **Replicate with a script** in the same container (RouterOS-api 0.21.0, the same account) issuing mktxp's exact call set
   every 60 s, then each call alone. Do the same with `librouteros` from the same host.
5. **Swap one variable at a time** (also try `http_server_threads = 1`): run the control script with the `monitoring` account; with the `api-user` account from the
   monitoring host; mktxp with `persistent_router_connection_pool = False` (new session each scrape, which sidesteps the fault
   and tells you whether the cost is only the login churn); `tls-version` left at default; Python version (an older mktxp image).
6. **Router-side:** `/log` with `topics=api,debug` enabled temporarily (the router forwards logs to Graylog) to see its view of
   each logout.
7. Search mktxp and RouterOS-api issue trackers, the MikroTik forum and RouterOS 7.20 to 7.25 changelogs for API session
   handling, `!fatal`, `Errno 110`, and "logged out" every few minutes.

## 8. Current mitigation

**Restarting the exporter** (`docker restart mktxp`) cleared the fault on 2026-10-25 and it has not returned in 21 hours. If it
returns, restart again and check whether the interval has changed; the instrumented build will then print the original exception.
The diagnostic patch is still in the running container (not in the repo or compose file) and disappears when the container is
recreated by a monitoring-stack deploy; that is acceptable.


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
- Capture files: 2026-10-25 08:03 to 08:25 (`/tmp/obs/`, the failing process) and 08:57 to 13:20 (`/tmp/obs2/ring.pcap0`, the healthy
  process, about 1.3 MB) on 192.168.20.12 (RAM-backed `/tmp`, lost at reboot). Both sets were copied to the session scratchpad;
  copy them somewhere durable if you need them.
- Independent source audit and test plan: `~/Downloads/mktxp-api-ssl-research-2026-10-25.md` (mktxp v2.1.0 and RouterOS-api
  0.21.0 at pinned commits). Its main points are folded into sections 4.2, 4.5, 6 and 7.

## 10. Lessons already learned about this fault

- A capture that sees one direction cannot show who closed a connection.
- A number that repeats 49 times (15.0 min) looks like a law until the next session breaks it.
- Check the device's change history before blaming the device.
- An error message (`Errno 110`) does not prove the mechanism; compare it with the wire.
