#!/usr/bin/env python3
"""React to a Grafana alert in Discord to silence it (docs/alerting/discord-silence-bot.md).

Polls the alert channels over Discord's REST API (no websocket, no third-party libraries). When the
owner reacts to a Grafana-sent message with a duration emoji, it reads the "silence" links in that
message, turns each into a Grafana silence for the chosen time, then marks the message with a check
mark and replies with what it did. It is off the alert path: if it is down, alerts still arrive.

Needs the bot's MESSAGE_CONTENT intent (Developer Portal toggle), or Discord hides the embeds it reads.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

DISCORD_API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/stevedwray/proxmox-homelab, 1)"  # Discord rejects generic agents
DEFAULT_DURATIONS = "\U0001F44D=4,\U0001F319=12,\U0001F4C5=24"  # thumbs up 4h, crescent moon 12h, calendar 24h
DONE, FAILED = "✅", "❌"  # bot's own marker reactions: check mark, cross mark
SILENCE_URL = re.compile(r"https?://[^\s)\]>\"']+/alerting/silence/new\?[^\s)\]>\"']+")
MATCHER = re.compile(r"^([^=!~]+)(=~|!~|!=|=)(.*)$", re.S)
SKIN_TONES = {chr(c) for c in range(0x1F3FB, 0x1F400)}
NZ = ZoneInfo("Pacific/Auckland")


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z {msg}", flush=True)


def normalize_emoji(name: str) -> str:
    """Drop skin-tone modifiers and variation selectors so a toned thumbs up still counts."""
    return "".join(ch for ch in name if ch not in SKIN_TONES and ch != "️")


def parse_durations(spec: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in spec.split(","):
        emoji, _, hours = part.strip().rpartition("=")
        if emoji and hours:
            out[normalize_emoji(emoji)] = float(hours)
    return out


def message_text(message: dict) -> str:
    """Everything in a message a silence link could hide in: content plus every embed text field."""
    parts = [message.get("content") or ""]
    for embed in message.get("embeds") or []:
        parts += [embed.get("title") or "", embed.get("description") or "", (embed.get("footer") or {}).get("text") or ""]
        parts += [f.get("value") or "" for f in embed.get("fields") or []]
    return html.unescape("\n".join(parts))


def extract_silence_urls(message: dict) -> list[str]:
    seen: list[str] = []
    for url in SILENCE_URL.findall(message_text(message)):
        if url not in seen:
            seen.append(url)
    return seen


def parse_matchers(url: str) -> list[dict]:
    """Grafana's silence link carries one `matcher=name<op>value` query parameter per label."""
    out = []
    for raw in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("matcher", []):
        found = MATCHER.match(raw)
        if not found:
            raise ValueError(f"unreadable matcher {raw!r}")
        name, op, value = found.groups()
        out.append({"name": name, "value": value, "isRegex": op in ("=~", "!~"), "isEqual": op in ("=", "=~")})
    if not out:
        raise ValueError("silence link has no matchers")
    return out


def build_silence(matchers: list[dict], hours: float, now: datetime) -> dict:
    stamp = lambda t: t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "matchers": matchers,
        "startsAt": stamp(now),
        "endsAt": stamp(now + timedelta(hours=hours)),
        "createdBy": "discord-silence-bot",
        "comment": f"Silenced by a Discord reaction for {hours:g}h",
    }


def describe(matchers: list[dict]) -> str:
    return ",".join(f"{m['name']}{'=' if m['isEqual'] else '!='}{m['value']}" for m in matchers)


