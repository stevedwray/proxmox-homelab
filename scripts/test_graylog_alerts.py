"""Tests for graylog_alerts.py: request bodies, idempotent create/update, and that list mode never writes."""

import contextlib
import io
import unittest

import graylog_alerts as g

WEBHOOKS = {
    "DISCORD_WEBHOOK_CRITICAL": "https://discord.com/api/webhooks/111/critical-token",
    "DISCORD_WEBHOOK_WARNING": "https://discord.com/api/webhooks/222/warning-token",
}


class FakeGraylog:
    """Records calls; keeps notifications and definitions in memory like the real API."""

    def __init__(self, notes=None, defs=None, validate_status=200):
        self.calls, self.validate_status = [], validate_status
        self.notes = {n["title"]: {"id": f"n{i}", "title": n["title"]} for i, n in enumerate(notes or [])}
        self.defs = {d["title"]: {"id": f"d{i}", "title": d["title"]} for i, d in enumerate(defs or [])}

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("/events/notifications"):
            return 200, {"notifications": list(self.notes.values())}
        if method == "GET" and path.startswith("/events/definitions"):
            return 200, {"event_definitions": list(self.defs.values())}
        if method == "POST" and path == "/events/notifications":
            self.notes[body["title"]] = {"id": f"new{len(self.notes)}", "title": body["title"]}
            return 200, self.notes[body["title"]]
        if method == "POST" and path.startswith("/events/definitions/validate"):
            if "id" not in body:  # what the real endpoint does
                return 500, "hexString can not be null"
            return self.validate_status, {"errors": {}, "failed": False} if self.validate_status == 200 else "bad"
        if method == "POST" and path.startswith("/events/definitions"):
            self.defs[body["title"]] = {"id": f"newd{len(self.defs)}", "title": body["title"]}
            return 200, self.defs[body["title"]]
        return 200, {}

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]


def run_quiet(call, mode, env=WEBHOOKS):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        failures = g.run(call, g.load_data(), env, mode)
    return failures, out.getvalue()


class DataTests(unittest.TestCase):
    def test_rules_are_consistent(self):
        data = g.load_data()
        titles = [d["title"] for d in data["definitions"]]
        self.assertEqual(len(titles), len(set(titles)))
        self.assertGreaterEqual(len(titles), 4)

    def test_every_query_excludes_pentest_and_never_uses_edac(self):
        for spec in g.load_data()["definitions"]:
            query = " ".join(spec["query"].split())
            self.assertIn("NOT relay_src_ip:192.168.70.*", query, spec["title"])
            self.assertNotIn("EDAC", query.upper(), spec["title"])
            self.assertNotIn("level:", query, "alert on exact text, never log level")

    def test_critical_rules_go_to_the_critical_channel(self):
        by_title = {d["title"]: d for d in g.load_data()["definitions"]}
        self.assertEqual(by_title["Storage fault in a kernel log"]["notification"], "critical")
        self.assertEqual(by_title["Out-of-memory kill"]["notification"], "warning")


class BodyTests(unittest.TestCase):
    def test_notification_uses_the_discord_slack_endpoint(self):
        spec = g.load_data()["notifications"]["critical"]
        body = g.notification_body(spec, WEBHOOKS)
        self.assertEqual(body["config"]["webhook_url"], WEBHOOKS["DISCORD_WEBHOOK_CRITICAL"] + "/slack")
        self.assertEqual(body["config"]["type"], "slack-notification-v1")

    def test_notification_rejects_a_missing_or_foreign_webhook(self):
        spec = g.load_data()["notifications"]["critical"]
        for env in ({}, {"DISCORD_WEBHOOK_CRITICAL": ""}, {"DISCORD_WEBHOOK_CRITICAL": "https://example.com/hook"}):
            with self.assertRaises(SystemExit):
                g.notification_body(spec, env)

    def test_definition_groups_by_host_and_sets_the_grace_period(self):
        spec = g.load_data()["definitions"][0]
        body = g.definition_body(spec, "abc")
        cfg = body["config"]
        self.assertEqual(cfg["group_by"], ["source"])
        self.assertEqual(body["key_spec"], ["source"])
        self.assertEqual(cfg["search_within_ms"], cfg["execute_every_ms"])
        self.assertEqual(body["notification_settings"]["grace_period_ms"], spec["grace_hours"] * 3_600_000)
        self.assertEqual(body["notifications"], [{"notification_id": "abc"}])
        self.assertEqual(body["storage"][0]["streams"], [g.EVENTS_STREAM])
        self.assertNotIn("\n", cfg["query"])
        self.assertTrue(body["alert"])


