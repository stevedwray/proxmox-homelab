"""Unit tests for panel-ui (app.py's layout and eval_tab.py), panel-web faked.
Needs app-ui/requirements.txt (skipped otherwise). Run with:
python3 -m unittest discover -s terraform/lxc/stacks/cse-panel-stack/app-ui -p "test_*.py"
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import app as panel_ui
    import eval_tab
except ImportError:  # dash not installed locally
    panel_ui = eval_tab = None

DONE = {"id": "j1", "task": "ifeval", "mode": "limit", "limit": 5, "state": "done", "run": "glm-ifeval-limit5-S",
        "submitted": "2026-10-08T14:00:00Z", "results": "IFEval 80.00%",
        "run_metrics": {"duration_seconds": 192, "segments": 1,
                        "model_under_test": {"completion_tokens": 4810, "prompt_tokens": 1234,
                                             "generation_tokens_per_second": 20.1,
                                             "prompt_tokens_per_second": 900.0}}}


def ids(component, found=None):
    """Every id in a Dash component tree."""
    found = [] if found is None else found
    if getattr(component, "id", None) is not None:
        cid = component.id
        found.append(json.dumps(cid, sort_keys=True) if isinstance(cid, dict) else cid)
    children = getattr(component, "children", None)
    for child in children if isinstance(children, (list, tuple)) else [children]:
        if hasattr(child, "to_plotly_json"):
            ids(child, found)
    return found


def text(component):
    if isinstance(component, (list, tuple)):
        return " ".join(text(c) for c in component)
    if hasattr(component, "children"):
        return text(component.children)
    return "" if component is None else str(component)


@unittest.skipUnless(panel_ui, "dash not installed")
class LayoutTest(unittest.TestCase):
    def test_component_ids_are_unique(self):
        found = ids(panel_ui.app.layout)
        self.assertEqual(len(found), len(set(found)), sorted(i for i in found if found.count(i) > 1))
        for needed in ("family", "cse-section", "eval-section", "eval-run-section", "eval-runs-section",
                       "framework-status", "jobs-table", "eval-jobs-table", "eval-cancel-btn"):
            self.assertIn(needed, found)

    def test_section_switches(self):
        self.assertEqual(panel_ui.switch_eval("results"), ({"display": "none"}, {}))
        self.assertEqual(panel_ui.switch_cse("run"), ({}, {"display": "none"}))

    def test_framework_colour(self):
        self.assertEqual(panel_ui.framework_status_color({"model": "m", "lock": {"suite": "eval"}}), "warning")
        self.assertEqual(panel_ui.framework_status_color({"model": "m", "lock": None}), "secondary")
        self.assertEqual(panel_ui.framework_status_color({"error": "refused"}), "danger")


@unittest.skipUnless(eval_tab, "dash not installed")
class EvalTabTest(unittest.TestCase):
    def test_row_has_metrics(self):
        row = eval_tab.job_row(DONE)
        self.assertEqual((row["mode"], row["duration"], row["tokens"], row["tokens_per_second"]),
                         ("limit 5", "3m 12s", "4,810", 20.1))

    def test_waiting_row_says_for_what(self):
        row = eval_tab.job_row({"id": "j2", "task": "gpqa", "mode": "pilot", "state": "waiting",
                                "waiting_for": "Framework (held by cyberseceval mitre job c1)"})
        self.assertEqual(row["state"], "waiting for Framework (held by cyberseceval mitre job c1)")

    def test_detail_and_buttons(self):
        out = text(eval_tab.job_detail(DONE))
        self.assertIn("IFEval 80.00%", out)
        self.assertIn("4,810", out)
        self.assertFalse(eval_tab.can_cancel(DONE))
        self.assertTrue(eval_tab.can_resume(dict(DONE, state="failed")))
        self.assertTrue(eval_tab.can_cancel({"state": "waiting"}))
        self.assertIn("unavailable", text(eval_tab.metrics_block({"duration_seconds": 5, "unavailable": "reloaded"})))

    def submit(self, rows, budget=False, note=""):
        """rows: {task: (on, size, count)} in TASKS order."""
        tasks = list(eval_tab.TASKS)
        on = [rows.get(t, (False, "pilot", 50))[0] for t in tasks]
        sizes = [rows.get(t, (False, "pilot", 50))[1] for t in tasks]
        counts = [rows.get(t, (False, "pilot", 50))[2] for t in tasks]
        ids_ = [{"type": "eval-on", "task": t} for t in tasks]
        resp = mock.Mock(status_code=200, json=lambda: {"submitted": ["a"]})
        with panel_ui.server.test_request_context(headers={"X-Authentik-Username": "steve"}), \
                mock.patch.object(eval_tab.requests, "post", return_value=resp) as post:
            result = eval_tab.submit(1, on, ids_, sizes, counts, budget, note)
        return result, [c.kwargs["json"] for c in post.call_args_list], post

    def test_each_benchmark_gets_its_own_size(self):
        (msg, color, _), bodies, post = self.submit(
            {"gpqa": (True, "count", 50), "bfcl": (True, "pilot", 50), "repobench": (True, "full", 50)},
            budget=True, note=" effort=high ")
        self.assertEqual(color, "success", msg)
        self.assertEqual([(b["tasks"], b["mode"], b["limit"], b["budget_32k"]) for b in bodies],
                         [(["gpqa"], "limit", 50, True), (["bfcl"], "pilot", None, False),
                          (["repobench"], "full", None, False)])
        self.assertEqual(bodies[0]["note"], "effort=high")
        self.assertEqual(post.call_args.kwargs["headers"]["X-Authentik-Username"], "steve")
        self.assertIn("GPQA diamond (50)", msg)

    def test_choosing_the_whole_set_is_a_full_run_and_bad_counts_start_nothing(self):
        _, bodies, _ = self.submit({"gpqa": (True, "count", 198)})
        self.assertEqual(bodies[0]["mode"], "full")
        (msg, color, _), bodies, _ = self.submit({"gpqa": (True, "count", 50), "agentbench": (True, "count", 500)})
        self.assertEqual((color, bodies), ("warning", []))
        self.assertIn("AgentBench os-std: enter a number from 1 to 100", msg)
        (msg, _, _), bodies, _ = self.submit({})
        self.assertEqual(bodies, [])

    def test_size_hints(self):
        self.assertEqual(eval_tab.size_hint("gpqa", "count", 50),
                         "50 of 198 questions (the first 50). A smoke test: not ranked against full runs.")
        self.assertIn("40 of 400 cases (spread evenly over all 400)", eval_tab.size_hint("bfcl", "pilot", None))
        self.assertIn("150 of 1,500 samples", eval_tab.size_hint("repobench", "count", 10))
        self.assertIn("All 541 prompts", eval_tab.size_hint("ifeval", "full", None))
        self.assertIn("from 1 to 100", eval_tab.size_hint("agentbench", "count", None))

    def test_choose_is_last_with_its_box_shown_only_when_picked(self):
        row = eval_tab.benchmark_row("repobench")
        radio = row.children[1].children[0].children[0]
        self.assertEqual([o["label"] for o in radio.options], ["Pilot (75)", "Full (1,500)", "Choose per level"])
        hidden, _ = eval_tab.update_size("pilot", 50, {"task": "gpqa"})
        shown, _ = eval_tab.update_size("count", 50, {"task": "gpqa"})
        self.assertEqual((hidden["display"], shown["display"]), ("none", "block"))

    def test_poll_builds_rows_and_links(self):
        resp = mock.Mock(json=lambda: {"jobs": [DONE], "links": {"Tables": "https://x/t", "Reports": "https://x/r"}})
        with mock.patch.object(eval_tab.requests, "get", return_value=resp):
            jobs, rows, links = eval_tab.poll(1)
        self.assertEqual(rows[0]["task"], "ifeval")
        self.assertEqual(len([l for l in links if hasattr(l, "href")]), 2)


if __name__ == "__main__":
    unittest.main()
