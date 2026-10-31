#!/usr/bin/env python3
"""React to a Grafana alert in Discord to silence it, or to have the local model investigate it
(docs/alerting/discord-silence-bot.md, docs/alerting/alert-investigator.md).

Polls the alert channels over Discord's REST API (no websocket, no third-party libraries). When the
owner reacts to a Grafana-sent message with a duration emoji, it reads the "silence" links in that
message, turns each into a Grafana silence for the chosen time, then marks the message with a check
mark and replies with what it did. It is off the alert path: if it is down, alerts still arrive.

A 🔍 from the owner (or a page arriving, when INVESTIGATE_AUTO_LABELS matches) queues an investigation instead:
alert_investigator.py runs it in a background thread, one at a time, so silencing is never held up by the model.

Needs the bot's MESSAGE_CONTENT intent (Developer Portal toggle), or Discord hides the embeds it reads.
"""

from __future__ import annotations

import html
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

DISCORD_API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/stevedwray/proxmox-homelab, 1)"  # Discord rejects generic agents
DEFAULT_DURATIONS = "\U0001F44D=4,\U0001F319=12,\U0001F4C5=24"  # thumbs up 4h, crescent moon 12h, calendar 24h
DEFAULT_SEED = "\U0001F50D,\U0001F319"  # magnifying glass, crescent moon: the buttons worth having one click away
DONE, FAILED = "✅", "❌"  # bot's own marker reactions: check mark, cross mark
INVESTIGATE = {"\U0001F50D", "\U0001F50E"}  # magnifying glass, either way round
QUEUED, REPORTED, INV_FAILED = "⏳", "\U0001F4DD", "⚠"  # bot's own investigation markers: hourglass, memo, warning
DEFAULT_AUTO_LABELS = "page=true,tripwire=honeypot"
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

    def call(self, method: str, path: str, body: dict | None = None, raw: tuple[bytes, str] | None = None) -> Any:
        data, ctype = raw if raw else (json.dumps(body).encode() if body is not None else None, "application/json")
        for attempt in (1, 2):
            req = urllib.request.Request(
                self.base + path,
                method=method,
                data=data,
                headers={**self.headers, "Content-Type": ctype, "Accept": "application/json"},
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

    def reply_with_file(self, channel: str, message: str, text: str, filename: str, content: str) -> None:
        """One reply carrying a text file (needs the Attach Files permission)."""
        boundary = uuid.uuid4().hex
        payload = {"content": text, "message_reference": {"message_id": message}, "attachments": [{"id": 0, "filename": filename}]}
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n"
            f"{json.dumps(payload)}\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{filename}\"\r\n"
            f"Content-Type: text/markdown; charset=utf-8\r\n\r\n"
        ).encode() + content.encode() + f"\r\n--{boundary}--\r\n".encode()
        self.api.call("POST", f"/channels/{channel}/messages", raw=(body, f"multipart/form-data; boundary={boundary}"))

    def whoami(self) -> str:
        return (self.api.call("GET", "/users/@me") or {}).get("username", "?")


class Grafana:
    def __init__(self, base: str, token: str):
        self.api = Api(base, {"Authorization": f"Bearer {token}"})

    def silence(self, payload: dict) -> str:
        return (self.api.call("POST", "/api/alertmanager/grafana/api/v2/silences", payload) or {}).get("silenceID", "?")

    def healthy(self) -> bool:
        return (self.api.call("GET", "/api/health") or {}).get("database") == "ok"


def others_reacted(reaction: dict) -> bool:
    """True when someone besides the bot is among the reactors (the bot's own seeded reaction is not a request)."""
    return reaction.get("count", 0) - (1 if reaction.get("me") else 0) > 0


def seed_reactions(message: dict, channel: str, cfg: dict, discord: Discord, now: datetime) -> list[str]:
    """Pre-add the owner's one-click buttons to a fresh alert that has a silence link, so they need not hunt the picker."""
    if not message.get("webhook_id") or not cfg.get("seed") or not extract_silence_urls(message):
        return []
    age = now - datetime.fromisoformat(message["timestamp"].replace("Z", "+00:00"))
    if age > timedelta(hours=cfg["seed_max_age_hours"]):
        return []  # do not backfill history after a deploy
    have = my_markers(message)
    added = []
    for emoji in cfg["seed"]:
        if normalize_emoji(emoji) not in have:
            discord.react(channel, message["id"], emoji)
            added.append(emoji)
    return added


