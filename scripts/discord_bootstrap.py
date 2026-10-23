#!/usr/bin/env python3
"""Create the homelab alert channels and webhooks in Discord, store the URLs in OpenBao.

One-shot, run by the operator (agents never see the bot token or the URLs):

  read -rs DISCORD_BOT_TOKEN; export DISCORD_BOT_TOKEN   # paste it; not echoed, not in history
  export DISCORD_GUILD_ID=...    # the private lab server
  export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
  export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"   # opens a browser
  LAB_IP_OPENBAO=192.168.20.16 scripts/discord_bootstrap.py --dry-run
  LAB_IP_OPENBAO=192.168.20.16 scripts/discord_bootstrap.py

It creates a "homelab-alerts" category with four text channels, one incoming
webhook per channel, and writes the four webhook URLs to OpenBao
(services/grafana: DISCORD_WEBHOOK_CRITICAL / _WARNING / _SECURITY / _EVENTS)
through scripts/openbao_write.py, so the URLs only ever travel over a pipe.
Neither the bot token nor a webhook URL is printed or logged.

Safe to re-run: existing categories, channels and webhooks are reused.
  --rotate    delete and recreate the webhooks (new URLs; use after a leak)
  --dry-run   authenticate and report what would change; create nothing
  --no-test   skip the test message posted to each channel

The bot needs only Manage Channels and Manage Webhooks. Reset its token in the
Developer Portal when this has finished.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/stevedwray/proxmox-homelab, 1)"
CATEGORY = "homelab-alerts"
OPENBAO_ENTRY = "services/grafana"
WRITER = Path(__file__).resolve().parent / "openbao_write.py"

GUILD_TEXT, GUILD_CATEGORY = 0, 4

# (channel name, OpenBao field, topic). The order is the order the fields are written.
CHANNELS = [
    ("alerts-critical", "DISCORD_WEBHOOK_CRITICAL", "Pages: copy of everything sent to Telegram"),
    ("alerts-warning", "DISCORD_WEBHOOK_WARNING", "Warnings that need a look but not tonight"),
    ("security", "DISCORD_WEBHOOK_SECURITY", "Wazuh, GVM, Graylog and Harbor findings"),
    ("events", "DISCORD_WEBHOOK_EVENTS", "Informational: Proxmox, PBS, Harbor"),
]

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


class DiscordError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def clean_token(raw: str) -> str:
    """Strip whitespace, surrounding quotes and a pasted 'Bot ' prefix."""
    token = raw.strip().strip("\"'").strip()
    return token.removeprefix("Bot ").strip()


def diagnose_token(token: str) -> str:
    """Explain a rejected token without revealing it.

    A bot token is three dot-separated parts and the first is the base64 of the
    bot's user ID (equal to the Application ID), which is not secret. Parts two
    and three are never shown.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return (f"The value has {len(parts)} dot-separated part(s) and is {len(token)} characters long; "
                "a bot token has 3 parts and is about 70 characters. It is probably the Client Secret, "
                "Public Key or Application ID. Use Bot tab, Reset Token, and copy that.")
    try:
        bot_id = base64.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError):
        return "The first part is not valid base64, so this is not a bot token. Copy it again from Bot tab, Reset Token."
    return (f"This token belongs to bot/application ID {bot_id}. Compare that with the Application ID in "
            "General Information. If it matches, the token was reset or revoked since you copied it: "
            "Reset Token again and use the new one. If it differs, it is a token from another application.")


