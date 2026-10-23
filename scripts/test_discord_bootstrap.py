"""Tests for discord_bootstrap.py against an in-memory fake of the Discord API."""

import base64
import contextlib
import importlib.util
import io
import json
import re
import sys
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("discord_bootstrap", Path(__file__).with_name("discord_bootstrap.py"))
db = importlib.util.module_from_spec(SPEC)
sys.modules["discord_bootstrap"] = db
SPEC.loader.exec_module(db)

TOKEN = "BOT-TOKEN-SECRET-VALUE"
ENV = {"DISCORD_BOT_TOKEN": TOKEN, "DISCORD_GUILD_ID": "111", "BAO_TOKEN": "x", "LAB_IP_OPENBAO": "10.0.0.1"}


class FakeDiscord:
    """Just enough of the Discord REST API: channels, webhooks, 429s and webhook execution."""

    def __init__(self, in_guild=True):
        self.in_guild = in_guild
        self.channels = []
        self.webhooks = []
        self.calls = []
        self.executed = []
        self.rate_limit_next = 0
        self.reject_token = False
        self.expected_token = TOKEN
        self._ids = iter(range(1000, 9999))

    def transport(self, method, url, headers, data):
        body = json.loads(data) if data else None
        self.calls.append((method, url))
        if self.rate_limit_next:
            self.rate_limit_next -= 1
            return 429, json.dumps({"retry_after": 0.01}).encode()
        path = url.removeprefix(db.API)
        if url.startswith("https://discord.com/api/webhooks/"):
            assert "Authorization" not in headers, "webhook execution must not send the bot token"
            self.executed.append((url, body))
            return 204, b""
        assert headers["Authorization"] == f"Bot {self.expected_token}"
        assert headers["User-Agent"].startswith("DiscordBot")
        if path == "/users/@me":
            if self.reject_token:
                return 401, json.dumps({"message": "401: Unauthorized", "code": 0}).encode()
            return 200, json.dumps({"username": "Gibbs Greatly Lab Automation"}).encode()
        if path == "/guilds/111":
            if not self.in_guild:
                return 403, json.dumps({"message": "Missing Access"}).encode()
            return 200, json.dumps({"name": "Lab"}).encode()
        if path == "/guilds/111/channels" and method == "GET":
            return 200, json.dumps(self.channels).encode()
        if path == "/guilds/111/channels" and method == "POST":
            chan = {"id": str(next(self._ids)), **body}
            self.channels.append(chan)
            return 201, json.dumps(chan).encode()
        match = re.fullmatch(r"/channels/(\d+)/webhooks", path)
        if match and method == "GET":
            found = [h for h in self.webhooks if h["channel_id"] == match[1]]
            return 200, json.dumps(found).encode()
        if match and method == "POST":
            hook = {"id": str(next(self._ids)), "channel_id": match[1], "name": body["name"],
                    "token": f"tok{next(self._ids)}"}
            self.webhooks.append(hook)
            return 200, json.dumps(hook).encode()
        match = re.fullmatch(r"/webhooks/(\d+)", path)
        if match and method == "DELETE":
            self.webhooks = [h for h in self.webhooks if h["id"] != match[1]]
            return 204, b""
        raise AssertionError(f"unexpected call {method} {url}")

    def mutations(self):
        return [c for c in self.calls if c[0] in ("POST", "DELETE") and "/api/webhooks/" not in c[1]]


class Writer:
    def __init__(self, code=0):
        self.code, self.calls = code, []

    def __call__(self, entry, fields, values, env):
        self.calls.append((entry, fields, values))
        return self.code


def run(fake, argv=(), writer=None, env=ENV):
    out, err = io.StringIO(), io.StringIO()
    writer = writer or Writer()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = db.main(list(argv), env=env, transport=fake.transport, writer=writer, sleep=lambda _s: None)
    return code, out.getvalue(), err.getvalue(), writer


