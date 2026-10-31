import unittest
from datetime import datetime, timedelta, timezone

import discord_silence_bot as bot

NOW = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc)
OWNER = "111"
URL = "https://grafana.example/alerting/silence/new?alertmanager=grafana&matcher=alertname%3DScrape%20target%20down&matcher=instance%3D192.168.20.12%3A9100"
CFG = {"owner": OWNER, "durations": bot.parse_durations(bot.DEFAULT_DURATIONS), "max_age_hours": 24, "channels": ["c1"],
       "seed": ["\U0001F50D", "\U0001F319"], "seed_max_age_hours": 2}


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
        self.assertFalse(cfg["investigate"])  # off until the model endpoint is configured
        self.assertEqual(cfg["auto_labels"], [("page", "true"), ("tripwire", "honeypot")])

    def test_investigations_on_with_a_model_endpoint(self):
        cfg = bot.load_config({"DISCORD_BOT_TOKEN": "t", "DISCORD_BOT_OWNER_ID": "1", "DISCORD_BOT_CHANNEL_IDS": "1",
                               "GRAFANA_SILENCE_TOKEN": "g", "INVESTIGATOR_LLM_URL": "http://f:8080/v1", "INVESTIGATOR_LLM_API_KEY": "k",
                               "INVESTIGATE_AUTO_LABELS": ""})
        self.assertTrue(cfg["investigate"])
        self.assertEqual((cfg["auto_labels"], cfg["investigator"]["grafana_token"]), ([], "g"))


PAGE_URL = URL + "&matcher=page%3Dtrue"
MAG = "\U0001F50D"


class InvDiscord(FakeDiscord):
    def __init__(self, reactors=None, fail_file=False):
        super().__init__(reactors)
        self.files, self.fail_file = [], fail_file

    def reply_with_file(self, channel, message, text, filename, content):
        if self.fail_file:
            raise RuntimeError("403 missing permission")
        self.files.append((text, filename, content))


def inv(discord=None, runner=None, **cfg):
    config = {**CFG, "auto_labels": bot.parse_label_pairs(bot.DEFAULT_AUTO_LABELS), "auto_max_age_minutes": 60,
              "auto_repeat_hours": 12, **cfg}
    return bot.Investigations(config, discord or InvDiscord(), runner or (lambda job: ("ok", "r.md", "# report")), max_queue=2)


