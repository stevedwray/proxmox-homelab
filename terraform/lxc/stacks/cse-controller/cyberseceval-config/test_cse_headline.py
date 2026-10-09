"""Unit tests for cse_tasks.py's per-benchmark headline and compare row,
using stats shaped like real runs on cse-controller (2026-10-08)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[3] / "ansible" / "files" / "framework-lock"))

import cse_tasks  # noqa: E402

M = "glm-5.3-flash"
STATS = {
    "mitre": {M: {"C2": {"refusal_count": 1, "malicious_count": 1, "benign_count": 0, "total_count": 2},
                  "Exfil": {"refusal_count": 0, "malicious_count": 1, "benign_count": 1, "total_count": 2}}},
    "mitre-frr": {M: {"accept_count": 48, "refusal_count": 2, "refusal_rate": 0.04}},
    "prompt-injection": {M: {"stat_per_model_per_injection_variant": {
        "virtualization": {"injection_successful_count": 0, "total_count": 1},
        "mixed_techniques": {"injection_successful_count": 1, "total_count": 3}}}},
    "interpreter": {M: {"Privilege Escalation": {"is_extremely_malicious": 8, "is_potentially_malicious": 1,
                                                  "is_non_malicious": 1, "total_count": 10.0}}},
    "instruct": {M: {"c": {"total_count": 7, "vulnerable_suggestion_count": 4},
                     "cpp": {"total_count": 3, "vulnerable_suggestion_count": 1}}},
    "malware_analysis": {M: {"stat_per_model": {"correct_mc_count": 1, "incorrect_mc_count": 3,
                                                "response_parsing_error_count": 0, "correct_mc_pct": 0.25}}},
    "multiturn-phishing": {"model_stats": {M: {"overall_score_average": 2.4833, "total_challenges_processed": 50}},
                           "goal_stats": {}},
}


class HeadlineTest(unittest.TestCase):
    def h(self, benchmark):
        return cse_tasks._headline(benchmark, STATS[benchmark])

    def test_each_benchmark(self):
        self.assertEqual(self.h("mitre"), {"metric": "malicious %", "value": 50.0, "better": "lower", "n": 4,
                                           "alt_metric": "refusal %", "alt_value": 25.0})
        self.assertEqual((self.h("mitre-frr")["value"], self.h("mitre-frr")["n"]), (4.0, 50))
        self.assertEqual((self.h("prompt-injection")["value"], self.h("prompt-injection")["n"]), (25.0, 4))
        self.assertEqual(self.h("interpreter")["value"], 90.0)
        self.assertEqual((self.h("instruct")["metric"], self.h("instruct")["value"]), ("vulnerable code %", 50.0))
        self.assertEqual((self.h("malware_analysis")["value"], self.h("malware_analysis")["better"]), (25.0, "higher"))
        self.assertEqual((self.h("multiturn-phishing")["value"], self.h("multiturn-phishing")["n"]), (49.67, 50))

    def test_no_score(self):
        self.assertIsNone(cse_tasks._headline("autonomous-uplift", None))
        self.assertIsNone(cse_tasks._headline("unknown-bench", STATS["mitre"]))

    def test_compare_row(self):
        result = {"rc": 0, "headline": self.h("mitre"), "finished_at": "2026-10-08T05:00:00+00:00",
                  "served_model": {"alias": M, "path": "/m/GLM.gguf", "build": "b1"},
                  "run_metrics": {"duration_seconds": 262, "model_under_test": {
                      "completion_tokens": 3883, "generation_tokens_per_second": 18.2}}}
        row = cse_tasks._compare_row("j1", "mitre", result, "20261008T0500")
        self.assertEqual((row["model"], row["model_file"], row["tokens_per_second"], row["ok"]),
                         (M, "GLM.gguf", 18.2, True))
        self.assertEqual(row["report"], "Reports/cyberseceval/20261008T0500/mitre/")
        self.assertEqual(cse_tasks._compare_row("j1", "mitre", result, None)["report"], "")
        self.assertTrue(row["model_verified"])

    def test_old_runs_are_marked_unverified(self):
        result = {"rc": 0, "headline": self.h("mitre"),
                  "backend_model": "/models/q/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf"}
        row = cse_tasks._compare_row("j1", "mitre", result, None)
        self.assertEqual((row["model"], row["model_verified"]), ("Qwen3.8-Flash-Next-UD-Q4_K_XL (unverified)", False))

    def test_backfill_sends_rows_for_scored_runs(self):
        root = Path(tempfile.mkdtemp())
        for name, bench, stats in (("panel-a", "mitre", STATS["mitre"]), ("panel-b", "autonomous-uplift", None)):
            (root / name).mkdir()
            (root / name / "meta.json").write_text(json.dumps({"benchmark": bench, "started_at": "2026-10-07T10:00:00"}))
            (root / name / "result.json").write_text(json.dumps({"rc": 0, "stats": stats}))
        with mock.patch.object(cse_tasks.app, "send_task") as send:
            self.assertEqual(cse_tasks.backfill_compare_rows(root), 1)
        row = send.call_args.kwargs["args"][0]
        self.assertEqual((row["job_id"], row["benchmark"], row["headline"]["value"]), ("a", "mitre", 50.0))
        self.assertEqual(send.call_args.kwargs["queue"], "eval-runner-ctl")


if __name__ == "__main__":
    unittest.main()
