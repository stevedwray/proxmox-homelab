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

## 2026-10-23: web UI behind Traefik (docs/npm-retirement/)

`https://tpot.lab.gibbsgreatly.xyz` (Traefik + Authentik forwardAuth, app bound to the
operator group) replaces the NPM route `tpotce.gibbsgreatly.xyz`. Applied by
`ansible/00-initial-setup/tpot-web-behind-traefik.yml` (tags `tls`, `firewall`, `noauth`):

- **TLS**: step-ca cert (SANs `tpot.lab…`, `tpot.gibbsgreatly.xyz`, `192.168.1.28`) in
  `data/nginx/cert/nginx.{crt,key}`; stock files kept as `*.selfsigned`; renewal via
  `tpot-tls-renew.timer` (03:20 daily, renews under 15 days).
- **nginx override**: `local/nginx/tpotweb.conf` (bind-mounted read-only over
  `/etc/nginx/conf.d/tpotweb.conf`) = the stock file with every `auth_basic*` line removed
  **plus `allow 192.168.30.10;`** (Traefik). T-Pot's stock config is `satisfy any` +
  `allow 127.0.0.1/::1` + `deny all`, so removing basic auth alone 403s every path.
  Compose line added to the `nginx` service (timestamped backup kept next to it).
- **Firewall** (the only gate besides Authentik now): `DOCKER-USER` DROP tcp/64297 from
  anything but `192.168.30.10` on `eth0`, `ip6tables INPUT` DROP tcp/64297, applied by
  `tpot-ui-firewall.service`; `tpot.service.d/10-ui-firewall.conf` makes T-Pot
  `Requires=` it (fail closed).
- **After a T-Pot `update.sh`** (may reset `docker-compose.yml` and the cert dir): re-run
  the playbook tags `tls` then `noauth`. The firewall unit survives.
- Rollback: copy the `.selfsigned` files back and `docker exec nginx nginx -s reload`; restore the
  compose backup and `docker compose up -d --no-deps nginx`; remove the two firewall rules.
- Not yet confirmed: the first daily reboot (04:09 Europe/London) with this config (T7).

## Re-applying after an update/reinstall

1. Copy `local/` back (or regenerate: `docker cp <container>:/opt/<sensor>/etc/honeypot.cfg`
   then add `blacklist = 127.0.0.1`; `docker cp logstash:/etc/logstash/logstash.conf`
   then re-add the gsub line).
2. Re-add the three `volumes:` lines to `elasticpot`, `ipphoney` and `logstash`
   and remove the two `profiles: disabled` blocks.
3. `docker compose -f docker-compose.yml up -d --no-deps <service>` for each.
4. Re-test from a LAN host (see the commands in this file's section above)
   and check `docker logs logstash | grep "Could not index"` is empty.

## 2026-10-23: daily reboot PAUSED (resume when done)

Root's crontab entry `9 4 * * * ... shutdown -r +1 "T-Pot Daily Reboot"` is commented out
(no backup copy was kept; the `#` is the only change) so long SpiderFoot scans are not
killed at 04:09. While paused: containers are not recreated daily and the Docker
container/image/volume prune does not run. **Resume:**
`ssh tpot 'sudo crontab -l | sed "s/^#\(9 4 \* \* \* bash -c\)/\1/" | sudo crontab -'`.