class RunTests(unittest.TestCase):
    def test_list_mode_never_writes(self):
        fake = FakeGraylog()
        failures, out = run_quiet(fake, "list")
        self.assertEqual(failures, 0)
        self.assertEqual(fake.writes(), [])
        self.assertIn("MISSING", out)

    def test_apply_creates_notifications_first_then_definitions_with_their_ids(self):
        fake = FakeGraylog()
        failures, _ = run_quiet(fake, "apply")
        self.assertEqual(failures, 0)
        methods = [(m, p.split("?")[0]) for m, p, _ in fake.writes()]
        self.assertEqual(methods[:2], [("POST", "/events/notifications")] * 2)
        self.assertTrue(all(c == ("POST", "/events/definitions") for c in methods[2:]))
        first = next(b for _, p, b in fake.writes() if p.startswith("/events/definitions"))
        self.assertNotEqual(first["notifications"][0]["notification_id"], g.PLACEHOLDER_ID)

    def test_apply_twice_updates_in_place_and_does_not_duplicate(self):
        fake = FakeGraylog()
        run_quiet(fake, "apply")
        before = (len(fake.notes), len(fake.defs))
        fake.calls.clear()
        failures, out = run_quiet(fake, "apply")
        self.assertEqual(failures, 0)
        self.assertEqual((len(fake.notes), len(fake.defs)), before)
        self.assertTrue(all(m == "PUT" for m, _, _ in fake.writes()))
        self.assertIn("updated", out)

    def test_a_failed_notification_stops_apply_before_any_definition(self):
        class RejectsNotifications(FakeGraylog):
            def __call__(self, method, path, body=None):
                if method == "POST" and path == "/events/notifications":
                    self.calls.append((method, path, body))
                    return 400, "unknown field"
                return super().__call__(method, path, body)

        fake = RejectsNotifications()
        failures, out = run_quiet(fake, "apply")
        self.assertGreater(failures, 0)
        self.assertFalse(any(p.startswith("/events/definitions") for _, p, _ in fake.writes()))
        self.assertIn("no event definitions were touched", out)

    def test_validate_saves_nothing_and_reports_rejections(self):
        fake = FakeGraylog()
        failures, _ = run_quiet(fake, "validate")
        self.assertEqual(failures, 0)
        self.assertTrue(all(p.startswith("/events/definitions/validate") for _, p, _ in fake.writes()))
        rejected = FakeGraylog(validate_status=400)
        failures, out = run_quiet(rejected, "validate")
        self.assertEqual(failures, len(g.load_data()["definitions"]))
        self.assertIn("REJECTED", out)

    def test_test_mode_posts_only_to_existing_notifications(self):
        data = g.load_data()
        fake = FakeGraylog(notes=list(data["notifications"].values()))
        failures, _ = run_quiet(fake, "test")
        self.assertEqual(failures, 0)
        self.assertEqual({p for _, p, _ in fake.writes()}, {"/events/notifications/n0", "/events/notifications/n1"})
        failures, out = run_quiet(FakeGraylog(), "test")
        self.assertEqual(failures, 2)
        self.assertIn("run --apply first", out)

    def test_no_webhook_url_is_ever_printed(self):
        for mode in ("list", "validate", "apply", "test"):
            _, out = run_quiet(FakeGraylog(), mode)
            for url in WEBHOOKS.values():
                self.assertNotIn(url, out, mode)
                self.assertNotIn("token", out.lower().replace("token-", ""), mode)


if __name__ == "__main__":
    unittest.main()