def wanted_hours(message: dict, owner: str, durations: dict[str, float], discord: Discord, channel: str) -> float | None:
    """Longest duration the owner reacted with, or None. Messages the bot already marked are skipped."""
    seen: dict[str, int] = {}
    for reaction in message.get("reactions") or []:
        name = normalize_emoji((reaction.get("emoji") or {}).get("name") or "")
        if name in (DONE, FAILED) and reaction.get("me"):
            return None
        if name in durations and others_reacted(reaction):
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


# ---- Investigations (docs/alerting/alert-investigator.md) ---------------------------------------------------------

SEVERITY_ICONS = {"real-problem": "🔴", "needs-attention": "🟠", "noise": "⚪", "unclear": "❔"}


def alert_labels(message: dict) -> list[dict[str, str]]:
    """Each alert's labels, read back from its silence link (Grafana puts one equality matcher per label there)."""
    out = []
    for url in extract_silence_urls(message):
        try:
            matchers = parse_matchers(url)
        except ValueError:
            continue
        out.append({m["name"]: m["value"] for m in matchers if m["isEqual"] and not m["isRegex"]})
    return out


def parse_label_pairs(spec: str) -> list[tuple[str, str]]:
    return [(k.strip(), v.strip()) for k, _, v in (p.partition("=") for p in spec.split(",")) if k.strip() and v.strip()]


def my_markers(message: dict) -> set[str]:
    return {normalize_emoji((r.get("emoji") or {}).get("name") or "") for r in message.get("reactions") or [] if r.get("me")}


class Investigations:
    """Decides which messages to investigate and runs them one at a time on a worker thread.

    The poll loop only calls consider(), which is quick: it queues a job and marks the message ⏳. The worker posts
    the result as a reply with the report attached and marks 📝 (or ⚠ on failure). Those marks are what makes it
    idempotent across restarts: a ⏳ with no 📝/⚠ after a restart means the job was lost, so it is queued again.
    """

    def __init__(self, cfg: dict, discord: Discord, runner: Callable[[dict], tuple[str, str, str]], max_queue: int = 5):
        self.cfg, self.discord, self.runner = cfg, discord, runner
        self.jobs: queue.Queue[dict] = queue.Queue(maxsize=max_queue)
        self.pending: set[str] = set()
        self.finished: set[str] = set()
        self.auto_seen: dict[str, datetime] = {}
        self.lock = threading.Lock()

    def owner_asked(self, message: dict, channel: str) -> bool:
        for reaction in message.get("reactions") or []:
            raw = (reaction.get("emoji") or {}).get("name") or ""
            if (normalize_emoji(raw) in INVESTIGATE and others_reacted(reaction)
                    and self.cfg["owner"] in self.discord.reactors(channel, message["id"], raw)):
                return True
        return False

    def auto_key(self, alerts: list[dict[str, str]]) -> str | None:
        wanted = self.cfg["auto_labels"]
        hits = [a for a in alerts if any(a.get(k) == v for k, v in wanted)]
        return "|".join(sorted(json.dumps(a, sort_keys=True) for a in hits)) or None

    def consider(self, message: dict, channel: str, now: datetime) -> str | None:
        if not message.get("webhook_id"):
            return None
        age = now - datetime.fromisoformat(message["timestamp"].replace("Z", "+00:00"))
        if age > timedelta(hours=self.cfg["max_age_hours"]):
            return None
        mid, mine = message["id"], my_markers(message)
        with self.lock:
            if REPORTED in mine or INV_FAILED in mine or mid in self.finished or mid in self.pending:
                return None
        alerts = alert_labels(message)
        reason = None
        if QUEUED in mine:
            reason = "resumed"  # queued before a restart and never finished
        elif self.owner_asked(message, channel):
            reason = "asked"
        elif age <= timedelta(minutes=self.cfg["auto_max_age_minutes"]):
            key = self.auto_key(alerts)
            last = self.auto_seen.get(key or "")
            if key and (last is None or now - last > timedelta(hours=self.cfg["auto_repeat_hours"])):
                self.auto_seen[key], reason = now, "auto"  # a page repeats every 30 min: investigate it once
        if reason is None:
            return None
        if not alerts:
            self.discord.react(channel, mid, INV_FAILED)
            self.discord.reply(channel, mid, "No alert labels in this message (resolved messages carry none), so nothing to investigate.")
            self.finished.add(mid)
            return "no-labels"
        job = {"channel": channel, "message": mid, "alerts": alerts, "text": message_text(message),
               "title": ((message.get("embeds") or [{}])[0].get("title") or "alert"), "reason": reason}
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            self.discord.react(channel, mid, INV_FAILED)
            self.discord.reply(channel, mid, "Too many investigations queued already; react 🔍 again later.")
            self.finished.add(mid)
            return "busy"
        with self.lock:
            self.pending.add(mid)
        if QUEUED not in mine:
            self.discord.react(channel, mid, QUEUED)
        return f"investigation queued ({reason})"

    def run_one(self, job: dict) -> str:
        channel, mid = job["channel"], job["message"]
        try:
            text, filename, report = self.runner(job)
        except Exception as exc:  # the model or a datasource failed: say so on the message, never retry in a loop
            self.discord.react(channel, mid, INV_FAILED)
            self.discord.reply(channel, mid, f"Investigation failed: {str(exc)[:300]}")
            return "investigation failed"
        try:
            self.discord.reply_with_file(channel, mid, text[:1990], filename, report)
        except Exception as exc:
            self.discord.reply(channel, mid, (text[:1700] + f"\n(Could not attach the full report: {str(exc)[:150]})"))
        self.discord.react(channel, mid, REPORTED)
        return "investigated"

    def work_forever(self) -> None:
        while True:
            job = self.jobs.get()
            started = time.monotonic()
            try:
                result = self.run_one(job)
            except Exception as exc:  # even reporting failed (Discord down): drop it, the ⏳ stays and a restart resumes it
                result = f"could not report: {exc}"
            finally:
                with self.lock:
                    self.pending.discard(job["message"])
                    self.finished.add(job["message"])
            log(f"channel {job['channel']} message {job['message']}: {result} in {time.monotonic() - started:.0f}s")


