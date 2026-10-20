"""Regression tests for task-scoped GVM result collection."""

import os
import unittest
from unittest import mock
from xml.etree import ElementTree as ET

os.environ.setdefault("GVM_BRIDGE_PASSWORD", "test")
import app  # noqa: E402

TASK = "12345678-1234-1234-1234-123456789abc"


class FakeGmp:
    def __init__(self, count):
        self.count = count
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def authenticate(self, *_args):
        pass

    def get_results(self, *, filter_string, details):
        self.calls.append(filter_string)
        terms = dict(term.split("=", 1) for term in filter_string.split())
        assert terms["task_id"] == TASK and details
        first, rows = int(terms["first"]), int(terms["rows"])
        root = ET.Element("results")
        for i in range(first, min(first + rows, self.count + 1)):
            result = ET.SubElement(root, "result", id=str(i))
            ET.SubElement(result, "host").text = "192.168.70.214"
            nvt = ET.SubElement(result, "nvt", oid="nvt.1")
            refs = ET.SubElement(nvt, "refs")
            ET.SubElement(refs, "ref", type="cve", id="CVE-2020-1234")
            ET.SubElement(refs, "ref", type="cve", id="CVE-2020-5678")
        return root


class ScanResultsTests(unittest.TestCase):
    def test_scoped_pagination_and_all_cve_references(self):
        for count, expected_pages in ((0, 1), (500, 2), (501, 2), (1001, 3)):
            with self.subTest(count=count):
                gmp = FakeGmp(count)
                with mock.patch.object(app, "_open_gmp", return_value=gmp):
                    response = app.app.test_client().get(f"/scan/results/{TASK}")
                self.assertEqual(response.status_code, 200)
                body = response.get_json()
                self.assertTrue(body["complete"])
                self.assertEqual(len(body["results"]), count)
                self.assertEqual(body["pages"], expected_pages)
                if count:
                    self.assertEqual(body["results"][0]["cves"], ["CVE-2020-1234", "CVE-2020-5678"])
                    self.assertEqual(body["results"][0]["cve_id"], "CVE-2020-1234")

    def test_rejects_filter_injection(self):
        with mock.patch.object(app, "_open_gmp") as opener:
            response = app.app.test_client().get("/scan/results/not-a-uuid")
        self.assertEqual(response.status_code, 400)
        opener.assert_not_called()

    def test_page_limit_does_not_claim_completeness(self):
        gmp = FakeGmp(100000)
        with mock.patch.object(app, "_open_gmp", return_value=gmp):
            response = app.app.test_client().get(f"/scan/results/{TASK}")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.get_json()["complete"])
        self.assertEqual(len(gmp.calls), 200)


if __name__ == "__main__":
    unittest.main()