class BootstrapTest(unittest.TestCase):
    def test_fresh_server_creates_everything_and_stores_four_urls_in_order(self):
        fake = FakeDiscord()
        code, out, err, writer = run(fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(len([c for c in fake.channels if c["type"] == db.GUILD_CATEGORY]), 1)
        self.assertEqual([c["name"] for c in fake.channels if c["type"] == db.GUILD_TEXT],
                         ["alerts-critical", "alerts-warning", "security", "events"])
        text_channels = [c for c in fake.channels if c["type"] == db.GUILD_TEXT]
        self.assertTrue(all(c["parent_id"] == fake.channels[0]["id"] for c in text_channels))
        (entry, fields, values), = writer.calls
        self.assertEqual(entry, "services/grafana")
        self.assertEqual(fields, ["DISCORD_WEBHOOK_CRITICAL", "DISCORD_WEBHOOK_WARNING",
                                  "DISCORD_WEBHOOK_SECURITY", "DISCORD_WEBHOOK_EVENTS"])
        self.assertEqual(len(values), 4)
        for chan, url in zip(text_channels, values, strict=True):
            hook = next(h for h in fake.webhooks if h["channel_id"] == chan["id"])
            self.assertEqual(url, f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}")

    def test_nothing_secret_is_ever_printed(self):
        fake = FakeDiscord()
        _code, out, err, writer = run(fake)
        everything = out + err
        self.assertNotIn(TOKEN, everything)
        self.assertNotIn("/api/webhooks/", everything)
        for hook in fake.webhooks:
            self.assertNotIn(hook["token"], everything)
        self.assertIn("Gibbs Greatly Lab Automation", out)

    def test_test_messages_have_no_mentions_and_no_auth(self):
        fake = FakeDiscord()
        run(fake)
        self.assertEqual(len(fake.executed), 4)
        for _url, body in fake.executed:
            self.assertEqual(body["allowed_mentions"], {"parse": []})

    def test_rerun_reuses_everything(self):
        fake = FakeDiscord()
        _c, _o, _e, first = run(fake)
        before = len(fake.mutations())
        code, _o, _e, second = run(fake)
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.mutations()), before, "second run must create nothing")
        self.assertEqual(first.calls[0][2], second.calls[0][2], "same URLs stored again")

    def test_rotate_replaces_webhooks(self):
        fake = FakeDiscord()
        _c, _o, _e, first = run(fake)
        _c, _o, _e, rotated = run(fake, ["--rotate"])
        self.assertEqual(len(fake.webhooks), 4)
        self.assertTrue(set(first.calls[0][2]).isdisjoint(rotated.calls[0][2]))

    def test_webhook_without_token_is_recreated(self):
        fake = FakeDiscord()
        run(fake)
        for hook in fake.webhooks:
            del hook["token"]
        code, _o, err, writer = run(fake)
        self.assertEqual(code, 0, err)
        self.assertTrue(all(url.startswith("https://discord.com/api/webhooks/") for url in writer.calls[0][2]))

    def test_dry_run_changes_nothing_and_writes_nothing(self):
        fake = FakeDiscord()
        code, out, _e, writer = run(fake, ["--dry-run"], env={k: v for k, v in ENV.items() if "BAO" not in k})
        self.assertEqual(code, 0)
        self.assertEqual(fake.mutations(), [])
        self.assertEqual(writer.calls, [])
        self.assertIn("would create", out)

    def test_rate_limit_is_retried(self):
        fake = FakeDiscord()
        fake.rate_limit_next = 2
        code, _o, err, _w = run(fake)
        self.assertEqual(code, 0, err)

    def test_missing_env_fails_before_any_call(self):
        fake = FakeDiscord()
        code, _o, err, _w = run(fake, env={"DISCORD_GUILD_ID": "111"})
        self.assertEqual(code, 2)
        self.assertEqual(fake.calls, [])

    def test_missing_openbao_token_fails_before_creating_anything(self):
        fake = FakeDiscord()
        code, _o, err, _w = run(fake, env={"DISCORD_BOT_TOKEN": TOKEN, "DISCORD_GUILD_ID": "111"})
        self.assertEqual(code, 2)
        self.assertEqual(fake.calls, [])
        self.assertIn("nowhere to go", err)

    def test_bot_not_in_server_gives_a_clear_error(self):
        fake = FakeDiscord(in_guild=False)
        code, _o, err, writer = run(fake)
        self.assertEqual(code, 1)
        self.assertIn("invited", err)
        self.assertNotIn(TOKEN, err)
        self.assertEqual(writer.calls, [])

    def test_openbao_failure_is_reported_and_no_test_messages_sent(self):
        fake = FakeDiscord()
        code, _o, err, _w = run(fake, writer=Writer(code=3))
        self.assertEqual(code, 1)
        self.assertIn("--rotate", err)
        self.assertEqual(fake.executed, [])
        self.assertNotIn("/api/webhooks/", err)


class TokenDiagnosisTest(unittest.TestCase):
    BOT_ID = "1234567890123456789"
    REAL_SHAPE = base64.urlsafe_b64encode(BOT_ID.encode()).decode().rstrip("=") + ".AbCdEf.SECRETPART-xyz"

    def test_401_reports_a_token_problem_not_an_invite_problem(self):
        fake = FakeDiscord()
        fake.reject_token = True
        fake.expected_token = self.REAL_SHAPE
        code, _o, err, writer = run(fake, env={**ENV, "DISCORD_BOT_TOKEN": self.REAL_SHAPE})
        self.assertEqual(code, 1)
        self.assertIn("rejected the bot token", err)
        self.assertNotIn("invited", err)
        self.assertIn(self.BOT_ID, err, "the non-secret bot id from part one is shown")
        self.assertNotIn("AbCdEf", err)
        self.assertNotIn("SECRETPART", err)
        self.assertEqual(writer.calls, [])

    def test_wrong_shape_is_called_out(self):
        fake = FakeDiscord()
        fake.reject_token = True
        fake.expected_token = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        code, _o, err, _w = run(fake, env={**ENV, "DISCORD_BOT_TOKEN": fake.expected_token})
        self.assertEqual(code, 1)
        self.assertIn("1 dot-separated part", err)
        self.assertIn("Client Secret", err)
        self.assertNotIn("0123456789abcdef", err)

    def test_quotes_and_bot_prefix_are_stripped(self):
        self.assertEqual(db.clean_token(' "Bot abc.def.ghi" \n'), "abc.def.ghi")
        fake = FakeDiscord()
        fake.expected_token = TOKEN
        code, _o, err, _w = run(fake, env={**ENV, "DISCORD_BOT_TOKEN": f'"Bot {TOKEN}"'})
        self.assertEqual(code, 0, err)

    def test_other_http_errors_still_point_at_the_invite(self):
        code, _o, err, _w = run(FakeDiscord(in_guild=False))
        self.assertEqual(code, 1)
        self.assertIn("invited", err)
        self.assertNotIn("rejected the bot token", err)


if __name__ == "__main__":
    unittest.main()
