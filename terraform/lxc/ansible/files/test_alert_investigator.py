import json
import unittest
import urllib.parse
from typing import ClassVar

import alert_investigator as ai

CFG = {
    "victoriametrics_url": "http://vm", "grafana_url": "http://grafana", "grafana_token": "g",
    "graylog_url": "http://graylog/api", "graylog_token": "t",
    "opensearch_url": "https://os", "opensearch_user": "u", "opensearch_password": "p", "opensearch_verify_tls": False,
}
RULES = {"data": {"groups": [{"rules": [{
    "uid": "homelab-target-down", "name": "Scrape target down", "state": "firing", "health": "ok",
    "query": "up < 1", "labels": {"severity": "critical"},
    "alerts": [{"state": "Alerting", "activeAt": "2026-10-29T05:00:00Z", "value": "0", "labels": {"instance": "x:9100"},
                "annotations": {"summary": "x is down"}}],
}]}]}}


class FakeHttp:
    """Stands in for Http: records every request and answers from a path-prefix table."""

    calls: ClassVar[list] = []
    answers: ClassVar[dict] = {}

    def __init__(self, base, headers=None, verify_tls=True, timeout=30):
        self.base, self.headers = base, headers or {}

    def request(self, method, path, body=None):
        FakeHttp.calls.append((self.base, method, path, body))
        for prefix, answer in FakeHttp.answers.items():
            if (self.base + path).startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer(path, body) if callable(answer) else answer
        return None


def tools(**answers):
    FakeHttp.calls, FakeHttp.answers = [], answers
    return ai.Tools(CFG, http=FakeHttp)


class FakeLlm:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def loaded_model(self):
        return "glm-test"

    def chat(self, messages, tools, max_tokens=8192):
        self.seen.append((list(messages), tools))
        return self.replies.pop(0)


