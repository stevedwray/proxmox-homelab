# Discord silence bot: react to an alert to silence it

Status 2026-10-29: **built and tested, not deployed.** Needs the one-time setup below (Discord application, three OpenBao values).
Parent docs: [README.md](README.md), [plan.md](plan.md). Script: `terraform/lxc/ansible/files/discord_silence_bot.py`.
Playbook: `terraform/lxc/ansible/playbooks/deploy-discord-silence-bot.yml`.

## What it does

You react to a Grafana alert message in Discord. The bot silences that alert in Grafana and replies in the thread.

| Reaction | Silence length |
|---|---|
| 👍 | 4 hours |
| 🌙 | 12 hours |
| 📅 | 24 hours |

- If you add more than one, the longest wins.
- The bot adds ✅ to the message and replies "Silenced 1 alert(s) for 4h, until Thu 18:20 NZ: alertname=…,instance=…".
- On any failure it adds ❌ and says why. A ✅ or ❌ from the bot means "handled": it never acts on that message again.
- Removing the silence early: Grafana, Alerting, Silences, as before.

**Investigations:** the same bot also runs alert investigations with the local model: react 🔍 (pages are investigated
automatically). See [alert-investigator.md](alert-investigator.md). That needs the **Attach Files** permission as well
(invite permissions `101440` instead of `68672`).

## How it works

1. Every 30 seconds the bot lists the latest 50 messages in each alert channel (Discord REST API; no websocket, no libraries).
2. For a message that Grafana's webhook posted and someone reacted to, it asks Discord who reacted. Only **your user ID** counts.
3. It reads every `…/alerting/silence/new?…&matcher=name%3Dvalue…` link in the message (embed text included) and creates one Grafana
   silence per link with exactly those matchers. A grouped message with several alerts is silenced alert by alert.
4. Messages older than 24 hours, and anything not posted by a webhook, are ignored.

It is **off the alert path**: Grafana still sends every alert straight to Discord and Telegram. If the bot is down, reactions do nothing.

## Limits

- Discord only. Telegram pages still use the silence link (which needs the lab network or a VPN).
- Reacting to a "resolved" message gets a ❌ "no silence link" reply. That is expected.
- A reaction is picked up within about 30 seconds.
- It cannot silence by itself something Grafana did not link: only alerts whose message carries a silence link.

## Security

- The bot token is a secret. It sits in OpenBao `services/discord-silence-bot` and a 0600 file on the monitoring host.
- The bot gets **no Grafana admin password**. The play uses the admin login once to create a service account (`discord-silence-bot`,
  role Editor) and a token, stored 0600 at `/opt/discord-silence-bot/grafana-token`. Rotate by deleting the file and the account's
  token in Grafana, then re-running the play.
- Only reactions from `DISCORD_BOT_OWNER_ID` act. Anyone else's reaction is ignored.
- The container runs as `nobody`, read-only, all capabilities dropped, 128 MB limit, host network (to reach Grafana on 127.0.0.1:3000).

## One-time setup

**1. Discord (you, in the browser)**

1. https://discord.com/developers/applications, New Application, name it (for example `homelab-alerts`).
2. Bot tab: Reset Token and copy it (this is `DISCORD_BOT_TOKEN`; it is shown once).
3. Same tab, Privileged Gateway Intents: turn on **Message Content Intent**. Without it Discord hides the embeds the bot reads.
4. Invite it to your server with this link (replace `APP_ID` with the Application ID from General Information):
   `https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot&permissions=68672`
   That permission set is View Channel, Send Messages, Add Reactions, Read Message History.
5. Make sure the bot can see each alert channel (private channels need it added explicitly).
6. Discord, User Settings, Advanced: turn on Developer Mode. Right-click each alert channel, Copy Channel ID; right-click your own
   name, Copy User ID.
   Channels to include: `#alerts-critical`, `#alerts-warning`, `#security`, and the events/tripwire channels you want to silence from.

**2. OpenBao (you; agents never write secrets)**

```bash
BAO_TOKEN=<write token> scripts/openbao_write.py services/discord-silence-bot \
  DISCORD_BOT_TOKEN DISCORD_BOT_OWNER_ID DISCORD_BOT_CHANNEL_IDS
```

It prompts for each value: the token, your user ID (digits), and the channel IDs as one comma-separated list (digits only, no spaces).

**3. Manifest** (separate small PR, merged only after step 2, or every production deploy fails closed)

Add `services/discord-silence-bot` with those three fields to `secrets/manifest.json` and to the `pve` profile's entry list.

**4. Deploy** (hand-run playbook, so the Ansible paths must be set; run from a checkout of `stable`)

```bash
export ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ANSIBLE_ROLES_PATH=$PWD/terraform/lxc/ansible/roles
export TASK_APPROVAL=discord-silence-bot
./with-secrets-prod ansible-playbook -i <main checkout>/terraform/lxc/environments/pve/monitoring-stack/inventory.yml -u root \
  terraform/lxc/ansible/playbooks/deploy-discord-silence-bot.yml --check    # preview
./with-secrets-prod ansible-playbook ... same without --check               # apply
```

The play prints the bot's startup line, for example `bot 'homelab-alerts' watching 4 channel(s); reactions [...]; grafana healthy=True`.

**5. Prove it**

1. In Grafana, Alerting, Contact points, send a **Test** to the Discord warning contact point.
2. React 👍 to that message. Within about 30 seconds the bot adds ✅ and replies.
3. Grafana, Alerting, Silences shows a silence created by `discord-silence-bot`. Expire it.
4. If the reply says Grafana refused (403), the Editor role lacks silence rights in this Grafana version: change the service
   account to Admin in the playbook and re-run. If it says "silence link has no matchers", Grafana's link format differs from
   what the parser expects: send the bot's log line (`docker logs discord-silence-bot`) and the message text.

## Operations

- Logs: `docker logs discord-silence-bot` on the monitoring host (one line per silenced or failed message, and per poll failure).
- Restart: `docker restart discord-silence-bot`.
- Roll back: `docker compose -f /opt/discord-silence-bot/docker-compose.yml down`, and delete the service account in Grafana.
- Tests: `cd terraform/lxc/ansible/files && python3 -m unittest test_discord_silence_bot` (32 tests, no network; 13 cover investigations).
- Not monitored by itself on purpose: a dead bot only means reactions do nothing.
