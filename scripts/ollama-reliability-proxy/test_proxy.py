"""Unit tests for the Ollama reliability proxy's response encodings."""

import importlib.util
import json
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("proxy.py")
SPEC = importlib.util.spec_from_file_location("ollama_reliability_proxy", MODULE_PATH)
assert SPEC and SPEC.loader
PROXY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROXY)


class NativeOllamaStreamingTests(unittest.TestCase):
    def test_ndjson_wrap_emits_one_parseable_native_response(self):
        completion = {
            "model": "laguna-s-2.1:q4_k_m",
            "message": {"role": "assistant", "content": "Current answer."},
            "done": True,
            "done_reason": "stop",
        }

        lines = PROXY.ndjson_wrap(completion).decode("utf-8").splitlines()

        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), completion)

    def test_native_response_is_checked_for_degenerate_content(self):
        self.assertEqual(PROXY.is_degenerate({"content": ""}, "stop"), "empty content")


if __name__ == "__main__":
    unittest.main()