def call(name, args, cid="c1"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


FINAL = "SUMMARY: The node exporter on x stopped after a SIGHUP.\nSEVERITY: needs-attention\n\n## What fired\nx"


class Redaction(unittest.TestCase):
    def test_key_value_secrets_and_bearer_tokens_are_hidden(self):
        text = 'password=hunter2 api_key: "abc123" Authorization: Bearer abcdefghijkl token=xyz'
        got = ai.redact(text)
        for secret in ("hunter2", "abc123", "abcdefghijkl", "xyz"):
            self.assertNotIn(secret, got)

    def test_discord_webhook_hidden(self):
        self.assertNotIn("abc/def", ai.redact("see https://discord.com/api/webhooks/abc/def now"))

    def test_digests_are_kept(self):
        digest = "sha256:" + "a" * 64
        self.assertIn(digest, ai.redact(f"image {digest}"))


class ToolsTests(unittest.TestCase):
    def test_tool_list_shrinks_without_graylog_or_opensearch(self):
        t = ai.Tools({**CFG, "graylog_token": "", "opensearch_password": ""}, http=FakeHttp)
        names = {s["function"]["name"] for s in t.specs()}
        self.assertEqual(names, {"query_metrics", "host_overview", "alert_rule", "firing_alerts"})
        self.assertIn("no tool named", t.run("search_logs", {"query": "x"}))

    def test_unknown_tool_and_bad_arguments_are_errors_not_crashes(self):
        t = tools()
        self.assertTrue(t.run("rm_rf", {}).startswith("error"))
        self.assertTrue(t.run("query_metrics", {"nope": 1}).startswith("error"))
        self.assertTrue(t.run("query_metrics", {"promql": ""}).startswith("error"))

    def test_instant_query(self):
        t = tools(**{"http://vm/api/v1/query?": {"data": {"result": [{"metric": {"__name__": "up", "stack": "a"}, "value": [0, "1"]}]}}})
        self.assertEqual(t.run("query_metrics", {"promql": "up"}), 'up{stack="a"} = 1')

    def test_range_query_summarises_and_caps_the_window(self):
        values = [[1761710400 + 60 * i, str(i)] for i in range(40)]
        t = tools(**{"http://vm/api/v1/query_range?": {"data": {"result": [{"metric": {"__name__": "x"}, "values": values}]}}})
        out = t.run("query_metrics", {"promql": "x", "hours": 9999})
        self.assertIn("min=0 max=39 last=39", out)
        query = urllib.parse.parse_qs(FakeHttp.calls[0][2].split("?", 1)[1])
        self.assertEqual(int(query["end"][0]) - int(query["start"][0]), 168 * 3600)

    def test_output_is_clipped(self):
        rows = [{"metric": {"__name__": "m", "i": str(i) * 200}, "value": [0, "1"]} for i in range(30)]
        t = tools(**{"http://vm/api/v1/query?": {"data": {"result": rows}}})
        self.assertLess(len(t.run("query_metrics", {"promql": "m"})), ai.TOOL_OUTPUT_LIMIT + 100)

    def test_alert_rule_by_title_or_uid(self):
        t = tools(**{"http://grafana/api/prometheus": RULES})
        for name in ("Scrape target down", "homelab-target-down"):
            out = t.run("alert_rule", {"name": name})
            self.assertIn("query: up < 1", out)
            self.assertIn("x is down", out)
        self.assertIn("no rule", t.run("alert_rule", {"name": "other"}))

    def test_log_search_uses_graylog_simple_search_and_bounds(self):
        answer = {"schema": [{"field": "timestamp"}, {"field": "source"}, {"field": "relay_src_ip"}, {"field": "message"}],
                  "datarows": [["2026-10-29T05:00:00Z", "proxy", "192.168.30.10", "token=abc connection refused"]]}
        t = tools(**{"http://graylog/api/search/messages": answer})
        out = t.run("search_logs", {"query": "source:proxy", "minutes": 99999, "limit": 500})
        self.assertIn("connection refused", out)
        self.assertNotIn("abc", out)  # redacted
        body = FakeHttp.calls[0][3]
        self.assertEqual((body["timerange"]["range"], body["size"]), (1440 * 60, 50))

    def test_harbor_findings_filters(self):
        hit = {"finding_id": "CVE-2026-1", "cvss_score": 9.8, "package": "openssl", "package_version": "3.0", "fixed_version": "3.1",
               "artifact": {"project": "dockerhub", "repository": "library/nginx", "tag": "1", "stack": "proxy-stack",
                            "in_production": True, "in_use": True}}
        t = tools(**{"https://os/harbor-findings*/_search": {"hits": {"hits": [{"_source": hit}]}}})
        out = t.run("harbor_findings", {"project": "dockerhub", "repository": "library/nginx", "severity": "critical"})
        self.assertIn("CVE-2026-1 cvss=9.8 openssl 3.0 -> fixed 3.1", out)
        must = FakeHttp.calls[0][3]["query"]["bool"]["must"]
        self.assertIn({"term": {"severity_raw": "Critical"}}, must)
        self.assertIn({"term": {"artifact.repository": "library/nginx"}}, must)

    def test_gvm_findings_never_include_pentest_targets(self):
        t = tools(**{"https://os/gvm-findings*/_search": {"hits": {"hits": []}}})
        t.run("gvm_findings", {"task": "weekly-lan"})
        self.assertIn({"term": {"target.pentest_target": True}}, FakeHttp.calls[0][3]["query"]["bool"]["must_not"])

    def test_cve_context_validates_the_id(self):
        t = tools(**{"https://os/unified-cve-exposure*/_search": {"hits": {"hits": [{"_source": {"cve_id": "CVE-2026-12345", "kev_listed": True}}]}},
                     "https://os/cve-remediation-assessment*/_search": {"hits": {"hits": []}}})
        self.assertIn('"kev_listed": true', t.run("cve_context", {"cve_id": "cve-2026-12345"}))
        self.assertIn("not a CVE id", t.run("cve_context", {"cve_id": "rm -rf"}))

    def test_a_failing_datasource_is_reported_to_the_model(self):
        t = tools(**{"http://vm": RuntimeError("GET /api/v1/query -> 503: down")})
        self.assertEqual(t.run("query_metrics", {"promql": "up"}), "error: GET /api/v1/query -> 503: down")

    def test_only_reads(self):
        t = tools(**{"http://": {}})
        for name, args in (("query_metrics", {"promql": "up"}), ("query_metrics", {"promql": "up", "hours": 1}),
                           ("host_overview", {"stack": "a"}), ("alert_rule", {"name": "a"}), ("firing_alerts", {}),
                           ("search_logs", {"query": "a"}), ("harbor_findings", {}), ("gvm_findings", {}),
                           ("cve_context", {"cve_id": "CVE-2026-1"})):
            t.run(name, args)
        for base, method, path, _ in FakeHttp.calls:
            self.assertTrue(method == "GET" or path.endswith(("/_search", "/search/messages")), (method, path))


class Loop(unittest.TestCase):
    def setUp(self):
        self.tools = tools(**{"http://grafana/api/prometheus": RULES, "http://grafana/api/alertmanager": [],
                              "http://vm/api/v1/query?": {"data": {"result": []}}})

    def test_tool_calls_then_answer(self):
        llm = FakeLlm([{"tool_calls": [call("query_metrics", {"promql": "up"})]}, {"content": FINAL}])
        report = ai.investigate([{"alertname": "Scrape target down", "__alert_rule_uid__": "homelab-target-down"}], "msg", self.tools, llm)
        self.assertEqual((report.severity, report.summary), ("needs-attention", "The node exporter on x stopped after a SIGHUP."))
        self.assertEqual([s["tool"] for s in report.steps], ["query_metrics"])
        first_user = llm.seen[0][0][1]["content"]
        self.assertIn("query: up < 1", first_user)  # the rule is looked up before the model starts
        self.assertEqual(llm.seen[1][0][-1], {"role": "tool", "tool_call_id": "c1", "content": "no series"})

    def test_more_than_four_calls_are_cut_everywhere(self):
        llm = FakeLlm([{"tool_calls": [call("firing_alerts", {}, f"c{n}") for n in range(6)]}, {"content": FINAL}])
        ai.investigate([{"alertname": "x"}], "msg", self.tools, llm)
        sent = llm.seen[1][0]
        self.assertEqual(len(sent[-5]["tool_calls"]), 4)  # every listed call has its answer
        self.assertEqual([m["tool_call_id"] for m in sent[-4:]], ["c0", "c1", "c2", "c3"])

    def test_grouped_alerts_look_up_their_rule_once(self):
        llm = FakeLlm([{"content": FINAL}])
        ai.investigate([{"alertname": "Scrape target down", "instance": str(n)} for n in range(3)], "msg", self.tools, llm)
        self.assertEqual(sum(1 for c in FakeHttp.calls if "/api/prometheus" in c[2]), 1)

    def test_step_limit_forces_a_final_answer_without_tools(self):
        llm = FakeLlm([{"tool_calls": [call("firing_alerts", {})]}] * 3 + [{"content": FINAL}])
        report = ai.investigate([{"alertname": "x"}], "msg", self.tools, llm, max_steps=3)
        self.assertEqual(len(report.steps), 3)
        self.assertIsNone(llm.seen[-1][1])

    def test_deadline_stops_the_loop(self):
        ticks = iter([0, 0, 1000, 1000])
        llm = FakeLlm([{"tool_calls": [call("firing_alerts", {})]}, {"content": FINAL}])
        report = ai.investigate([{"alertname": "x"}], "msg", self.tools, llm, deadline_seconds=10, clock=lambda: next(ticks))
        self.assertEqual(len(report.steps), 1)

    def test_bad_json_arguments_go_back_to_the_model(self):
        bad = {"id": "c1", "function": {"name": "query_metrics", "arguments": "{not json"}}
        llm = FakeLlm([{"tool_calls": [bad]}, {"content": FINAL}])
        report = ai.investigate([{"alertname": "x"}], "msg", self.tools, llm)
        self.assertIn("not a JSON object", report.steps[0]["result"])

    def test_empty_report_is_an_error(self):
        llm = FakeLlm([{"content": ""}, {"content": ""}])
        with self.assertRaises(RuntimeError):
            ai.investigate([{"alertname": "x"}], "msg", self.tools, llm)

    def test_missing_shape_still_gives_a_report(self):
        self.assertEqual(ai.parse_answer("just prose"), ("No summary line; see the attached report.", "unclear"))
        self.assertEqual(ai.parse_answer("**SUMMARY:** a\n**SEVERITY:** Noise")[1], "noise")

    def test_rendered_report_lists_the_evidence(self):
        report = ai.Report("s", "noise", FINAL, "glm", [{"tool": "query_metrics", "args": {"promql": "up"}, "result": "```x```"}])
        from datetime import datetime, timezone
        md = ai.render_markdown(report, "🔴 Scrape target down", datetime(2026, 10, 29, tzinfo=timezone.utc))
        self.assertIn("model `glm`", md)
        self.assertIn('### 1. `query_metrics` {"promql": "up"}', md)
        self.assertEqual(md.count("```"), 2)  # tool output cannot break out of its fence


if __name__ == "__main__":
    unittest.main()
