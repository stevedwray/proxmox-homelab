"""Unit tests for the OpenBao seal-status textfile exporter. No network: the opener is faked."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parent / "openbao_health.py"
SPEC = importlib.util.spec_from_file_location("openbao_health", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["openbao_health"] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeOpener:
    def __init__(self, result):
        self.result = result
        self.url = None

    def open(self, url, timeout=0):
        self.url = url
        if isinstance(self.result, Exception):
            raise self.result
        return io.BytesIO(self.result if isinstance(self.result, bytes) else json.dumps(self.result).encode())


class HealthExporterTest(unittest.TestCase):
    def run_main(self, result):
        opener = FakeOpener(result)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(MODULE, "TEXTFILE", Path(d) / "openbao_health.prom"), \
                mock.patch.object(MODULE.ssl, "create_default_context", return_value=None), \
                mock.patch.object(MODULE.urllib.request, "build_opener", return_value=opener):
            code = MODULE.main()
            text = (Path(d) / "openbao_health.prom").read_text()
            leftovers = [p.name for p in Path(d).iterdir() if p.name != "openbao_health.prom"]
        values = {line.split()[0]: int(line.split()[1]) for line in text.splitlines() if not line.startswith("#")}
        return code, values, leftovers, opener.url

    def test_unsealed_reports_up_and_not_sealed(self):
        code, values, leftovers, url = self.run_main({"initialized": True, "sealed": False})
        self.assertEqual((code, values), (0, {"openbao_health_up": 1, "openbao_sealed": 0}))
        self.assertEqual(leftovers, [], "the temporary file is renamed away, never left behind")
        self.assertIn("sealedcode=200", url, "must answer 200 even when sealed so the body can be read")

    def test_sealed_reports_sealed(self):
        _c, values, _l, _u = self.run_main({"initialized": True, "sealed": True})
        self.assertEqual(values, {"openbao_health_up": 1, "openbao_sealed": 1})

    def test_missing_sealed_field_is_treated_as_sealed(self):
        _c, values, _l, _u = self.run_main({"initialized": True})
        self.assertEqual(values["openbao_sealed"], 1)

    def test_unreachable_counts_as_down_and_sealed(self):
        _c, values, _l, _u = self.run_main(OSError("connection refused"))
        self.assertEqual(values, {"openbao_health_up": 0, "openbao_sealed": 1})

    def test_garbage_response_counts_as_down_and_sealed(self):
        _c, values, _l, _u = self.run_main(b"<html>502</html>")
        self.assertEqual(values, {"openbao_health_up": 0, "openbao_sealed": 1})


if __name__ == "__main__":
    unittest.main()