def make_runner(cfg: dict) -> Callable[[dict], tuple[str, str, str]]:
    import alert_investigator as ai  # beside this file in the container

    tools = ai.Tools(cfg["investigator"])
    llm = ai.Llm(cfg["llm_url"], cfg["llm_api_key"], cfg["llm_model"], timeout=cfg["llm_timeout_seconds"])

    def run(job: dict) -> tuple[str, str, str]:
        started, t0 = datetime.now(timezone.utc), time.monotonic()
        report = ai.investigate(job["alerts"], job["text"], tools, llm, cfg["max_steps"], cfg["deadline_seconds"])
        text = (f"{SEVERITY_ICONS.get(report.severity, '❔')} **{report.severity}**: {report.summary}\n"
                f"-# {len(report.steps)} tool call(s), model `{report.model}`, {time.monotonic() - t0:.0f}s. "
                "Advisory only: nothing was changed.")
        return text, f"investigation-{started:%Y%m%d-%H%M}.md", ai.render_markdown(report, job["title"], started)

    return run


def cfg_for_seed(cfg: dict, investigations: "Investigations | None") -> dict:
    """The 🔍 button only makes sense when investigations are on."""
    seed = [e for e in cfg.get("seed") or [] if investigations is not None or normalize_emoji(e) not in INVESTIGATE]
    return {**cfg, "seed": seed}