class Api:
    """Tiny JSON-over-HTTP client. 429s are retried once after the delay Discord asks for."""

    def __init__(self, base: str, headers: dict[str, str]):
        self.base, self.headers = base.rstrip("/"), headers

    def call(self, method: str, path: str, body: dict | None = None) -> Any:
        for attempt in (1, 2):
            req = urllib.request.Request(
                self.base + path,
                method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers={**self.headers, "Content-Type": "application/json", "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                if exc.code == 429 and attempt == 1:
                    time.sleep(min(float(json.loads(detail or "{}").get("retry_after", 1)), 30))
                    continue
                raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from None
        return None


class Discord:
    def __init__(self, token: str, base: str = DISCORD_API):
        self.api = Api(base, {"Authorization": f"Bot {token}", "User-Agent": USER_AGENT})

    def messages(self, channel: str) -> list[dict]:
        return self.api.call("GET", f"/channels/{channel}/messages?limit=50") or []

    def reactors(self, channel: str, message: str, emoji: str) -> list[str]:
        path = f"/channels/{channel}/messages/{message}/reactions/{urllib.parse.quote(emoji)}?limit=100"
        return [u["id"] for u in self.api.call("GET", path) or []]

    def react(self, channel: str, message: str, emoji: str) -> None:
        self.api.call("PUT", f"/channels/{channel}/messages/{message}/reactions/{urllib.parse.quote(emoji)}/@me")

    def reply(self, channel: str, message: str, text: str) -> None:
        self.api.call("POST", f"/channels/{channel}/messages", {"content": text, "message_reference": {"message_id": message}})

    def whoami(self) -> str:
        return (self.api.call("GET", "/users/@me") or {}).get("username", "?")


class Grafana:
    def __init__(self, base: str, token: str):
        self.api = Api(base, {"Authorization": f"Bearer {token}"})

    def silence(self, payload: dict) -> str:
        return (self.api.call("POST", "/api/alertmanager/grafana/api/v2/silences", payload) or {}).get("silenceID", "?")

    def healthy(self) -> bool:
        return (self.api.call("GET", "/api/health") or {}).get("database") == "ok"


def wanted_hours(message: dict, owner: str, durations: dict[str, float], discord: Discord, channel: str) -> float | None:
    """Longest duration the owner reacted with, or None. Messages the bot already marked are skipped."""
    seen: dict[str, int] = {}
    for reaction in message.get("reactions") or []:
        name = normalize_emoji((reaction.get("emoji") or {}).get("name") or "")
        if name in (DONE, FAILED) and reaction.get("me"):
            return None
        if name in durations and reaction.get("count", 0) > 0:
            seen[name] = reaction["count"]
    best = None
    for name in seen:
        # The emoji the API reports may differ from our normalized key (skin tone), so ask with the reported name.
        raw = next(r["emoji"]["name"] for r in message["reactions"] if normalize_emoji(r["emoji"]["name"]) == name)
        if owner in discord.reactors(channel, message["id"], raw):
            best = max(best or 0, durations[name])
    return best


def handle_message(message: dict, channel: str, cfg: dict, discord: Discord, grafana: Grafana, now: datetime) -> str | None:
    if not message.get("webhook_id") or not message.get("reactions"):
        return None  # only Grafana's own webhook posts, and only ones someone reacted to
    age = now - datetime.fromisoformat(message["timestamp"].replace("Z", "+00:00"))
    if age > timedelta(hours=cfg["max_age_hours"]):
        return None
    hours = wanted_hours(message, cfg["owner"], cfg["durations"], discord, channel)
    if hours is None:
        return None
    urls = extract_silence_urls(message)
    if not urls:
        discord.react(channel, message["id"], FAILED)
        discord.reply(channel, message["id"], "No silence link in this message, so nothing to silence.")
        return "no-link"
    done, errors = [], []
    for url in urls:
        try:
            matchers = parse_matchers(url)
            grafana.silence(build_silence(matchers, hours, now))
            done.append(describe(matchers))
        except Exception as exc:  # report every failure on the message instead of retrying forever
            errors.append(str(exc)[:200])
    until = (now + timedelta(hours=hours)).astimezone(NZ).strftime("%a %H:%M")
    if errors:
        discord.react(channel, message["id"], FAILED)
        discord.reply(channel, message["id"], f"Could not silence {len(errors)} of {len(urls)}: {errors[0]}")
        return "failed"
    discord.react(channel, message["id"], DONE)
    discord.reply(channel, message["id"], f"Silenced {len(done)} alert(s) for {hours:g}h, until {until} NZ: " + "; ".join(done))
    return "silenced"


def poll_once(cfg: dict, discord: Discord, grafana: Grafana) -> int:
    handled = 0
    for channel in cfg["channels"]:
        for message in reversed(discord.messages(channel)):  # oldest first
            try:
                result = handle_message(message, channel, cfg, discord, grafana, datetime.now(timezone.utc))
            except Exception as exc:
                log(f"channel {channel} message {message.get('id')}: {exc}")
                continue
            if result:
                handled += 1
                log(f"channel {channel} message {message['id']}: {result}")
    return handled


def load_config(env: dict[str, str]) -> dict:
    need = ["DISCORD_BOT_TOKEN", "DISCORD_BOT_OWNER_ID", "DISCORD_BOT_CHANNEL_IDS", "GRAFANA_SILENCE_TOKEN"]
    missing = [k for k in need if not env.get(k, "").strip()]
    if missing:
        raise SystemExit(f"missing required environment: {', '.join(missing)}")
    return {
        "token": env["DISCORD_BOT_TOKEN"].strip(),
        "owner": env["DISCORD_BOT_OWNER_ID"].strip(),
        "channels": [c.strip() for c in env["DISCORD_BOT_CHANNEL_IDS"].split(",") if c.strip()],
        "grafana_url": env.get("GRAFANA_URL", "http://127.0.0.1:3000"),
        "grafana_token": env["GRAFANA_SILENCE_TOKEN"].strip(),
        "durations": parse_durations(env.get("DISCORD_BOT_DURATIONS", DEFAULT_DURATIONS)),
        "poll_seconds": float(env.get("DISCORD_BOT_POLL_SECONDS", "30")),
        "max_age_hours": float(env.get("DISCORD_BOT_MAX_AGE_HOURS", "24")),
    }


def main(sleep: Callable[[float], None] = time.sleep) -> None:
    cfg = load_config(dict(os.environ))
    discord, grafana = Discord(cfg["token"]), Grafana(cfg["grafana_url"], cfg["grafana_token"])
    log(f"bot {discord.whoami()!r} watching {len(cfg['channels'])} channel(s); reactions {sorted(cfg['durations'])}; grafana healthy={grafana.healthy()}")
    failures = 0
    while True:
        try:
            poll_once(cfg, discord, grafana)
            failures = 0
        except Exception as exc:
            failures += 1
            if failures in (1, 10) or failures % 120 == 0:
                log(f"poll failed ({failures} in a row): {exc}")
        sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    sys.exit(main())
