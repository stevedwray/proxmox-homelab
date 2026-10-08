"""Unit tests for cse_tasks.py's run metrics (usage.jsonl -> report)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
sys.path.insert(0, str(Path(__file__).parent))
# Deployed next to cse_tasks.py; in the repo it lives with the playbooks' files.
sys.path.insert(0, str(Path(__file__).parents[3] / "ansible" / "files" / "framework-lock"))

import cse_tasks  # noqa: E402

MUT = "/models/qwen3.8-flash-next-q4/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf"


def _write_log(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


class RunMetricsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.log = self.dir / cse_tasks.USAGE_LOG_NAME
        _write_log(self.log, [
            {"model": MUT, "elapsed_s": 500.0, "prompt_tokens": 1000, "completion_tokens": 12000,
             "finish_reason": "stop",
             "timings": {"prompt_n": 1000, "prompt_ms": 2000.0, "predicted_n": 12000, "predicted_ms": 500000.0}},
            {"model": MUT, "elapsed_s": 2800.0, "prompt_tokens": 1200, "completion_tokens": 65536,
             "finish_reason": "length",
             "timings": {"prompt_n": 1200, "prompt_ms": 2400.0, "predicted_n": 65536, "predicted_ms": 2797000.0}},
            {"model": "gpt-4o-mini", "elapsed_s": 3.2, "prompt_tokens": 800, "completion_tokens": 50,
             "finish_reason": "stop", "timings": None},
        ])
        self.metrics = cse_tasks._run_metrics(
            self.log, MUT, "2026-10-07T05:07:37+00:00", "2026-10-07T06:02:40+00:00"
        )

    def test_splits_model_under_test_from_judge(self):
        mut = self.metrics["model_under_test"]
        self.assertEqual(mut["calls"], 2)
        self.assertEqual(mut["completion_tokens"], 77536)
        self.assertEqual(mut["max_completion_tokens"], 65536)
        self.assertEqual(mut["hit_token_limit"], 1)
        self.assertEqual(self.metrics["judge"]["calls"], 1)
        self.assertNotIn("generation_tokens_per_second", self.metrics["judge"])

    def test_speeds_come_from_server_timings(self):
        mut = self.metrics["model_under_test"]
        self.assertEqual(mut["generation_tokens_per_second"], round(77536 / 3297.0, 1))
        self.assertEqual(mut["prompt_tokens_per_second"], round(2200 / 4.4, 1))

    def test_duration(self):
        self.assertEqual(self.metrics["duration_seconds"], 3303.0)
        self.assertEqual(cse_tasks._format_duration(3303.0), "55m 3s")
        self.assertEqual(cse_tasks._format_duration(3725), "1h 2m 5s")

    def test_headline_and_section(self):
        headline = cse_tasks._metrics_headline(self.metrics)
        self.assertIn("55m 3s total", headline)
        self.assertIn("77,536 tokens generated over 2 call(s)", headline)
        self.assertIn("1 answer(s) cut off at the token limit", headline)
        section = "\n".join(cse_tasks._render_metrics_section(self.metrics))
        self.assertIn("| | Model under test | Judge / expansion (cloud) |", section)
        self.assertIn("| Generated tokens (incl. reasoning) | 77,536 | 50 |", section)
        self.assertIn("| Generation speed (tokens/s) | 23.5 | – |", section)

    def test_missing_log_still_gives_duration(self):
        metrics = cse_tasks._run_metrics(self.dir / "absent.jsonl", MUT, "2026-10-07T05:00:00+00:00", "2026-10-07T05:00:30+00:00")
        self.assertEqual(metrics, {"duration_seconds": 30.0})
        self.assertIn("No model calls were recorded.", cse_tasks._render_metrics_section(metrics))

    def test_old_runs_without_metrics(self):
        self.assertIsNone(cse_tasks._metrics_headline(None))
        self.assertEqual(cse_tasks._render_metrics_section(None), ["Not recorded for this run."])


if __name__ == "__main__":
    unittest.main()
