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


@unittest.skipUnless(panel_ui, "dash not installed")
class CseResultsTest(unittest.TestCase):
    JOBS = [{"job_id": "c2", "benchmark": "mitre", "state": "SUCCESS", "state_label": "Done"},
            {"job_id": "c1", "benchmark": "instruct", "state": "STARTED", "state_label": "Running"}]

    def test_poll_keeps_the_ticks_on_the_same_runs(self):
        resp = mock.Mock(json=lambda: {"jobs": self.JOBS})
        with mock.patch.object(panel_ui.requests, "get", return_value=resp):
            rows, _, _, kept = panel_ui.poll_jobs(1, ["c1", "gone"])
        self.assertEqual(([r["id"] for r in rows], kept), (["c2", "c1"], [1]))

    def test_clicking_shows_and_ticking_counts(self):
        self.assertEqual(panel_ui.select_job({"row": 0, "column": 1, "row_id": "c2"}), "c2")
        detail, style = panel_ui.show_run_detail("c2", self.JOBS)
        self.assertIn("mitre", text(detail))
        self.assertIn('{id} = "c2"', str(style))
        self.assertEqual(panel_ui.tick_jobs([0, 1], self.JOBS), (["c2", "c1"], "Delete selected (2)", False))
        self.assertEqual(panel_ui.tick_jobs([], self.JOBS), ([], "Delete selected", True))
        with mock.patch.object(panel_ui, "ctx", mock.Mock(triggered_id="cse-select-all")):
            self.assertEqual(panel_ui.tick_many_jobs(1, None, self.JOBS), [0])  # finished only

    def test_message_lists_runs_and_warns_about_unfinished(self):
        message = panel_ui.cse_delete_message(self.JOBS)
        self.assertIn("Delete 2 runs", message)
        self.assertIn("instruct c1", message)
        self.assertIn("1 of them haven't finished", message)
        self.assertNotIn("finished:", panel_ui.cse_delete_message(self.JOBS[:1]))

    def test_confirmed_delete_deletes_each_and_forces_only_when_told_in_progress(self):
        answers = iter([{"deleted": "c2"}, {"error": "job is started", "in_progress": True}, {"deleted": "c1"}])
        resp = mock.Mock(json=lambda: next(answers))
        with mock.patch.object(panel_ui.requests, "delete", return_value=resp) as delete:
            message, colour, _ = panel_ui.delete_cse_jobs(1, ["c2", "c1"])
        self.assertEqual(colour, "success")
        self.assertIn("Deleted 2 runs", message)
        self.assertEqual([c.kwargs.get("params") for c in delete.call_args_list], [None, None, {"force": "true"}])


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
        cached = text(eval_tab.metrics_block({"duration_seconds": 40, "model_under_test": {
            "prompt_tokens": 4, "completion_tokens": 520, "prompt_seconds": 0.1, "prompt_tokens_per_second": 40.0}}))
        self.assertIn("Prompt tokens processed (cached text excluded)", cached)
        self.assertIn("too little prompt work", cached)

    def submit(self, rows, budget=False, note=""):
        """rows: {task: (on, size, count)} in TASKS order."""
        tasks = list(eval_tab.TASKS)
        on = [rows.get(t, (False, "pilot", 50))[0] for t in tasks]
        sizes = [rows.get(t, (False, "pilot", 50))[1] for t in tasks]
        counts = [rows.get(t, (False, "pilot", 50))[2] for t in tasks]
        ids_ = [{"type": "eval-on", "task": t} for t in tasks]
        resp = mock.Mock(status_code=200, json=lambda: {"submitted": ["a"]})
        with panel_ui.server.test_request_context(headers={"X-Authentik-Username": "steve"}), \
                mock.patch.object(eval_tab.requests, "request", return_value=resp) as post:
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

    def test_choose_is_last_with_its_box_beside_it(self):
        row = eval_tab.benchmark_row("repobench")
        radio = row.children[1].children[0].children[0]
        self.assertEqual([o["label"] for o in radio.options], ["Pilot (75)", "Full (1,500)", "Choose per level"])
        box = row.children[1].children[0].children[1]
        self.assertNotIn("display", box.style)
        self.assertEqual(eval_tab.typing_a_number_picks_choose(30), "count")
        self.assertIn("30 of 198", eval_tab.update_size("count", 30, {"task": "gpqa"}))

    def test_finished_run_links_to_its_own_folder(self):
        links = [c for c in eval_tab.job_detail(DONE) if hasattr(c, "children") and hasattr(c.children, "href")]
        self.assertTrue(links[0].children.href.endswith("?dir=/eval-runner/runs/glm-ifeval-limit5-S"))

    def test_samples_view(self):
        page = {"available": True, "tasks": [{"task": "gpqa_diamond_cot_zeroshot", "total": 50, "offset": 10, "items": [
            {"doc_id": 10, "prompt": "Q?", "response": "The answer is (B)", "extracted": "(B)", "target": "(B)",
             "scores": {"exact_match": 1.0}},
            {"doc_id": 11, "prompt": "Q2?", "response": "", "extracted": "[invalid]", "target": "(C)",
             "scores": {"exact_match": 0.0}}]}]}
        out = eval_tab.samples_view(page, 10)
        self.assertEqual(out[0].children, "gpqa_diamond_cot_zeroshot · 11–12 of 50")
        titles = [item.title for item in out[1].children]
        self.assertEqual(titles, ["#10 · ✓ correct · answer (B) · expected (B)",
                                  "#11 · ✗ wrong · answer [invalid] · expected (C)"])
        self.assertIn("record scores only", text(eval_tab.samples_view(
            {"available": False, "reason": "BFCL, AgentBench and RepoBench record scores only"}, 0)))

    def test_paging_and_reset(self):
        with mock.patch.object(eval_tab, "fetch_samples", return_value={"available": False, "reason": "r"}) as fetch:
            with mock.patch.object(eval_tab, "ctx", mock.Mock(triggered_id="eval-samples-next")):
                _, offset = eval_tab.show_samples(1, None, 1, "j1", 10)
            self.assertEqual((offset, fetch.call_args.args), (20, ("j1", 20)))
            with mock.patch.object(eval_tab, "ctx", mock.Mock(triggered_id="eval-samples-prev")):
                _, offset = eval_tab.show_samples(1, 1, 1, "j1", 5)
            self.assertEqual(offset, 0)
            with mock.patch.object(eval_tab, "ctx", mock.Mock(triggered_id="eval-selected")):
                _, offset = eval_tab.show_samples(1, 1, 1, "j2", 30)
            self.assertEqual(offset, 0)

    def test_poll_builds_rows_and_links(self):
        resp = mock.Mock(json=lambda: {"jobs": [DONE], "links": {"Tables": "https://x/t", "Reports": "https://x/r"}})
        with mock.patch.object(eval_tab.requests, "get", return_value=resp):
            jobs, rows, links, ticked = eval_tab.poll(1)
            *_, kept = eval_tab.poll(2, ["j1"])
        self.assertEqual(rows[0]["task"], "ifeval")
        self.assertEqual(len([l for l in links if hasattr(l, "href")]), 2)
        self.assertEqual((ticked, kept), ([], [0]))

    def test_ticks_follow_the_runs_when_new_runs_arrive(self):
        rows = [{"id": "new"}, {"id": "j1"}, {"id": "j0"}]
        self.assertEqual(eval_tab.selected_index(rows, ["j0", "j1", "deleted"]), [1, 2])

    def test_clicking_shows_and_ticking_counts(self):
        self.assertEqual(eval_tab.select({"row": 1, "column": 0, "row_id": "j1"}), "j1")
        out = eval_tab.detail("j1", [DONE])
        self.assertIn('{id} = "j1"', str(out[4]))
        rows = [eval_tab.job_row(DONE), eval_tab.job_row(dict(DONE, id="j2"))]
        self.assertEqual(eval_tab.tick([1], rows), (["j2"], "Delete selected (1)", False))
        running = dict(DONE, id="j3", state="running")
        with mock.patch.object(eval_tab, "ctx", mock.Mock(triggered_id="eval-select-all")):
            self.assertEqual(eval_tab.tick_many(1, None, [DONE, running]), [0])
        with mock.patch.object(eval_tab, "ctx", mock.Mock(triggered_id="eval-select-none")):
            self.assertEqual(eval_tab.tick_many(None, 1, [DONE, running]), [])

    def test_delete_plan_and_message(self):
        running = dict(DONE, id="j3", state="running", run="r3")
        never = {"id": "j4", "task": "bfcl", "state": "cancelled"}
        doomed, skipped = eval_tab.delete_plan([DONE, running, never], ["j1", "j3", "j4"])
        self.assertEqual(([j["id"] for j in doomed], [j["id"] for j in skipped]), (["j1", "j4"], ["j3"]))
        message = eval_tab.delete_message(doomed, skipped)
        self.assertIn("Delete 2 runs", message)
        self.assertIn("glm-ifeval-limit5-S", message)
        self.assertIn("bfcl job (never started a run)", message)
        self.assertIn("1 ticked run is still going", message)

    def test_confirmed_delete_deletes_each_ticked_run(self):
        answers = iter([(200, {"deleted": ["j1"], "run": "glm-ifeval-limit5-S"}), (404, {"detail": "no such job"}),
                        (200, {"deleted": ["j4"], "run": None})])

        def fake(method, url, **_):
            status, body = next(answers)
            return mock.Mock(status_code=status, json=lambda: body)
        jobs = [DONE, dict(DONE, id="j2"), {"id": "j4", "task": "bfcl", "state": "cancelled"}]
        with panel_ui.server.test_request_context(), \
                mock.patch.object(eval_tab, "ctx", mock.Mock(triggered_id="eval-delete-confirm")), \
                mock.patch.object(eval_tab.requests, "request", side_effect=fake) as req:
            message, colour, _ = eval_tab.act(None, None, None, 1, None, ["j1", "j2", "j4"], jobs)
        self.assertEqual([c.args[0] for c in req.call_args_list], ["DELETE"] * 3)
        self.assertEqual(colour, "success")
        self.assertEqual(message, "Deleted 1 run, removed 1 job that never ran. "
                                  "Nextcloud and the results table catch up in a minute or so.")

if __name__ == "__main__":
    unittest.main()
