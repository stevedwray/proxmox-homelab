"""Unit tests for compare_tab.py and the CyberSecEval charts in app.py."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import app as panel_ui
    import compare_tab
except ImportError:  # dash not installed locally
    panel_ui = compare_tab = None

ROWS = [
    {"Model": "glm", "Task": "IFEval", "Score %": 77.5, "Questions": 40, "Comparable": "no", "Date": "2026-10-08",
     "Source": "eval-runner", "Run": "pilot", "Tokens/s": 17.9},
    {"Model": "glm", "Task": "IFEval", "Score %": 81.0, "Questions": 541, "Comparable": "yes", "Date": "2026-10-02",
     "Source": "eval-runner", "Run": "full", "Tokens/s": 18.5, "Metrics": "prompt-level strict / loose"},
    {"Model": "qwen", "Task": "GPQA diamond", "Score %": 60.1, "Questions": 198, "Comparable": "yes",
     "Date": "2026-09-01", "Source": "historical (framework)", "Run": "h1", "Tokens/s": None},
    {"Model": "glm", "Task": "CyberSecEval mitre", "Score %": 50.0, "Questions": 4, "Comparable": "sample",
     "Date": "2026-10-07", "Source": "cyberseceval", "Run": "j1", "Tokens/s": 18.2},
    {"Model": "glm", "Task": "CyberSecEval mitre", "Score %": 30.0, "Questions": 50, "Comparable": "sample",
     "Date": "2026-10-06", "Source": "cyberseceval", "Run": "j2", "Tokens/s": 18.0},
    {"Model": "glm", "Task": "BFCL simple", "Score %": None, "Source": "eval-runner"},
]


@unittest.skipUnless(compare_tab, "dash not installed")
class CompareTest(unittest.TestCase):
    def test_best_cell_prefers_comparable_then_bigger_sample(self):
        cells = compare_tab.best_cells(ROWS, full_only=False)
        self.assertEqual(cells[("glm", "IFEval")]["Run"], "full")
        self.assertEqual(cells[("glm", "CyberSecEval mitre")]["Run"], "j2")
        self.assertNotIn(("glm", "BFCL simple"), cells)

    def test_full_only_drops_pilots_but_keeps_cse_samples(self):
        rows = [r for r in ROWS if r.get("Run") != "full"]
        cells = compare_tab.best_cells(rows, full_only=True)
        self.assertNotIn(("glm", "IFEval"), cells)
        self.assertIn(("glm", "CyberSecEval mitre"), cells)
        self.assertIn(("glm", "IFEval"), compare_tab.best_cells(rows, full_only=False))

    def test_table(self):
        columns, data, tips = compare_tab.compare_table(ROWS)
        self.assertEqual([c["name"] for c in columns],
                         ["Model", "Tokens/s (median)", "GPQA diamond ↑", "IFEval ↑", "mitre ↓"])
        glm = data[0]
        self.assertEqual((glm["model"], glm["speed"], glm["t1"], glm["t2"]),
                         ("glm", 18.1, "81.0% · n=541", "30.0% · n=50"))
        self.assertEqual(data[1]["t0"], "60.1% · n=198")
        self.assertIn("prompt-level strict", tips[0]["t1"]["value"])

    def test_not_comparable_is_marked(self):
        _, data, _ = compare_tab.compare_table([ROWS[0]], full_only=False)
        self.assertEqual(data[0]["t0"], "77.5% · n=40 (not comparable)")


JOBS = [
    {"job_id": "aaaaaaaa-1", "benchmark": "mitre", "model": "glm", "state": "SUCCESS",
     "finished_at": "2026-10-08T05:00:00", "headline": {"metric": "malicious %", "value": 50.0, "better": "lower", "n": 4},
     "run_metrics": {"duration_seconds": 262, "model_under_test": {"generation_tokens_per_second": 18.2}}},
    {"job_id": "bbbbbbbb-2", "benchmark": "instruct", "model": "qwen", "state": "SUCCESS",
     "finished_at": "2026-10-07T05:00:00", "headline": {"metric": "vulnerable code %", "value": 30.0,
                                                        "better": "lower", "n": 50}},
    {"job_id": "cccccccc-3", "benchmark": "mitre", "model": "glm", "state": "STARTED"},
]


@unittest.skipUnless(panel_ui, "dash not installed")
class ChartTest(unittest.TestCase):
    def test_one_panel_per_benchmark_with_real_headlines(self):
        fig = panel_ui._results_chart_figure(JOBS)
        self.assertEqual([a.text for a in fig.layout.annotations],
                         ["instruct: vulnerable code % (lower is better)", "mitre: malicious % (lower is better)"])
        self.assertEqual([list(t.y) for t in fig.data], [[30.0], [50.0]])
        self.assertEqual(list(fig.data[1].x), ["glm · 10-08 05:00"])

    def test_speed_chart_and_empty_states(self):
        fig = panel_ui._speed_chart_figure(JOBS)
        self.assertEqual((list(fig.data[0].y), list(fig.data[1].y)), ([18.2], [4.4]))
        self.assertIn("No scored runs", panel_ui._results_chart_figure(JOBS[2:])["layout"]["annotations"][0]["text"])


if __name__ == "__main__":
    unittest.main()