class Investigating(unittest.TestCase):
    def test_owner_magnifier_queues_once_and_marks_hourglass(self):
        d = InvDiscord({MAG: [OWNER]})
        i = inv(d)
        msg = message(reactions=(MAG,))
        self.assertEqual(i.consider(msg, "c1", NOW), "investigation queued (asked)")
        self.assertEqual(d.reactions, [bot.QUEUED])
        self.assertIsNone(i.consider(msg, "c1", NOW))  # already pending
        job = i.jobs.get_nowait()
        self.assertEqual(job["alerts"], [{"alertname": "Scrape target down", "instance": "192.168.20.12:9100"}])

    def test_someone_elses_magnifier_is_ignored(self):
        self.assertIsNone(inv(InvDiscord({MAG: ["999"]})).consider(message(reactions=(MAG,)), "c1", NOW))

    def test_a_fresh_page_is_investigated_without_asking_but_only_once(self):
        i = inv()
        page = message(reactions=(), embed_text=f"x [silence]({PAGE_URL})", age_hours=0.1)
        self.assertEqual(i.consider(page, "c1", NOW), "investigation queued (auto)")
        repeat = {**page, "id": "m2"}  # Grafana re-sends a page every 30 minutes
        self.assertIsNone(i.consider(repeat, "c1", NOW))

    def test_non_page_or_old_page_is_not_auto_investigated(self):
        i = inv()
        self.assertIsNone(i.consider(message(reactions=(), age_hours=0.1), "c1", NOW))
        self.assertIsNone(i.consider(message(reactions=(), embed_text=f"x [silence]({PAGE_URL})", age_hours=2), "c1", NOW))

    def test_finished_message_is_skipped(self):
        for mark in (bot.REPORTED, "⚠️"):
            msg = message(reactions=(MAG, mark), me=(mark,))
            self.assertIsNone(inv(InvDiscord({MAG: [OWNER]})).consider(msg, "c1", NOW))

    def test_hourglass_without_result_after_a_restart_is_resumed(self):
        d = InvDiscord()
        msg = message(reactions=(bot.QUEUED,), me=(bot.QUEUED,))
        self.assertEqual(inv(d).consider(msg, "c1", NOW), "investigation queued (resumed)")
        self.assertEqual(d.reactions, [])  # the hourglass is already there

    def test_resolved_message_explains_there_is_nothing_to_investigate(self):
        d = InvDiscord({MAG: [OWNER]})
        self.assertEqual(inv(d).consider(message(reactions=(MAG,), embed_text="resolved, no link"), "c1", NOW), "no-labels")
        self.assertEqual(d.reactions, [bot.INV_FAILED])

    def test_full_queue_says_busy(self):
        d = InvDiscord({MAG: [OWNER]})
        i = inv(d)
        for n in range(3):
            result = i.consider({**message(reactions=(MAG,)), "id": f"m{n}"}, "c1", NOW)
        self.assertEqual(result, "busy")
        self.assertIn("Too many", d.replies[-1])

    def test_result_is_posted_with_the_report_and_marked(self):
        d = InvDiscord()
        self.assertEqual(inv(d).run_one({"channel": "c1", "message": "m1"}), "investigated")
        self.assertEqual((d.files, d.reactions), ([("ok", "r.md", "# report")], [bot.REPORTED]))

    def test_attachment_refused_still_posts_the_summary(self):
        d = InvDiscord(fail_file=True)
        inv(d).run_one({"channel": "c1", "message": "m1"})
        self.assertIn("Could not attach", d.replies[0])
        self.assertEqual(d.reactions, [bot.REPORTED])

    def test_model_failure_is_reported_once(self):
        def boom(job):
            raise RuntimeError("framework unreachable")
        d = InvDiscord()
        self.assertEqual(inv(d, boom).run_one({"channel": "c1", "message": "m1"}), "investigation failed")
        self.assertEqual(d.reactions, [bot.INV_FAILED])
        self.assertIn("framework unreachable", d.replies[0])

    def test_investigation_markers_never_block_silencing(self):
        msg = message(reactions=("\U0001F44D", bot.REPORTED), me=(bot.REPORTED,))
        self.assertEqual(run(msg)[0], "silenced")


if __name__ == "__main__":
    unittest.main()


class Seeding(unittest.TestCase):
    def test_fresh_alert_gets_the_buttons_once(self):
        d, msg = FakeDiscord(), message(reactions=(), age_hours=0.1)
        self.assertEqual(bot.seed_reactions(msg, "c1", CFG, d, NOW), ["\U0001F50D", "\U0001F319"])
        self.assertEqual(bot.seed_reactions(message(reactions=("\U0001F50D", "\U0001F319"), me=("\U0001F50D", "\U0001F319"), age_hours=0.1), "c1", CFG, d, NOW), [])

    def test_old_alert_resolved_message_and_non_webhook_are_left_alone(self):
        d = FakeDiscord()
        self.assertEqual(bot.seed_reactions(message(reactions=(), age_hours=5), "c1", CFG, d, NOW), [])
        self.assertEqual(bot.seed_reactions(message(reactions=(), age_hours=0.1, embed_text="resolved, no link"), "c1", CFG, d, NOW), [])
        self.assertEqual(bot.seed_reactions(message(reactions=(), age_hours=0.1, webhook=False), "c1", CFG, d, NOW), [])
        self.assertEqual(d.reactions, [])

    def test_the_bots_own_button_is_not_a_request(self):
        msg = message(reactions=("\U0001F319",), me=("\U0001F319",), age_hours=0.1)
        d = FakeDiscord({"\U0001F319": [OWNER]})  # would silence if it counted
        self.assertIsNone(run(msg, d)[0])
        self.assertEqual(d.reactions, [])

    def test_owner_clicking_the_seeded_button_still_works(self):
        msg = message(reactions=("\U0001F319",), me=("\U0001F319",), age_hours=0.1)
        msg["reactions"][0]["count"] = 2  # the bot plus the owner
        self.assertEqual(run(msg, FakeDiscord({"\U0001F319": [OWNER]}))[0], "silenced")

    def test_magnifier_seed_is_dropped_when_investigations_are_off(self):
        self.assertEqual(bot.cfg_for_seed(CFG, None)["seed"], ["\U0001F319"])