def poll_once(cfg: dict, discord: Discord, grafana: Grafana, investigations: Investigations | None = None) -> int:
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
            try:
                seeded = seed_reactions(message, channel, cfg_for_seed(cfg, investigations), discord, datetime.now(timezone.utc))
                if seeded:
                    message = {**message, "reactions": (message.get("reactions") or []) + [{"emoji": {"name": e}, "count": 1, "me": True} for e in seeded]}
            except Exception as exc:
                log(f"channel {channel} message {message.get('id')}: could not add reaction buttons: {exc}")
            if investigations is None:
                continue
            try:
                queued = investigations.consider(message, channel, datetime.now(timezone.utc))
            except Exception as exc:
                log(f"channel {channel} message {message.get('id')}: investigation not queued: {exc}")
                continue
            if queued:
                log(f"channel {channel} message {message['id']}: {queued}")
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
        "seed": [e.strip() for e in env.get("DISCORD_BOT_SEED_REACTIONS", DEFAULT_SEED).split(",") if e.strip()],
        "seed_max_age_hours": float(env.get("DISCORD_BOT_SEED_MAX_AGE_HOURS", "2")),
        "poll_seconds": float(env.get("DISCORD_BOT_POLL_SECONDS", "30")),
        "max_age_hours": float(env.get("DISCORD_BOT_MAX_AGE_HOURS", "24")),
        # Investigations are on only when the model endpoint is configured.
        "investigate": bool(env.get("INVESTIGATOR_LLM_URL", "").strip() and env.get("INVESTIGATOR_LLM_API_KEY", "").strip()),
        "llm_url": env.get("INVESTIGATOR_LLM_URL", "").strip(),
        "llm_api_key": env.get("INVESTIGATOR_LLM_API_KEY", "").strip(),
        "llm_model": env.get("INVESTIGATOR_MODEL", "").strip(),  # empty: whatever Framework has loaded
        "llm_timeout_seconds": float(env.get("INVESTIGATOR_LLM_TIMEOUT_SECONDS", "300")),
        "max_steps": int(env.get("INVESTIGATOR_MAX_STEPS", "8")),
        "deadline_seconds": float(env.get("INVESTIGATOR_DEADLINE_SECONDS", "900")),
        "auto_labels": parse_label_pairs(env.get("INVESTIGATE_AUTO_LABELS", DEFAULT_AUTO_LABELS)),
        "auto_max_age_minutes": float(env.get("INVESTIGATE_AUTO_MAX_AGE_MINUTES", "60")),
        "auto_repeat_hours": float(env.get("INVESTIGATE_AUTO_REPEAT_HOURS", "12")),
        "investigator": {
            "victoriametrics_url": env.get("VICTORIAMETRICS_URL", "http://127.0.0.1:8428"),
            "grafana_url": env.get("GRAFANA_URL", "http://127.0.0.1:3000"),
            "grafana_token": env["GRAFANA_SILENCE_TOKEN"].strip(),
            "graylog_url": env.get("GRAYLOG_URL", "").strip(),
            "graylog_token": env.get("GRAYLOG_TOKEN", "").strip(),
            "opensearch_url": env.get("OPENSEARCH_URL", "").strip(),
            "opensearch_user": env.get("OPENSEARCH_USER", "").strip(),
            "opensearch_password": env.get("OPENSEARCH_PASSWORD", "").strip(),
            "opensearch_verify_tls": env.get("OPENSEARCH_VERIFY_TLS", "true").strip().lower() in ("1", "true", "yes"),
        },
    }


def main(sleep: Callable[[float], None] = time.sleep) -> None:
    cfg = load_config(dict(os.environ))
    discord, grafana = Discord(cfg["token"]), Grafana(cfg["grafana_url"], cfg["grafana_token"])
    investigations = None
    if cfg["investigate"]:
        investigations = Investigations(cfg, discord, make_runner(cfg))
        threading.Thread(target=investigations.work_forever, name="investigations", daemon=True).start()
    inv = cfg["investigator"]
    sources = [n for n, on in (("graylog", inv["graylog_token"]), ("opensearch", inv["opensearch_password"])) if on]
    log(f"bot {discord.whoami()!r} watching {len(cfg['channels'])} channel(s); reactions {sorted(cfg['durations'])}; grafana healthy={grafana.healthy()}; "
        f"investigations {'on (metrics, grafana' + ''.join(', ' + n for n in sources) + ')' if investigations else 'off'}")
    failures = 0
    while True:
        try:
            poll_once(cfg, discord, grafana, investigations)
            failures = 0
        except Exception as exc:
            failures += 1
            if failures in (1, 10) or failures % 120 == 0:
                log(f"poll failed ({failures} in a row): {exc}")
        sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    sys.exit(main())
