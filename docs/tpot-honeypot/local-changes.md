# Local changes to the live T-Pot install (drift from stock 24.04.1)

The Pi's `~/tpotce` checkout is hand-installed and not managed by this repo.
These are the deliberate local modifications, so an `update.sh`, reinstall or
redeploy knows what to re-apply. Everything lives in `~/tpotce/docker-compose.yml`
(uncommitted in that checkout) and `~/tpotce/local/` (untracked). Backups:
`docker-compose.yml.bak.20261015` (before the 2026-10-15 session).
T-Pot restarts itself daily (root cron `9 4 * * *` Europe/London:
`systemctl stop tpot.service`, prune, `shutdown -r`); `tpot.service` runs
`compose down -v` then `up`, so containers are recreated every day -- these
changes persist because they are in the compose file / bind-mounted files.

## Pre-existing (before 2026-10-15)

- `.env`: `.env.bak.20260930011420` is the pre-edit copy.
- `docker-compose.yml`: `profiles: [disabled]` on adbhoney, ciscoasa,
  conpot_ipmi, dicompot, medpot, fatt (still disabled). Cowrie and Dionaea
  were also disabled until 2026-10-15 (see below).

## 2026-10-15: made the honeypot a working LAN tripwire

Purpose: the honeypot detects someone who got onto the LAN. The stock setup
assumes internet-facing sensors and has three LAN-blind spots:

| # | Problem | Root cause | Fix |
|---|---|---|---|
| 1 | Elasticpot (9200) and IPPhoney (631) never logged LAN requests | Upstream (bontchev) default `blacklist = 127.0.0.1,192.168.0.0/16` silently drops events from 192.168.0.0/16; T-Pot's `honeypot.cfg` doesn't override it | `local/elasticpot/honeypot.cfg` and `local/ipphoney/honeypot.cfg` (copies of the image config plus `blacklist = 127.0.0.1`), bind-mounted `:ro` over `/opt/<sensor>/etc/honeypot.cfg` |
| 2 | Elasticpot events rejected by Elasticsearch (HTTP 400, never indexed) | Elasticpot writes `timestamp` like `2026-10-15T03:55:08.469570+00:00Z` (offset **and** `Z`): fails Logstash's ISO8601 date filter and ES's date mapping | `local/logstash/logstash.conf` (copy of the image's file; original kept as `logstash.conf.orig`) with `mutate { gsub => ["timestamp", "\+00:00Z$", "Z"] }` added at the top of the `ElasticPot` filter; bind-mounted `:ro` at `/etc/logstash/logstash.conf` |
| 3 | No sensor on SSH/telnet/SMB/FTP/MSSQL/MySQL/RPC | Cowrie and Dionaea were `profiles: [disabled]`; T-Pot's INPUT chain accepts those ports ahead of Honeytrap's NFQUEUE rule, so connections just got RST | Removed `profiles: disabled` from `cowrie` and `dionaea` |

Verified live from the Kali VM (192.168.1.114) 2026-10-15: Cowrie (22/23),
Dionaea (21/135/445/1433/3306 ...), Elasticpot (9200), IPPhoney (631 print job),
Honeytrap (unlisted ports), Mailoney, Heralding, Conpot, Miniprint, Redis,
SentryPeer, Tanner/Snare, Wordpot, H0neytr4p, Honeyaml all produced events in
T-Pot's ES with 0 Logstash rejections. Not exercised: Heralding 5900/VNC
handshake, 465/993/995/1080/5432.

Findings still open: `ip6`/UDP sensors not tested; Suricata stays very noisy
("Ethertype unknown" is ~99% of events -- filtered in the Grafana queries, see
`opensearch-grafana-plan.md`).

## Re-applying after an update/reinstall

1. Copy `local/` back (or regenerate: `docker cp <container>:/opt/<sensor>/etc/honeypot.cfg`
   then add `blacklist = 127.0.0.1`; `docker cp logstash:/etc/logstash/logstash.conf`
   then re-add the gsub line).
2. Re-add the three `volumes:` lines to `elasticpot`, `ipphoney` and `logstash`
   and remove the two `profiles: disabled` blocks.
3. `docker compose -f docker-compose.yml up -d --no-deps <service>` for each.
4. Re-test from a LAN host (see the commands in this file's section above)
   and check `docker logs logstash | grep "Could not index"` is empty.
