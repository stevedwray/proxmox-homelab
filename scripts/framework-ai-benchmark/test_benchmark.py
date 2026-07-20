#!/usr/bin/env python3
import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("benchmark.py")
SPEC = importlib.util.spec_from_file_location("framework_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
bench = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bench
SPEC.loader.exec_module(bench)


class GraderTests(unittest.TestCase):
    def test_task_matrix_has_all_requested_suites(self):
        tasks = bench.build_tasks(smoke=False)
        self.assertEqual(len(tasks), 17)
        self.assertEqual({task.suite for task in tasks}, set(bench.SUITES))

    def test_security_grader_distinguishes_safe_and_vulnerable(self):
        vulnerable = bench.security_grader("vulnerable", {"CWE-347"})(
            json.dumps({
                "verdict": "vulnerable",
                "cwes": ["CWE-347"],
                "evidence": ["HS256 accepts the public key as an HMAC secret"],
                "remediation": "Restrict validation to RS256 only.",
            })
        )
        safe = bench.security_grader("safe", set())(
            '<think>check carefully</think>\n{"verdict":"safe","cwes":[],"evidence":[],"remediation":"No change required."}'
        )
        self.assertTrue(vulnerable["passed"])
        self.assertTrue(safe["passed"])

    def test_chat_graders_accept_live_format_variants_and_correct_math(self):
        context = (
            "Orchard can use Python's json module to read a JSON file into a dictionary. "
            "What directory should hold the configuration?"
        )
        incident = "\n".join([
            "• Diagnosis: The payments-api database pool change caused connection exhaustion, matching the sharp checkout error increase seven minutes after deployment.",
            "• Mitigation: Roll back to the known-good release immediately, freeze further changes, and keep an incident commander coordinating the response.",
            "• Verification: Confirm checkout errors return to the 0.2 percent baseline and database pool utilization remains healthy under representative traffic.",
            "• Communication: Notify affected customers, acknowledge checkout failures, provide the mitigation status, and publish another update after recovery is verified.",
        ])
        schedule = "Tuesday 22:30 + 11 hours = Wednesday 09:30; + 27 hours = Thursday 12:30; + 90 minutes = Thursday 14:00."
        self.assertTrue(bench.grade_context_chat(context)["passed"])
        self.assertTrue(bench.grade_incident_chat(incident)["passed"])
        self.assertTrue(bench.grade_reasoning_chat(schedule)["passed"])

    def test_code_grader_executes_hidden_tests(self):
        response = """```python
def merge_intervals(intervals):
    for start, end in intervals:
        if start > end:
            raise ValueError("reversed")
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged
```"""
        grade = bench.code_grader({"merge_intervals"}, bench.MERGE_TESTS)(response)
        self.assertTrue(grade["passed"], grade)

    def test_code_grader_rejects_imports_without_execution(self):
        response = """```python
import os
def merge_intervals(intervals):
    os.remove('/storage')
    return []
```"""
        grade = bench.code_grader({"merge_intervals"}, bench.MERGE_TESTS)(response)
        self.assertFalse(grade["passed"])
        self.assertRegex(grade["checks"][0]["detail"], r"unsafe|disallowed")


class SelectionTests(unittest.TestCase):
    def test_task_specific_model_selection_and_eligibility(self):
        inventory = {
            "llamacpp": [
                {"id": "Llama-3.3-70B-Instruct-Q4_K_M"},
                {"id": "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M"},
                {"id": "DeepSeek-R1-Distill-Qwen-32B-Q4_K_M"},
            ],
            "lmstudio": [{"id": "qwen3-coder-30b-phase6"}],
            "ollama": [{"name": "qwen2.5:0.5b", "details": {"parameter_size": "494.03M"}}],
        }
        selected, warnings = bench.choose_models(inventory)
        self.assertEqual(selected[("llamacpp", "chat")]["id"], "Llama-3.3-70B-Instruct-Q4_K_M")
        self.assertEqual(selected[("llamacpp", "code_generation")]["id"], "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M")
        self.assertEqual(selected[("llamacpp", "security")]["id"], "DeepSeek-R1-Distill-Qwen-32B-Q4_K_M")
        self.assertFalse(selected[("ollama", "security")]["quality_eligible"])
        self.assertTrue(any("smoke-only" in warning for warning in warnings))


class EvidenceTests(unittest.TestCase):
    def test_results_paths_are_confined(self):
        with self.assertRaises(ValueError):
            bench.validate_results_root("/etc/framework-bench")
        allowed = str(Path.home() / "framework-ai-benchmark-results" / "unit-tests")
        self.assertTrue(bench.validate_results_root(allowed).is_relative_to(bench.Path.home()))

    def test_resource_summary_includes_levels_and_counter_deltas(self):
        samples = [
            {"cpu_busy_percent": 10.0, "memory_used_bytes": 100, "network_rx_bytes": 1000},
            {"cpu_busy_percent": 50.0, "memory_used_bytes": 140, "network_rx_bytes": 1250},
        ]
        summary = bench.summarize_samples(samples)
        self.assertEqual(summary["cpu_busy_percent"]["max"], 50.0)
        self.assertEqual(summary["memory_used_bytes"]["mean"], 120.0)
        self.assertEqual(summary["network_rx_bytes"]["delta"], 250)

    def test_error_signatures_and_cloud_corpus_separation(self):
        anomalies = bench.find_anomalies({"output": "amdgpu ring timeout; GPU reset scheduled"})
        self.assertEqual(len(anomalies), 1)
        record = {
            "runtime": "llamacpp", "model": "model", "quality_eligible": True,
            "suite": "chat", "task": "task", "repetition": 1, "seed": 1001,
            "request": {"prompt": "hello"}, "response_text": "hi", "request_ok": True,
            "grade": {"score": 1.0}, "performance": {"wall_seconds": 1.0},
            "kernel_logs": "must not be exported",
        }
        exported = bench.evaluation_record(record)
        self.assertEqual(exported["output"], "hi")
        self.assertNotIn("kernel_logs", exported)


if __name__ == "__main__":
    unittest.main()
