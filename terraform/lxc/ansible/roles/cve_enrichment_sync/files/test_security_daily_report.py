"""Unit tests for security_daily_report.py (no network)."""
import unittest
from datetime import datetime, timedelta, timezone

import security_daily_report as r

NOW = datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc)
SINCE = NOW - timedelta(hours=24)


class FakeClient:
    """Answers searches from a dict of index -> list of canned results,
    consumed in call order."""

    def __init__(self, answers):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.calls = []

    def search(self, index, body):
        self.calls.append((index, body))
        queue = self.answers.get(index)
        return queue.pop(0) if queue else None


def agg_result(total, **aggs):
    return {"hits": {"total": {"value": total}, "hits": []}, "aggregations": aggs}


def terms(**counts):
    return {"buckets": [{"key": k, "doc_count": v} for k, v in counts.items()]}


class NormalizeSeverityTests(unittest.TestCase):
    def test_folds_case_and_merges(self):
        self.assertEqual(
            r.normalize_severity({"Critical": 2, "critical": 1, "High": 4, "": 1}),
            {"critical": 3, "high": 4, "unknown": 1},
        )


class FreshnessTests(unittest.TestCase):
    def test_fresh(self):
        row = r.evaluate_freshness(NOW - timedelta(hours=3), 10, 26, NOW)
        self.assertEqual((row["status"], row["age_hours"]), ("fresh", 3.0))

    def test_stale(self):
        self.assertEqual(r.evaluate_freshness(NOW - timedelta(hours=30), 10, 26, NOW)["status"], "stale")

    def test_empty_index_is_missing(self):
        self.assertEqual(r.evaluate_freshness(None, 0, 26, NOW)["status"], "missing")

    def test_collect_reads_epoch_millis_and_errors(self):
        newest_ms = (NOW - timedelta(minutes=5)).timestamp() * 1000
        answers = {spec["index"]: [agg_result(5, newest={"value": newest_ms})] for spec in r.FRESHNESS}
        answers["gvm-findings"] = [None]  # e.g. a 403
        rows = {row["name"]: row for row in r.collect_freshness(FakeClient(answers), NOW)}
        self.assertEqual(rows["tpot"]["status"], "fresh")
        self.assertEqual(rows["greenbone"]["status"], "error")


class FindingsTests(unittest.TestCase):
    def test_collect_and_totals(self):
        harbor = agg_result(
            100,
            by_severity=terms(Critical=5, High=20, Medium=75),
            new={"doc_count": 3, "by_severity": terms(Critical=1, High=2)},
            severe={"doc_count": 25, "by_stack": terms(**{"wazuh-stack": 25}), "by_zone": terms(infra_seg=25)},
        )
        gvm = agg_result(
            10,
            by_severity=terms(High=4, Medium=6),
            new={"doc_count": 0, "by_severity": terms()},
            severe={"doc_count": 4, "by_stack": terms(), "by_zone": terms(lan=4)},
        )
        rows = r.collect_findings(FakeClient({"harbor-findings": [harbor], "gvm-findings": [gvm]}), SINCE)
        by_source = {row["source"]: row for row in rows}
        self.assertFalse(by_source["wazuh"]["ok"])
        self.assertEqual(by_source["harbor"]["severe_by_stack"], {"wazuh-stack": 25})
        self.assertEqual(r.totals(rows), {"critical": 5, "high": 24, "new_critical": 1, "new_high": 2})

    def test_greenbone_excludes_pentest_targets(self):
        client = FakeClient({})
        r.collect_findings(client, SINCE)
        gvm_body = dict(client.calls)["gvm-findings"]
        self.assertIn(
            {"bool": {"must_not": {"term": {"target.pentest_target": True}}}},
            gvm_body["query"]["bool"]["filter"],
        )


class ReportTests(unittest.TestCase):
    def facts(self, freshness_status="fresh"):
        return {
            "totals": {"critical": 5, "high": 24, "new_critical": 1, "new_high": 2},
            "freshness": [
                {"name": "harbor", "status": "fresh"},
                {"name": "wazuh", "status": freshness_status},
            ],
            "cves": {"kev_listed": 3, "poc_available": 7, "top": [
                {"cve_id": "CVE-2026-0001", "risk_score": 91.0, "stacks": ["wazuh-stack"], "triage_raw_text": "x"},
            ]},
            "remediation": {"open": 4},
            "tpot": {"unexpected_sources": 1, "unexpected_connections": 12},
            "stack_risk": [],
        }

    def test_headline_is_deterministic_and_flags_stale(self):
        facts = self.facts("stale")
        line = r.build_headline("2026-10-30", facts["totals"], facts["cves"], facts["tpot"], facts["freshness"])
        self.assertIn("5 critical / 24 high", line)
        self.assertIn("+1 / +2 new", line)
        self.assertIn("1 unexpected source(s), 12 connection(s)", line)
        self.assertIn("check wazuh (stale)", line)

    def test_document_status(self):
        facts = self.facts()
        ok = r.build_document("2026-10-30", NOW, facts, "h", "## Bottom line", None, "m")
        failed = r.build_document("2026-10-30", NOW, facts, "h", None, "timeout", "m")
        facts_only = r.build_document("2026-10-30", NOW, facts, "h", None, None, "")
        self.assertEqual((ok["status"], ok["llm_provider"]), ("ok", "llamacpp"))
        self.assertEqual(failed["status"], "llm_failed")
        self.assertEqual((facts_only["status"], facts_only["llm_provider"]), ("facts_only", "none"))
        # top_cves keeps only the mapped fields, not the raw triage text.
        self.assertNotIn("triage_raw_text", ok["top_cves"][0])
        self.assertEqual(ok["stale_sources"], [])

    def test_prompt_carries_facts_and_guardrails(self):
        prompt = r.build_prompt(self.facts())
        self.assertIn("CVE-2026-0001", prompt)
        self.assertIn("Never invent", prompt)
        self.assertIn("## Threat-model focus", prompt)


if __name__ == "__main__":
    unittest.main()