def urllib_transport(method: str, url: str, headers: dict[str, str], data: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class Client:
    def __init__(self, token: str, transport: Transport = urllib_transport,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._token = token
        self._transport = transport
        self._sleep = sleep

    def request(self, method: str, path: str, body: object | None = None, *, auth: bool = True):
        """Call the API (or an absolute webhook URL); retry on 429; return parsed JSON or None."""
        url = path if path.startswith("https://") else f"{API}{path}"
        headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bot {self._token}"
        data = json.dumps(body).encode() if body is not None else None
        for _ in range(6):
            status, raw = self._transport(method, url, headers, data)
            parsed = json.loads(raw) if raw else None
            if status == 429:
                self._sleep(float((parsed or {}).get("retry_after", 1)) + 0.1)
                continue
            if status >= 400:
                detail = parsed.get("message", "") if isinstance(parsed, dict) else ""
                raise DiscordError(
                    f"{method} {path.split('?')[0] if auth else 'webhook'} -> HTTP {status} {detail}".strip(), status)
            return parsed
        raise DiscordError(f"{method} {path if auth else 'webhook'} -> still rate limited after retries", 429)


def ensure_channels(client: Client, guild_id: str, dry_run: bool) -> dict[str, str]:
    """Return {channel name: channel id}, creating the category and channels as needed."""
    existing = client.request("GET", f"/guilds/{guild_id}/channels")
    category = next((c for c in existing if c["type"] == GUILD_CATEGORY and c["name"] == CATEGORY), None)
    if category is None:
        print(f"  {'would create' if dry_run else 'creating'} category {CATEGORY}")
        category = {"id": "(dry-run)"} if dry_run else client.request(
            "POST", f"/guilds/{guild_id}/channels", {"name": CATEGORY, "type": GUILD_CATEGORY})
    ids: dict[str, str] = {}
    for name, _field, topic in CHANNELS:
        found = next((c for c in existing if c["type"] == GUILD_TEXT and c["name"] == name
                      and c.get("parent_id") == category["id"]), None)
        if found is None:
            print(f"  {'would create' if dry_run else 'creating'} channel #{name}")
            found = {"id": "(dry-run)"} if dry_run else client.request(
                "POST", f"/guilds/{guild_id}/channels",
                {"name": name, "type": GUILD_TEXT, "parent_id": category["id"], "topic": topic})
        else:
            print(f"  channel #{name} exists")
        ids[name] = found["id"]
    return ids


def ensure_webhook(client: Client, channel_id: str, name: str, rotate: bool, dry_run: bool) -> str | None:
    """Return the webhook URL, or None in a dry run. Never prints the URL."""
    hook_name = f"homelab-alerts-{name}"
    hooks = [] if channel_id == "(dry-run)" else client.request("GET", f"/channels/{channel_id}/webhooks")
    ours = [h for h in hooks if h.get("name") == hook_name]
    if ours and not rotate and ours[0].get("token"):
        print(f"  webhook for #{name} exists; reusing")
        return f"https://discord.com/api/webhooks/{ours[0]['id']}/{ours[0]['token']}"
    if dry_run:
        print(f"  would {'rotate' if ours else 'create'} webhook for #{name}")
        return None
    for hook in ours:
        print(f"  deleting old webhook for #{name}")
        client.request("DELETE", f"/webhooks/{hook['id']}")
    print(f"  creating webhook for #{name}")
    made = client.request("POST", f"/channels/{channel_id}/webhooks", {"name": hook_name})
    return f"https://discord.com/api/webhooks/{made['id']}/{made['token']}"


def write_openbao(entry: str, fields: list[str], values: list[str], env: Mapping[str, str]) -> int:
    """Hand the values to openbao_write.py on stdin, one per line."""
    proc = subprocess.run([sys.executable, str(WRITER), entry, *fields],
                          input="\n".join(values) + "\n", text=True, env=dict(env), check=False)
    return proc.returncode


def main(argv: list[str], env: Mapping[str, str] = os.environ, transport: Transport = urllib_transport,
         writer: Callable[[str, list[str], list[str], Mapping[str, str]], int] = write_openbao,
         sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rotate", action="store_true")
    parser.add_argument("--no-test", action="store_true")
    args = parser.parse_args(argv)

    token, guild_id = clean_token(env.get("DISCORD_BOT_TOKEN", "")), env.get("DISCORD_GUILD_ID", "").strip()
    if not token or not guild_id:
        print("ERROR: set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID in this shell.", file=sys.stderr)
        return 2
    if not args.dry_run and not (env.get("BAO_TOKEN", "").strip() and env.get("LAB_IP_OPENBAO", "").strip()):
        print("ERROR: BAO_TOKEN and LAB_IP_OPENBAO must be set before anything is created, "
              "or the webhook URLs would have nowhere to go.", file=sys.stderr)
        return 2

    client = Client(token, transport, sleep)
    try:
        me = client.request("GET", "/users/@me")
        guild = client.request("GET", f"/guilds/{guild_id}")
        print(f"Authenticated as bot '{me['username']}' in server '{guild['name']}'"
              f"{' (dry run)' if args.dry_run else ''}")
        channel_ids = ensure_channels(client, guild_id, args.dry_run)
        urls = [ensure_webhook(client, channel_ids[name], name, args.rotate, args.dry_run)
                for name, _field, _topic in CHANNELS]
    except DiscordError as exc:
        if exc.status == 401:
            print(f"ERROR: {exc}\nDiscord rejected the bot token (this is not an invite problem). "
                  f"{diagnose_token(token)}", file=sys.stderr)
        else:
            print(f"ERROR: {exc}\nIs the bot invited to the server with Manage Channels and Manage Webhooks, "
                  "and is DISCORD_GUILD_ID the server ID?", file=sys.stderr)
        return 1
    if args.dry_run:
        print("Dry run complete; nothing was created.")
        return 0

    code = writer(OPENBAO_ENTRY, [field for _n, field, _t in CHANNELS], urls, env)
    if code != 0:
        print("ERROR: OpenBao write failed (exit %d). The webhooks now exist but their URLs were not stored; "
              "re-run with --rotate to replace them." % code, file=sys.stderr)
        return 1
    if not args.no_test:
        for (name, _field, _topic), url in zip(CHANNELS, urls, strict=True):
            client.request("POST", url, {"content": f"#{name} is wired up (test message from discord_bootstrap.py).",
                                         "allowed_mentions": {"parse": []}}, auth=False)
            print(f"  test message sent to #{name}")
    print("Done. Now reset the bot token in the Developer Portal (Bot, Reset Token).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
