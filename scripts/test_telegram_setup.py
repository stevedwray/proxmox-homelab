"""Tests for telegram_setup.py against an in-memory fake of the Telegram Bot API."""

import contextlib
import importlib.util
import io
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("telegram_setup", Path(__file__).with_name("telegram_setup.py"))
ts = importlib.util.module_from_spec(SPEC)
sys.modules["telegram_setup"] = ts
SPEC.loader.exec_module(ts)

# Built from pieces so no token-shaped literal sits in the source.
TOKEN = "123456789" + ":" + "x" * 35


def private(update_id, chat_id, name, username=""):
    chat = {"id": chat_id, "type": "private", "first_name": name}
    if username:
        chat["username"] = username
    return {"update_id": update_id, "message": {"chat": chat, "text": "/start"}}


class FakeTelegram:
    def __init__(self, updates=None, token=TOKEN):
        self.token, self.updates, self.sent, self.calls = token, list(updates or []), [], []

    def transport(self, url, data, timeout):
        prefix = f"{ts.API}/bot"
        assert url.startswith(prefix)
        token, method = url[len(prefix):].rsplit("/", 1)
        params = json.loads(data)
        self.calls.append(method)
        if token != self.token:
            return 401, json.dumps({"ok": False, "error_code": 401, "description": "Unauthorized"}).encode()
        if method == "getMe":
            result = {"id": 123456789, "first_name": "Lab Alerts", "username": "lab_alerts_bot"}
        elif method == "getUpdates":
            offset = params.get("offset")
            if offset is not None:
                self.updates = [u for u in self.updates if u["update_id"] >= offset]
                result = []
            else:
                result = list(self.updates)
        elif method == "sendMessage":
            self.sent.append(params)
            result = {"message_id": 1}
        else:
            raise AssertionError(method)
        return 200, json.dumps({"ok": True, "result": result}).encode()


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 25
        return self.t


def run(fake, env_file, answers=("y",), secret_value=TOKEN, wait=100):
    out, err = io.StringIO(), io.StringIO()
    queue = list(answers)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ts.main(["--env-file", str(env_file)], transport=fake.transport, ask=lambda _p: queue.pop(0),
                       secret=lambda _p: secret_value, now=Clock(), wait_seconds=wait)
    return code, out.getvalue(), err.getvalue()


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = Path(self.dir.name) / ".env"
        self.addCleanup(self.dir.cleanup)

    def test_happy_path_writes_env_with_mode_600_and_sends_test_message(self):
        self.env.write_text("CF_DNS_API_TOKEN=keepme\n# a comment\nTELEGRAM_CHAT_ID=old\n")
        self.env.chmod(0o644)
        fake = FakeTelegram([private(10, 4242, "Steve", "steve")])
        code, out, err = run(fake, self.env)
        self.assertEqual(code, 0, err)
        lines = self.env.read_text().splitlines()
        self.assertEqual(lines[0], "CF_DNS_API_TOKEN=keepme")
        self.assertEqual(lines[1], "# a comment")
        self.assertEqual(lines.count("TELEGRAM_CHAT_ID=4242"), 1)
        self.assertNotIn("TELEGRAM_CHAT_ID=old", lines)
        self.assertIn(f"TELEGRAM_BOT_TOKEN={TOKEN}", lines)
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)
        self.assertEqual(fake.sent[0]["chat_id"], 4242)
        self.assertEqual(fake.updates, [], "the queue is acknowledged so the relay never sees old updates")

    def test_token_never_printed(self):
        fake = FakeTelegram([private(10, 4242, "Steve")])
        _code, out, err = run(fake, self.env)
        self.assertNotIn(TOKEN, out + err)
        self.assertNotIn("x" * 35, out + err)

    def test_creates_env_file_when_absent(self):
        fake = FakeTelegram([private(10, 7, "Steve")])
        self.assertEqual(run(fake, self.env)[0], 0)
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)

    def test_wrong_shape_is_explained_without_echoing_it(self):
        fake = FakeTelegram()
        code, _o, err = run(fake, self.env, secret_value="0123456789")
        self.assertEqual(code, 1)
        self.assertIn("no colon", err)
        self.assertIn("10 characters", err)
        self.assertNotIn("0123456789", err)
        self.assertEqual(fake.calls, [])
        self.assertFalse(self.env.exists())

    def test_rejected_token_shows_only_the_bot_id(self):
        fake = FakeTelegram(token="999999999" + ":" + "y" * 35)
        code, _o, err = run(fake, self.env)
        self.assertEqual(code, 1)
        self.assertIn("rejected", err)
        self.assertIn("bot id 123456789", err)
        self.assertNotIn("x" * 35, err)
        self.assertFalse(self.env.exists())

    def test_quotes_and_bot_prefix_are_stripped(self):
        self.assertEqual(ts.clean_token(f' "bot{TOKEN}" '), TOKEN)

    def test_declining_confirmation_writes_nothing(self):
        fake = FakeTelegram([private(10, 4242, "Stranger")])
        code, _o, err = run(fake, self.env, answers=("n",))
        self.assertEqual(code, 1)
        self.assertFalse(self.env.exists())
        self.assertEqual(fake.sent, [])

    def test_several_senders_requires_choosing_yourself(self):
        fake = FakeTelegram([private(10, 111, "Intruder"), private(11, 222, "Steve", "steve")])
        code, out, _e = run(fake, self.env, answers=("2",))
        self.assertEqual(code, 0)
        self.assertIn("TELEGRAM_CHAT_ID=222", self.env.read_text())
        self.assertIn("More than one person", out)

    def test_several_senders_blank_answer_aborts(self):
        fake = FakeTelegram([private(10, 111, "Intruder"), private(11, 222, "Steve")])
        code, _o, _e = run(fake, self.env, answers=("",))
        self.assertEqual(code, 1)
        self.assertFalse(self.env.exists())

    def test_group_messages_are_ignored(self):
        group = {"update_id": 10, "message": {"chat": {"id": -5, "type": "group", "title": "g"}, "text": "hi"}}
        fake = FakeTelegram([group])
        code, _o, err = run(fake, self.env)
        self.assertEqual(code, 1)
        self.assertIn("no message arrived", err)
        self.assertFalse(self.env.exists())

    def test_timeout_when_nobody_presses_start(self):
        code, _o, err = run(FakeTelegram(), self.env)
        self.assertEqual(code, 1)
        self.assertIn("no message arrived", err)

    def test_missing_directory_is_reported(self):
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            code = ts.main(["--env-file", str(Path(self.dir.name) / "nope" / ".env")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
