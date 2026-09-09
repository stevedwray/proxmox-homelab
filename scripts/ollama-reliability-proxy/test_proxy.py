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


class RepetitionCollapseTests(unittest.TestCase):
    """2026-09-09: a live Gemma4 response of `<unused49>` repeated ~30 times
    (Gemma's reserved-vocab placeholder token) sailed straight through the
    original '?'-only check. is_degenerate() now generalizes to any short
    unit collapsing into a repeated loop -- these cases are the real
    transcripts (or close analogs) that motivated it."""

    def test_flags_real_gemma_unused_token_corruption(self):
        content = "<unused49>" * 60
        reason = PROXY.is_degenerate({"content": content}, "stop")
        self.assertIsNotNone(reason)
        self.assertIn("repetition collapse", reason)

    def test_flags_question_mark_flood_the_same_as_before(self):
        content = "?" * 100
        reason = PROXY.is_degenerate({"content": content}, "stop")
        self.assertIsNotNone(reason)

    def test_flags_repeated_sentence_corruption(self):
        content = "I'll create a Python script in the Qwen3.6 directory that prints Hello, World.\n\n" * 5
        reason = PROXY.is_degenerate({"content": content}, "stop")
        self.assertIsNotNone(reason)

    def test_does_not_flag_normal_prose(self):
        content = (
            "The user asked to read the file and tell them what it says. I used "
            "read_file with the given path and the result shows the file contains "
            "some text. I should answer based on this information, summarizing it "
            "clearly and concisely for the user to understand quickly."
        )
        self.assertIsNone(PROXY.is_degenerate({"content": content}, "stop"))

    def test_does_not_flag_real_code(self):
        content = (
            "def fibonacci(n):\n"
            "    if n <= 1:\n"
            "        return n\n"
            "    a, b = 0, 1\n"
            "    for _ in range(2, n + 1):\n"
            "        a, b = b, a + b\n"
            "    return b\n\n"
            "for i in range(10):\n"
            "    print(fibonacci(i))\n"
        )
        self.assertIsNone(PROXY.is_degenerate({"content": content}, "stop"))

    def test_does_not_flag_legitimate_numbered_list(self):
        content = "\n".join(f"- Item number {i} in the list of things to do today" for i in range(20))
        self.assertIsNone(PROXY.is_degenerate({"content": content}, "stop"))

    def test_does_not_flag_short_normal_answer(self):
        self.assertIsNone(PROXY.is_degenerate({"content": 'print("Hello, World")'}, "stop"))


class PayloadShapeTests(unittest.TestCase):
    """2026-09-09: added alongside repetition-collapse detection so a real
    degenerate-response log line carries a comparable signature (message/
    role counts, character volume, tool schema size) instead of just the
    reason string -- content is never logged here, only structure."""

    def test_counts_messages_and_roles(self):
        body = {
            "messages": [
                {"role": "system", "content": "You are an assistant."},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ],
            "tools": [],
        }
        shape = PROXY.payload_shape(body)
        self.assertEqual(shape["message_count"], 3)
        self.assertEqual(shape["role_counts"], {"system": 1, "user": 1, "assistant": 1})
        self.assertEqual(shape["total_message_chars"], len("You are an assistant.") + len("hello") + len("hi there"))
        self.assertEqual(shape["tool_count"], 0)
        self.assertEqual(shape["tools_schema_chars"], 0)

    def test_counts_tool_schema_size_and_tool_call_arguments(self):
        body = {
            "messages": [
                {"role": "user", "content": "do it"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "create_file", "arguments": '{"filePath":"a.py"}'}}
                    ],
                },
            ],
            "tools": [{"type": "function", "function": {"name": "create_file", "parameters": {}}}],
        }
        shape = PROXY.payload_shape(body)
        self.assertEqual(shape["message_count"], 2)
        self.assertEqual(shape["tool_count"], 1)
        self.assertGreater(shape["tools_schema_chars"], 0)
        self.assertGreater(shape["total_message_chars"], len("do it"))

    def test_handles_empty_payload(self):
        self.assertEqual(
            PROXY.payload_shape({}),
            {"message_count": 0, "role_counts": {}, "total_message_chars": 0, "tool_count": 0, "tools_schema_chars": 0},
        )


if __name__ == "__main__":
    unittest.main()
