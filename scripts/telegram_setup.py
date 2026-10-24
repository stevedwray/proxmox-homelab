#!/usr/bin/env python3
"""Connect the lab alert bot to Telegram and store its credentials in the oci repo's .env.

Run by the operator, from a terminal (the token is never shown or logged):

  scripts/telegram_setup.py                       # writes ~/git/oci/.env
  scripts/telegram_setup.py --env-file /path/.env

It asks for the bot token from @BotFather (hidden prompt) and checks it, waits
for you to open the bot in Telegram and press Start, shows who it saw and asks
you to confirm that is you (anyone can find and message a bot, so the chat id is
never taken blindly), writes TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to the env
file with mode 0600, and sends a test message. Existing lines are preserved.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

API = "https://api.telegram.org"
DEFAULT_ENV = Path.home() / "git" / "oci" / ".env"
TOKEN_SHAPE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
WAIT_SECONDS = 180

Transport = Callable[[str, bytes, float], tuple[int, bytes]]


class TelegramError(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def urllib_transport(url: str, data: bytes, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        # The URL contains the token, so report only the reason.
        raise TelegramError(f"could not reach Telegram ({getattr(exc, 'reason', exc)})") from None


def clean_token(raw: str) -> str:
    return raw.strip().strip("\"'").strip().removeprefix("bot").strip()


def diagnose_token(token: str) -> str:
    """Say what is wrong with a token without revealing it."""
    if ":" not in token:
        return (f"The value is {len(token)} characters with no colon. A bot token looks like "
                "<digits>:<35 characters> and is about 46 characters long; copy it from BotFather's reply.")
    left, right = token.split(":", 1)
    return (f"The value is {len(token)} characters (bot id {left if left.isdigit() else '?'}, "
            f"secret part {len(right)} characters). A bot token is about 46 characters: <digits>:<35 characters>.")


class Telegram:
    def __init__(self, token: str, transport: Transport = urllib_transport) -> None:
        self._token = token
        self._transport = transport

    def call(self, method: str, params: dict | None = None, timeout: float = 20):
        status, raw = self._transport(f"{API}/bot{self._token}/{method}", json.dumps(params or {}).encode(), timeout)
        body = json.loads(raw) if raw else {}
        if status != 200 or not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', f'HTTP {status}')}", body.get("error_code", status))
        return body["result"]


def wait_for_senders(tg: Telegram, seconds: float, now: Callable[[], float] = time.monotonic) -> dict[int, dict]:
    """Poll until at least one private-chat message arrives; return {chat id: who}. Clears the queue."""
    deadline, offset, seen = now() + seconds, None, {}
    while now() < deadline and not seen:
        params = {"timeout": 20, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        for update in tg.call("getUpdates", params, timeout=40):
            offset = update["update_id"] + 1
            chat = (update.get("message") or {}).get("chat") or {}
            if chat.get("type") == "private":
                seen[chat["id"]] = {"name": chat.get("first_name", "?"), "username": chat.get("username", "")}
    if offset is not None:  # acknowledge, so the relay never sees these old updates
        tg.call("getUpdates", {"offset": offset, "timeout": 0})
    return seen


def write_env(path: Path, values: dict[str, str]) -> None:
    """Replace or append KEY=value lines, keeping everything else, and leave the file mode 0600."""
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in remaining and not line.lstrip().startswith("#"):
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in remaining.items()]
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(out) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv: list[str], transport: Transport = urllib_transport,
         ask: Callable[[str], str] = input, secret: Callable[[str], str] = getpass.getpass,
         now: Callable[[], float] = time.monotonic, wait_seconds: float = WAIT_SECONDS) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    args = parser.parse_args(argv)
    if not args.env_file.parent.is_dir():
        print(f"ERROR: {args.env_file.parent} does not exist.", file=sys.stderr)
        return 2

    token = clean_token(secret("Bot token from @BotFather (hidden): "))
    if not TOKEN_SHAPE.match(token):
        print(f"ERROR: that does not look like a bot token. {diagnose_token(token)}", file=sys.stderr)
        return 1
    tg = Telegram(token, transport)
    try:
        me = tg.call("getMe")
    except TelegramError as exc:
        hint = f" {diagnose_token(token)}" if exc.code == 401 else ""
        print(f"ERROR: Telegram rejected the token ({exc}).{hint}", file=sys.stderr)
        return 1
    print(f"Token OK: bot '{me['first_name']}' (@{me['username']}).")
    print(f"Now open https://t.me/{me['username']} in Telegram and press Start. Waiting up to "
          f"{int(wait_seconds)} seconds...")

    try:
        seen = wait_for_senders(tg, wait_seconds, now)
    except TelegramError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not seen:
        print("ERROR: no message arrived in time. Press Start in the bot's chat and run this again.", file=sys.stderr)
        return 1

    people = list(seen.items())
    print("Saw message(s) from:")
    for i, (chat_id, who) in enumerate(people, 1):
        print(f"  {i}. {who['name']} {('@' + who['username']) if who['username'] else ''} (chat id {chat_id})")
    pick = 1
    if len(people) > 1:
        print("More than one person messaged the bot. Pick only yourself.")
        choice = ask(f"Which one is you (1-{len(people)}, blank to abort)? ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(people):
            print("Aborted; nothing written.", file=sys.stderr)
            return 1
        pick = int(choice)
    elif ask("Is that you? Only answer y if so [y/N] ").strip().lower() != "y":
        print("Aborted; nothing written.", file=sys.stderr)
        return 1
    chat_id = people[pick - 1][0]

    write_env(args.env_file, {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": str(chat_id)})
    print(f"Wrote TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to {args.env_file} (mode 0600).")
    try:
        tg.call("sendMessage", {"chat_id": chat_id, "text": "Lab alerts bot is connected. This is a test message."})
    except TelegramError as exc:
        print(f"WARNING: saved, but the test message failed: {exc}", file=sys.stderr)
        return 1
    print("Test message sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
