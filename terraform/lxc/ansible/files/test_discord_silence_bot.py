import unittest
from datetime import datetime, timedelta, timezone

import discord_silence_bot as bot

NOW = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc)
OWNER = "111"
URL = "https://grafana.example/alerting/silence/new?alertmanager=grafana&matcher=alertname%3DScrape%20target%20down&matcher=instance%3D192.168.20.12%3A9100"
CFG = {"owner": OWNER, "durations": bot.parse_durations(bot.DEFAULT_DURATIONS), "max_age_hours": 24, "channels": ["c1"]}


class FakeDiscord:
    def __init__(self, reactors=None):
        self.reactors_by_emoji = reactors or {}
        self.reactions, self.replies = [], []

    def reactors(self, channel, message, emoji):
        return self.reactors_by_emoji.get(bot.normalize_emoji(emoji), [])

    def react(self, channel, message, emoji):
        self.reactions.append(emoji)

    def reply(self, channel, message, text):
        self.replies.append(text)


class FakeGrafana:
    def __init__(self, fail=False):
        self.payloads, self.fail = [], fail

    def silence(self, payload):
        if self.fail:
            raise RuntimeError("grafana said no")
        self.payloads.append(payload)
        return "abc"


def message(reactions=("\U0001F44D",), webhook=True, embed_text=f"line one [silence]({URL})", age_hours=1, me=()):
    return {
        "id": "m1",
        "webhook_id": "w1" if webhook else None,
        "timestamp": (NOW - timedelta(hours=age_hours)).isoformat(),
        "content": "",
        "embeds": [{"title": "[FIRING] x", "description": embed_text}],
        "reactions": [{"emoji": {"name": r}, "count": 1, "me": r in me} for r in reactions],
    }


def run(msg, discord=None, grafana=None):
    discord, grafana = discord or FakeDiscord({"\U0001F44D": [OWNER]}), grafana or FakeGrafana()
    return bot.handle_message(msg, "c1", CFG, discord, grafana, NOW), discord, grafana


class Parsing(unittest.TestCase):
    def test_extracts_each_link_once_from_embeds_and_content(self):
        msg = message(embed_text=f"a [silence]({URL}) b\nSilence: {URL}")
        self.assertEqual(bot.extract_silence_urls(msg), [URL])

    def test_html_escaped_links_are_read(self):
        msg = message(embed_text=URL.replace("&", "&amp;"))
        self.assertEqual(bot.extract_silence_urls(msg), [URL])

    def test_matchers_decoded_with_operators(self):
        url = "https://g/alerting/silence/new?matcher=a%3Db&matcher=b%21%3Dc&matcher=c%3D~d.%2A&matcher=e%21~f"
        got = bot.parse_matchers(url)
        self.assertEqual([(m["name"], m["value"], m["isRegex"], m["isEqual"]) for m in got],
                         [("a", "b", False, True), ("b", "c", False, False), ("c", "d.*", True, True), ("e", "f", True, False)])

    def test_value_may_contain_equals(self):
        got = bot.parse_matchers("https://g/alerting/silence/new?matcher=expr%3Da%3Db")
        self.assertEqual((got[0]["name"], got[0]["value"]), ("expr", "a=b"))

    def test_link_without_matchers_is_an_error(self):
        with self.assertRaises(ValueError):
            bot.parse_matchers("https://g/alerting/silence/new?alertmanager=grafana")

    def test_skin_tone_and_variation_selector_are_ignored(self):
        self.assertEqual(bot.normalize_emoji("\U0001F44D\U0001F3FD"), "\U0001F44D")
        self.assertEqual(bot.normalize_emoji("⚠️"), "⚠")

    def test_silence_window(self):
        s = bot.build_silence(bot.parse_matchers(URL), 4, NOW)
        self.assertEqual((s["startsAt"], s["endsAt"]), ("2026-10-29T06:00:00.000Z", "2026-10-29T10:00:00.000Z"))
        self.assertEqual(len(s["matchers"]), 2)


class Handling(unittest.TestCase):
    def test_owner_thumbs_up_silences_for_four_hours_and_marks_done(self):
        result, d, g = run(message())
        self.assertEqual(result, "silenced")
        self.assertEqual(g.payloads[0]["endsAt"], "2026-10-29T10:00:00.000Z")
        self.assertEqual(d.reactions, [bot.DONE])
        self.assertIn("4h", d.replies[0])
        self.assertIn("Scrape target down", d.replies[0])

    def test_longest_of_several_reactions_wins(self):
        d = FakeDiscord({"\U0001F44D": [OWNER], "\U0001F4C5": [OWNER]})
        _, _, g = run(message(reactions=("\U0001F44D", "\U0001F4C5")), d)
        self.assertEqual(g.payloads[0]["endsAt"], "2026-10-30T06:00:00.000Z")

    def test_someone_elses_reaction_is_ignored(self):
        result, d, g = run(message(), FakeDiscord({"\U0001F44D": ["999"]}))
        self.assertIsNone(result)
        self.assertEqual((g.payloads, d.reactions), ([], []))

    def test_only_webhook_messages_are_acted_on(self):
        result, _, g = run(message(webhook=False))
        self.assertIsNone(result)
        self.assertEqual(g.payloads, [])

    def test_already_marked_message_is_skipped(self):
        result, _, g = run(message(reactions=("\U0001F44D", bot.DONE), me=(bot.DONE,)))
        self.assertIsNone(result)
        self.assertEqual(g.payloads, [])

    def test_old_message_is_skipped(self):
        result, _, g = run(message(age_hours=30))
        self.assertIsNone(result)
        self.assertEqual(g.payloads, [])

    def test_unrelated_reaction_is_skipped(self):
        result, _, _ = run(message(reactions=("\U0001F602",)))
        self.assertIsNone(result)

    def test_message_without_link_gets_an_explanation(self):
        result, d, g = run(message(embed_text="[RESOLVED] all good"))
        self.assertEqual(result, "no-link")
        self.assertEqual((d.reactions, g.payloads), ([bot.FAILED], []))

    def test_grouped_message_silences_every_alert(self):
        other = URL.replace("Scrape%20target%20down", "Disk%20high")
        result, _, g = run(message(embed_text=f"[silence]({URL})\n[silence]({other})"))
        self.assertEqual((result, len(g.payloads)), ("silenced", 2))

    def test_grafana_failure_is_reported_and_marked_so_it_is_not_retried(self):
        result, d, _ = run(message(), grafana=FakeGrafana(fail=True))
        self.assertEqual(result, "failed")
        self.assertEqual(d.reactions, [bot.FAILED])
        self.assertIn("grafana said no", d.replies[0])


class Config(unittest.TestCase):
    def test_missing_settings_stop_startup(self):
        with self.assertRaises(SystemExit):
            bot.load_config({"DISCORD_BOT_TOKEN": "t"})

    def test_channels_and_defaults(self):
        cfg = bot.load_config({"DISCORD_BOT_TOKEN": "t", "DISCORD_BOT_OWNER_ID": "1", "DISCORD_BOT_CHANNEL_IDS": "1, 2,", "GRAFANA_SILENCE_TOKEN": "g"})
        self.assertEqual((cfg["channels"], cfg["poll_seconds"], cfg["max_age_hours"]), (["1", "2"], 30.0, 24.0))


if __name__ == "__main__":
    unittest.main()
