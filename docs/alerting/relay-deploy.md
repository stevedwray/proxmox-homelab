# Alert relay: deploy runbook (Phase 3a)

> **Superseded design (2026-10-24): do not follow this runbook yet.** The operator
> ruled out serving the relay on port 443 behind Pangolin's Traefik, and wants
> mutual TLS on a dedicated port, restricted to the home IP at the OCI firewall.
> The Traefik route and Cloudflare-record steps below have been removed from the
> `oci` working tree and will be rewritten once the design is settled (see the
> mTLS discussion in the plan). The secrets, drills and rollback sections still
> describe the right ideas.

The relay is a single standard-library Python service on the OCI box. It takes
alerts and heartbeats, pages Telegram with Ack and Snooze buttons, and mirrors
heartbeat alerts to Discord `#alerts-critical`. It lives in the **`~/git/oci`**
repo (`roles/alert_relay/`); this runbook is the operator side. The relay
source and its 39 tests are `roles/alert_relay/files/relay.py` and
`test_relay.py`.

Built and tested, **not yet deployed**. Phase 3b (pointing Grafana at it) and
Phase 4 (the lab pingers) come after this is proven.

## How the lab reaches the relay

Grafana (and later the pingers) make an **outbound HTTPS POST** to
`https://alerts.gibbsgreatly.xyz/v1/alerts`. Nothing connects into the lab and
the Newt tunnel is not involved.

```
Grafana / pinger (lab) -> MikroTik (normal internet egress) -> OCI public IP :443
   -> Gerbil/Traefik on the OCI box -> router "alert-relay" -> http://alert-relay:8080
```

Verified 2026-10-24 from the monitoring host, `pve` and `pve-tiny`: HTTPS to the
OCI edge returns 200 with a valid certificate, both through public DNS
(Cloudflare) and straight to the origin IP. The monitoring host also reaches
`discord.com` and `api.telegram.org`.

**DNS, which differs by resolver.** The MikroTik has static entries
(`/ip dns static`) sending `pangolin.gibbsgreatly.xyz` and
`oci.gibbsgreatly.xyz` to `192.9.191.163` directly, bypassing Cloudflare.
The monitoring host, `pve` and `pve-tiny` all resolve through the MikroTik. The
Technitium nodes are authoritative-looking for `gibbsgreatly.xyz` and return
NXDOMAIN for names they do not hold, so a LAN client using Technitium would not
see `alerts` until it is added there too. The servers that call the relay do
not use Technitium, so this only matters for testing from a LAN client.

Two ways to name the relay, both working:

| | Cloudflare record only | plus a MikroTik static entry (matches `pangolin`/`oci`) |
|---|---|---|
| Lab path | via Cloudflare's proxy | straight to the OCI IP, **Cloudflare not in the path** |
| Dependencies for the dead man's switch | Cloudflare, DNS, OCI | DNS, OCI |
| Outside the lab | works | works (the Cloudflare record is still there) |

The second is recommended: one fewer thing that can make the dead man's switch
fail. Without the static entry nothing breaks; the lab just takes the Cloudflare
route.

## Preflight

| | |
|---|---|
| Target | The OCI box (`ssh oci`): aarch64, 8 GB RAM, about 6.9 GB free. The relay is limited to 128 MB |
| Mutating | Yes: a new container, a new Traefik route, a **Pangolin restart** (its tunnels reconnect within seconds), a Cloudflare DNS record |
| Out of scope | Hardening, Pangolin config, anything in the lab |
| Reversible | Yes, see Rollback |

## 0. Commit the oci changes

Do not commit in `~/git/oci`: the Pangolin source is moving into this repo's `oci/` (`task/oci-security-prs-integration`, unmerged, see docs/oci-integration/plan.md). When that import merges, copy `roles/alert_relay/` into `oci/roles/`.
These files are new or changed:

```
roles/alert_relay/                      (new: files/relay.py, files/test_relay.py, tasks, defaults, handlers, templates)
roles/pangolin/templates/dynamic_config.yml.j2   (router + service for alerts.gibbsgreatly.xyz)
group_vars/pangolin.yml                 (alert_relay_domain)
site.yml                                (alert_relay role)
.env.template                           (new keys, alerts.gibbsgreatly.xyz in CF_RECORD_NAMES)
```

Run the tests any time: `cd ~/git/oci/roles/alert_relay/files && python3 -m unittest test_relay`.

## 1. Secrets

`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are already in `~/git/oci/.env`
(from `scripts/telegram_setup.py`). Add the other two.

**a. The ingest token** (the shared secret the lab uses to call the relay).
It goes in the OCI `.env` and in OpenBao, so Grafana and the pingers can send
it. Write OpenBao **before** the manifest field is added, or every production
wrapper fails closed.

```bash
cd ~/git/proxmox-homelab
export RELAY_INGEST_TOKEN="$(openssl rand -hex 32)"
printf 'RELAY_INGEST_TOKEN=%s\n' "$RELAY_INGEST_TOKEN" >> ~/git/oci/.env

