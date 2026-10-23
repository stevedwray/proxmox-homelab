# Telegram bot setup runbook

One-time setup of the emergency-tier bot. Part 1 happens in the Telegram app;
Part 2 is `scripts/telegram_setup.py`. The bot token never goes in git, chat
or a file other than the `oci` repo's `.env`.

## Part 1: create the bot (Telegram app)

1. Open a chat with **@BotFather** (check the blue verified tick) and send
   `/newbot`.
2. Display name, for example `Gibbs Greatly Lab Alerts`.
3. Username: must end in `bot` and be unique, for example `gibbs_lab_alerts_bot`.
4. BotFather replies with a token like `123456789:AA...`. Treat it like a
   password. If it ever leaks, send `/revoke` to BotFather.
5. Send BotFather `/setjoingroups`, choose the bot, and pick **Disable** so
   nobody can add it to a group.
6. Open a chat with your new bot and press **Start**.

## Part 2: run the script

```bash
cd ~/git/proxmox-homelab
scripts/telegram_setup.py                  # writes ~/git/oci/.env
```

It prompts for the token (hidden) and checks it, waits for your Start message,
shows who messaged the bot and asks you to confirm it is you (anyone can find
and message a bot, so the chat id is never taken blindly), writes
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to the env file, and sends a test
message. Existing lines in `.env` are kept.

It also sets the file to **mode 0600**. That `.env` was `0644` (readable by any
local user) and already holds the Cloudflare DNS token and the Pangolin master
key.

If it says the value does not look like a token, it tells you its length and
whether it has the colon, without printing it. A real token is about 46
characters: digits, a colon, then 35 characters.

## Afterwards

- The relay (Phase 3) reads these two values from the same `.env`, copied to
  the OCI host at mode 0600 like `CF_DNS_API_TOKEN`.
- The relay acts only on `TELEGRAM_CHAT_ID`. Messages from anyone else are
  ignored.
- To rotate the token: `/revoke` in BotFather, `/token` for a new one, and run
  the script again.
