# Discord setup runbook

One-time setup of the lab's alert channels. Everything that has no API is
manual (Part 1); the rest is `scripts/discord_bootstrap.py` (Part 2).

## Part 1: manual (Discord UI)

1. Turn on 2FA for your Discord account.
2. Create a new private server used only for the lab. Its privacy comes from
   being invite-only with just you in it, so the script sets no per-channel
   permissions. Delete or disable any invite links.
3. Server settings: enable the option that requires 2FA for moderator
   actions.
4. Developer Portal, New Application, Bot tab:
   - untick **Public Bot**;
   - leave every **privileged intent off**;
   - **Reset Token** and copy it (shown once).
5. Invite the bot. Either:
   - **Developer Portal route (safest):** your application, OAuth2, URL
     Generator. Tick scope `bot`; in the permissions list that appears tick
     only **Manage Channels** and **Manage Webhooks**; copy the generated URL
     at the bottom; or
   - **Build the URL yourself** from the Application ID (General Information):
     `https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot&permissions=536870928`
     (536870928 is Manage Channels, 16, plus Manage Webhooks, 536870912).

   Open the URL in a browser logged in to your Discord account, choose the
   lab server in the drop-down, and Authorize. If the server isn't in the
   list, you aren't its owner or lack Manage Server. If Discord says the bot
   is private or needs a code grant, check in the Bot tab that **Requires
   OAuth2 Code Grant** is off. (Public Bot being off is fine: you own the
   app, so you can still add it.)
   To check it worked, the bot shows in the server's member list with a BOT
   tag (it appears offline; that's normal for a bot that never connects), and
   under Server Settings, Integrations. The script's `--dry-run` also fails
   with a clear message if the bot isn't there.

   Getting `DISCORD_GUILD_ID`: User Settings, Advanced, enable **Developer
   Mode**; then right-click the server icon and **Copy Server ID**.

The application ID is only needed to build that invite URL. The public key
is for Discord's interactions endpoint and isn't used here. Neither is a
secret, but the **bot token is**: it never goes in git, chat or a file.

## Part 2: run the script

```bash
export DISCORD_BOT_TOKEN=...          # this shell only
export DISCORD_GUILD_ID=...           # the server ID (Copy Server ID, see Part 1)
cd ~/git/proxmox-homelab
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"   # opens a browser: Authentik, group homelab-admins
export LAB_IP_OPENBAO=192.168.20.16
scripts/discord_bootstrap.py --dry-run     # authenticates, reports what it would create (skip the bao login line for this one)
scripts/discord_bootstrap.py               # creates, stores in OpenBao, posts a test message
unset DISCORD_BOT_TOKEN BAO_TOKEN
```

It creates a `homelab-alerts` category with `#alerts-critical`,
`#alerts-warning`, `#security` and `#events`, one webhook each, and writes the
URLs to OpenBao `services/grafana` (`DISCORD_WEBHOOK_CRITICAL`, `_WARNING`,
`_SECURITY`, `_EVENTS`). Nothing secret is printed. It checks `BAO_TOKEN`
before creating anything, so a webhook URL is never created with nowhere to
go. Re-running reuses what exists; `--rotate` replaces the webhooks.

## Part 3: afterwards

- **Reset the bot token** in the Developer Portal. The bot then has no usable
  credential and nothing long-lived can manage your channels.
- Webhook URLs are credentials: anyone holding one can post to that channel
  (not read it). If one leaks, run the script with `--rotate`.
- Alert text leaves the lab for Discord's servers. Keep templates to
  hostnames, metric names and counts, and nothing that would identify the
  honeypot.
- Continue at Phase 1 step `alerting-03-manifest-fields` in
  [plan.md](plan.md).
