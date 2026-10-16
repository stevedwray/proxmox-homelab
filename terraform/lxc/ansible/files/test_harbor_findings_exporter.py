"""Tests for the findings.json filters in harbor_findings_exporter.py."""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import types
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "harbor_findings_exporter", pathlib.Path(__file__).with_name("harbor_findings_exporter.py")
)
exporter = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(exporter)

ROWS = [
    {"project": "dockerhub", "repository": "a/b", "severity": "Low", "cve_id": "CVE-3"},
    {"project": "ghcr", "repository": "c/d", "severity": "Critical", "cve_id": "CVE-1"},
    {"project": "dockerhub", "repository": "a/b", "severity": "High", "cve_id": "CVE-2"},
    {"project": "lscr", "repository": "e/f", "severity": "High", "cve_id": "CVE-0"},
    {"project": "ghcr", "repository": "c/d", "severity": "Unknown", "cve_id": "CVE-9"},
]


def _store() -> "exporter.SnapshotStore":
    store = exporter.SnapshotStore()
    store.update_success("", 1.0, list(ROWS))
    return store


class FilterRowsTest(unittest.TestCase):
    def test_no_filters_keeps_everything(self) -> None:
        self.assertEqual(len(exporter.filter_findings_rows(ROWS)), len(ROWS))

    def test_severity_filter_is_case_insensitive(self) -> None:
        got = exporter.filter_findings_rows(ROWS, severities={"critical", "HIGH"})
        self.assertEqual({r["cve_id"] for r in got}, {"CVE-1", "CVE-2", "CVE-0"})

    def test_project_filter(self) -> None:
        got = exporter.filter_findings_rows(ROWS, projects={"ghcr"})
        self.assertEqual({r["cve_id"] for r in got}, {"CVE-1", "CVE-9"})

    def test_most_severe_first_and_limit_keeps_the_worst(self) -> None:
        got = exporter.filter_findings_rows(ROWS, limit=2)
        self.assertEqual([r["cve_id"] for r in got], ["CVE-1", "CVE-2"])

    def test_limit_zero_returns_nothing(self) -> None:
        self.assertEqual(exporter.filter_findings_rows(ROWS, limit=0), [])


class CsvParamTest(unittest.TestCase):
    def test_values_and_whitespace(self) -> None:
        self.assertEqual(exporter._csv_param({"severity": ["Critical, High"]}, "severity"), {"Critical", "High"})

    def test_star_means_no_filter(self) -> None:
        self.assertEqual(exporter._csv_param({"project": ["*"]}, "project"), set())

    def test_missing_or_empty(self) -> None:
        self.assertEqual(exporter._csv_param({}, "project"), set())
        self.assertEqual(exporter._csv_param({"project": [""]}, "project"), set())


class RenderTest(unittest.TestCase):
    def test_default_output_is_unchanged(self) -> None:
        payload = json.loads(_store().render_findings_json())
        self.assertEqual(len(payload["rows"]), len(ROWS))
        self.assertNotIn("total_rows", payload)
        self.assertEqual(payload["rows"], ROWS)

    def test_filtered_output_reports_totals(self) -> None:
        payload = json.loads(_store().render_findings_json({"critical"}, None, None))
        self.assertEqual(payload["total_rows"], len(ROWS))
        self.assertEqual(payload["returned_rows"], 1)
        self.assertEqual(payload["rows"][0]["cve_id"], "CVE-1")


class HandlerTest(unittest.TestCase):
    """Drive do_GET in-process: no sockets, no server."""

    def _get(self, path: str) -> tuple[int, dict | None]:
        handler = exporter.MetricsHandler.__new__(exporter.MetricsHandler)
        handler.path = path
        handler.exporter = types.SimpleNamespace(snapshot=_store())
        handler.wfile = io.BytesIO()
        status: list[int] = []
        handler.send_response = status.append  # type: ignore[method-assign]
        handler.send_header = lambda *_: None  # type: ignore[method-assign]
        handler.end_headers = lambda: None  # type: ignore[method-assign]
        handler.do_GET()
        body = handler.wfile.getvalue()
        return status[0], (json.loads(body) if body else None)

    def test_plain_path_returns_full_feed(self) -> None:
        status, body = self._get("/findings.json")
        self.assertEqual((status, len(body["rows"])), (200, len(ROWS)))

    def test_query_string_filters(self) -> None:
        status, body = self._get("/findings.json?severity=Critical,High&project=*&limit=2")
        self.assertEqual(status, 200)
        self.assertEqual([r["cve_id"] for r in body["rows"]], ["CVE-1", "CVE-2"])  # Critical first, then High by project (dockerhub < lscr)
        self.assertEqual(body["total_rows"], len(ROWS))

    def test_bad_limit_is_a_400(self) -> None:
        self.assertEqual(self._get("/findings.json?limit=abc")[0], 400)
        self.assertEqual(self._get("/findings.json?limit=-1")[0], 400)

    def test_unknown_path_is_a_404(self) -> None:
        self.assertEqual(self._get("/nope?x=1")[0], 404)


if __name__ == "__main__":
    unittest.main()