export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"   # opens a browser
printf '%s\n' "$RELAY_INGEST_TOKEN" | LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py services/grafana RELAY_INGEST_TOKEN
unset RELAY_INGEST_TOKEN BAO_TOKEN
```

**b. A copy of the `#alerts-critical` webhook**, so the relay can reach Discord
even when the lab is down. The wrapper prints its banner on stderr, so only the
line is appended:

```bash
TASK_APPROVAL=alerting-relay-secrets ./with-secrets-prod bash -c \
  'printf "DISCORD_WEBHOOK_CRITICAL=%s\n" "$DISCORD_WEBHOOK_CRITICAL"' >> ~/git/oci/.env
```

**c. Check** (names only, never values) and keep the file private:

```bash
chmod 600 ~/git/oci/.env
grep -o '^[A-Z_]*' ~/git/oci/.env | sort
```

You should see `DISCORD_WEBHOOK_CRITICAL`, `RELAY_INGEST_TOKEN`,
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` among them.

Then tell me, and I will add `RELAY_INGEST_TOKEN` to the `services/grafana`
entry in `secrets/manifest.json` and read it back through the wrapper.

## 2. DNS

Create an **A record `alerts.gibbsgreatly.xyz`** in Cloudflare with the same
target as the existing `pangolin` / `oci` records, **proxied** (orange cloud),
like the others. The certificate is issued by Traefik through the existing
Cloudflare DNS challenge; nothing to do for it.

Alternatively, set `CF_ZONE_ID` and `CF_RECORD_NAMES` in the `oci` `.env` and run
`scripts/oci-edge-reconcile.sh`, which upserts every name in the list. (Your
current `.env` has neither, so the dashboard is the quick way.)

## 3. Deploy

```bash
cd ~/git/oci
ansible-playbook site.yml --skip-tags os_hardening --check --diff    # read what will change
ansible-playbook site.yml --skip-tags os_hardening
```

Expect, in the real run: the Traefik dynamic config changes (and Pangolin
restarts), the relay directory, program, settings and compose file are
created, the container starts, and the last task waits for it to report
`healthy`. Nothing else should change.

## 4. Prove it

```bash
export RELAY_INGEST_TOKEN="$(grep '^RELAY_INGEST_TOKEN=' ~/git/oci/.env | cut -d= -f2)"
URL=https://alerts.gibbsgreatly.xyz

curl -s $URL/healthz                                   # ok
curl -s -o /dev/null -w '%{http_code}\n' -X POST $URL/v1/alerts          # 401 (no token)
```

**Fire drill:** a critical alert, then each button.

```bash
curl -s -X POST $URL/v1/alerts -H "Authorization: Bearer $RELAY_INGEST_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"key":"drill-1","title":"Fire drill","summary":"Test alert from the runbook","severity":"critical","status":"firing"}'
```

Within about 15 seconds Telegram shows `CRITICAL / Fire drill` with
**Ack | Snooze 1h | 4h | 24h**. Then:

1. Press **Snooze 1h**: the message gains "Snoozed 1h" and keeps its buttons.
2. Send `/status`: it lists the drill as snoozed.
3. Press **Ack**: the message gains "Acknowledged" and loses its buttons.
4. Resolve it (same command with `"status":"resolved"`): Telegram says
   `RESOLVED: Fire drill`.

**Heartbeat drill** (also proves the Discord mirror):

```bash
curl -s -X POST $URL/v1/heartbeat/drill -H "Authorization: Bearer $RELAY_INGEST_TOKEN" \
  -H 'Content-Type: application/json' -d '{"components":{"grafana":false}}'
```

Expect `drill: grafana is not healthy` on Telegram **and** in Discord
`#alerts-critical`. Send the same with `true` to resolve it; both get a
`RESOLVED` line.

Also check: only you can use the buttons (a second Telegram account pressing
them does nothing), and `curl -s -H "Authorization: Bearer $RELAY_INGEST_TOKEN" $URL/metrics`
shows `relay_up 1`.

## `EXPECTED_HEARTBEATS` stays empty for now

The relay starts with no expected heartbeat senders, so it will not page
"no heartbeat from pve" before the Phase 4 pingers exist. When they are
running, set `alert_relay_expected_heartbeats: "pve,pve-tiny"` in the role
defaults and redeploy.

## Rollback

```bash
ssh oci 'cd /opt/alert-relay && sudo docker compose down'
```

Revert the oci commit and redeploy to remove the Traefik route; delete the
`alerts` DNS record. The `data/` directory holds only alert state.
