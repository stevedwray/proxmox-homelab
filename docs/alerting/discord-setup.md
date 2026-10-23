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
5. Invite the bot: OAuth2, URL Generator, scope `bot` only, permissions
   **Manage Channels** and **Manage Webhooks** only. Open the URL and add it
   to the lab server.

The application ID is only needed to build that invite URL. The public key
is for Discord's interactions endpoint and isn't used here. Neither is a
secret, but the **bot token is**: it never goes in git, chat or a file.

## Part 2: run the script

```bash
export DISCORD_BOT_TOKEN=...          # this shell only
export DISCORD_GUILD_ID=...           # Server Settings, Widget, or right-click the server with Developer Mode on
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
export LAB_IP_OPENBAO=192.168.20.16
scripts/discord_bootstrap.py --dry-run     # authenticates, reports what it would create
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
