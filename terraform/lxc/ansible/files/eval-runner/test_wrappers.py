"""Unit tests for the benchmark wrappers' own logic (bfcl_run.py,
agentbench_run.py, repobench_run.py, wrapper_common.py) and how their
results flow into summarize/publish. The benchmarks themselves run only in
their images (eval-run selftest). Run with:
python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner -p "test_*.py"
"""

import json
import os
import tempfile
import unittest

import agentbench_run
import bfcl_run
import publish
import repobench_run
import summarize
import wrapper_common as wc

try:
    import rapidfuzz  # noqa: F401
except ImportError:  # in the image; locally: pip install rapidfuzz==3.14.6 in a venv
    rapidfuzz = None


def write_jsonl(path, rows):
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


class BfclTest(unittest.TestCase):
    def test_pilot_ids_are_evenly_spaced(self):
        self.assertEqual(bfcl_run.pilot_ids(20)[:3], ["simple_0", "simple_20", "simple_40"])
        self.assertEqual(len(bfcl_run.pilot_ids(40)), 40)
        self.assertEqual(bfcl_run.pilot_ids(2), ["simple_0", "simple_200"])

    def test_errored_entries_are_dropped_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.json")
            write_jsonl(path, [{"id": "simple_0", "result": [{"f": "{}"}]},
                               {"id": "simple_1", "result": "Error during inference: timeout"}])
            self.assertEqual(bfcl_run.drop_errored(path), 1)
            with open(path) as fh:
                self.assertEqual([json.loads(line)["id"] for line in fh], ["simple_0"])
            self.assertEqual(bfcl_run.drop_errored(os.path.join(tmp, "missing.json")), 0)

    def test_response_counts(self):
        entries = [{"result": []}, {"result": ""}, {"result": "Error during inference: x"}, {"result": [{"f": "{}"}]}]
        self.assertEqual(bfcl_run.response_counts(entries), (2, 1))


class AgentBenchTest(unittest.TestCase):
    def test_agent_config_matches_history_without_a_secret(self):
        conf = agentbench_run.agent_config("http://f:8080/v1/chat/completions", "glm")["eval-runner"]["parameters"]
        self.assertEqual(conf["body"], {"model": "glm", "temperature": 0, "max_tokens": 3072})
        self.assertEqual(conf["headers"]["Authorization"], "Bearer ${OPENAI_API_KEY}")
        self.assertEqual(conf["prompter"], {"name": "role_content_dict", "args": {"agent_role": "assistant"}})
        self.assertEqual(conf["return_format"], "{response[choices][0][message][content]}")

    def test_assignment_points_at_output_and_controller(self):
        conf = agentbench_run.assignment_config("/tmp/a.yaml", "/results/r/agentbench/outputs")
        self.assertEqual(conf["output"], "/results/r/agentbench/outputs")
        self.assertEqual(conf["assignments"], [{"agent": ["eval-runner"], "task": ["os-std"]}])
        self.assertTrue(conf["definition"]["task"]["import"].startswith("/opt/agentbench/"))

    def test_episode_counts_and_injection_rate(self):
        runs = [
            {"error": None, "output": {"status": "completed", "history": [{"role": "agent", "content": "Act: finish"}],
                                       "result": {"metadata": {"injection_present": True},
                                                  "injection_successful": True}}},
            {"error": None, "output": {"status": "agent invalid action", "history": [{"role": "agent", "content": ""}],
                                       "result": {"metadata": {"injection_present": True},
                                                  "injection_successful": False}}},
            {"error": "boom", "output": {"status": "unknown", "history": [], "result": {"metadata": {}}}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runs.jsonl")
            write_jsonl(path, runs)
            self.assertEqual(agentbench_run.episode_counts(path), (3, 1, 1))
            self.assertEqual(agentbench_run.injection_rate(path), 0.5)
            self.assertEqual(agentbench_run.episode_counts(os.path.join(tmp, "none")), (0, 0, 0))


class RepoBenchTest(unittest.TestCase):
    def test_first_line_not_comment(self):
        f = repobench_run.get_first_line_not_comment
        self.assertEqual(f("\n# comment\n    x = 1\ny = 2"), "    x = 1")
        self.assertEqual(f('"""doc\nmore"""\nreturn a'), "return a")
        self.assertEqual(f("# only\n# comments"), "# only")

    def test_prompt_matches_upstream_when_it_fits(self):
        data = {"repo_name": "r", "context": [{"path": "a.py", "snippet": "def a(): pass"}],
                "file_path": "b.py", "import_statement": "import a", "cropped_code": "x = a()\n\n"}
        prompt = repobench_run.construct_prompt(data, lambda text: 0)
        self.assertEqual(prompt, "# Repo Name: r\n# Path: a.py\ndef a(): pass\n\n# Path: b.py\nimport a\nx = a()\n")

    def test_cross_file_part_is_cut_to_fit(self):
        snippets = [{"path": f"m{i}.py", "snippet": "y" * 40} for i in range(10)]
        data = {"repo_name": "r", "context": snippets, "file_path": "b.py", "import_statement": "",
                "cropped_code": "z"}
        prompt = repobench_run.construct_prompt(data, len, max_tokens=200)  # 1 "token" per character
        self.assertLessEqual(len(prompt), 200)
        self.assertTrue(prompt.startswith("# Repo Name: r\n# Path: m0.py"))
        self.assertTrue(prompt.endswith("# Path: b.py\n\nz\n"))

    def test_sample_is_seeded_and_capped(self):
        by_level = {"2k": list(range(50)), "4k": list(range(100, 103))}
        first = repobench_run.sample(by_level, 5)
        self.assertEqual(first, repobench_run.sample(by_level, 5))
        self.assertEqual(len(first), 8)  # 5 from 2k, all 3 from 4k
        self.assertEqual(first[-3:], [100, 101, 102])

    @unittest.skipUnless(rapidfuzz, "rapidfuzz not installed")
    def test_scores_are_weighted_by_sample_count(self):
        preds = {"cross_file_first": [{"pred": "a = 1", "gt": "a  =  1"}, {"pred": "b", "gt": "c"}],
                 "in_file": [{"pred": "x", "gt": "x"}] * 2}
        per, em, es, total = repobench_run.score(preds)
        self.assertEqual(per["cross_file_first"][:2], (2, 50.0))
        self.assertEqual(per["in_file"], (2, 100.0, 100.0))
        self.assertEqual((em, total), (75.0, 4))
        self.assertEqual(repobench_run.edit_similarity("abc", "abd"), 67)


class ImportHistoryTest(unittest.TestCase):
    def test_bfcl_probe_becomes_comparable_rows(self):
        import import_history
        probe = [
            {"name": "Gemma4-26B-Ollama-FC", "score": {"accuracy": 0.94, "correct_count": 376, "total_count": 400},
             "mtime": 1785888000, "empty": 0, "errors": 0, "tag": "gemma4:26b", "base_url": "http://localhost:11434/v1"},
            {"name": "Qwen3.8-27B-UDQ4KXL-High-Ollama-FC",
             "score": {"accuracy": 0.925, "correct_count": 370, "total_count": 400},
             "mtime": 1789000000, "empty": 1, "errors": 0, "tag": "qwen3.8-27b-q4kxl-ctx32k", "base_url": None},
            {"name": "Laguna-S-2-1-UD-Q4-K-M-FC", "score": {"accuracy": 0.755, "correct_count": 302, "total_count": 400},
             "mtime": 1785888000, "empty": 34, "errors": 0, "tag": None, "base_url": "http://localhost:8080/v1"},
        ]
        with tempfile.TemporaryDirectory() as root:
            import_history.import_bfcl(probe, root)
            _, rows = publish.build_files(publish.collect(root), None, "NOW")
        by_model = {r["Model"]: r for r in rows}
        self.assertEqual(set(by_model), {"gemma4:26b", "qwen3.8-27b-q4kxl-ctx32k", "Laguna-S-2-1-UD-Q4-K-M"})
        gemma = by_model["gemma4:26b"]
        self.assertEqual((gemma["Score %"], gemma["Comparable"], gemma["Runtime"], gemma["Source"]),
                         (94.0, "yes", "Ollama", "historical (framework)"))
        self.assertEqual(by_model["qwen3.8-27b-q4kxl-ctx32k"]["Note"], "reasoning effort high")
        self.assertEqual(by_model["Laguna-S-2-1-UD-Q4-K-M"]["Runtime"], "llama.cpp (router)")
        self.assertEqual(by_model["Laguna-S-2-1-UD-Q4-K-M"]["Empty answers"], 34)

    def test_agentbench_sampled_and_full_runs(self):
        import import_history
        with tempfile.TemporaryDirectory() as tmp:
            outputs, root = os.path.join(tmp, "outputs"), os.path.join(tmp, "results")
            for stamp, agent, total, passed in (("2026-08-06-08-20-09", "qwen36-35b", 100, 22),
                                                ("2026-08-05-21-14-17", "qwen3-coder-30b", 800, 216)):
                task_dir = os.path.join(outputs, stamp, agent, "os-std")
                os.makedirs(task_dir)
                with open(os.path.join(task_dir, "overall.json"), "w") as fh:
                    json.dump({"total": total, "custom": {"overall": {"total": total, "pass": passed,
                                                                      "acc": passed / total}}}, fh)
            import_history.import_agentbench(outputs, root)
            _, rows = publish.build_files(publish.collect(root), None, "NOW")
        by_model = {r["Model"]: r for r in rows}
        self.assertEqual((by_model["qwen36-35b"]["Score %"], by_model["qwen36-35b"]["Comparable"]), (22.0, "yes"))
        coder = by_model["qwen3-coder-30b"]
        self.assertEqual((coder["Comparable"], coder["Series"]), ("no", "800 full"))
        self.assertIn("separate series", coder["Why not comparable"])
        self.assertEqual(coder["Source"], "historical (garuda)")


class ResultsFlowTest(unittest.TestCase):
    """A wrapper's results file goes through summarize and publish like lm_eval's."""

    def _write(self, root, task, metrics, limit=None, series="v3 simple", exclusion=None):
        run_dir = os.path.join(root, "glm-bfcl-S")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "run.json"), "w") as fh:
            json.dump({"run": "glm-bfcl-S", "tasks": [task], "created_utc": "20261002T000000Z", "note": "",
                       "server": {"model_id": "glm", "props": {"build_info": "b1", "model_path": "/m/g.gguf"}}}, fh)
        wc.write_results(os.path.join(run_dir, "bfcl"), task, metrics, 400, 400, limit=limit, model="glm",
                         base_url="http://f:8080/v1", harness="bfcl", version="2025.8.6.2", series=series,
                         exclusion=exclusion, runtime="llama.cpp b1", stamp="2026-10-02T00-00-00.000000")
        return run_dir

    def test_comparable_wrapper_result_is_ranked(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = self._write(root, "bfcl_simple", {"accuracy,none": 0.9425, "empty,none": 3, "errors,none": 1})
            line, ok = summarize.describe(run_dir, check=True)
            self.assertTrue(ok)
            self.assertIn("BFCL simple 94.25%", line)
            self.assertIn("empty 3, errors 1", line)
            files, rows = publish.build_files(publish.collect(root), None, "NOW")
        row = rows[0]
        self.assertEqual((row["Task"], row["Score %"], row["Alt score %"], row["Metrics"]),
                         ("BFCL simple", 94.25, None, "accuracy"))
        self.assertEqual((row["Comparable"], row["Series"], row["Runtime"]), ("yes", "v3 simple", "llama.cpp b1"))
        self.assertEqual(row["Empty answers"], 3)
        self.assertIn("| 1 | glm | 94.25% | – |", files["leaderboard.md"].decode())

    def test_pilot_wrapper_result_is_excluded(self):
        with tempfile.TemporaryDirectory() as root:
            self._write(root, "bfcl_simple", {"accuracy,none": 0.5, "empty,none": 0}, limit=40)
            _, rows = publish.build_files(publish.collect(root), None, "NOW")
        self.assertEqual((rows[0]["Comparable"], rows[0]["Why not comparable"]), ("no", "pilot (limit 40)"))
        self.assertEqual(rows[0]["Series"], "")

    def test_every_wrapper_task_has_labels_series_and_a_view(self):
        view_tasks = {task for _, _, task, _ in publish.VIEWS if task}
        for task in summarize.HEADLINE:
            self.assertIn(task, publish.TASK_LABELS)
            self.assertIn(task, summarize.STANDARD_SERIES)
            self.assertIn(publish.TASK_LABELS[task][0], view_tasks)
        self.assertEqual(summarize.STANDARD_SERIES["bfcl_simple"], bfcl_run.SERIES)
        self.assertEqual(summarize.STANDARD_SERIES["agentbench_os_std"], agentbench_run.SERIES)
        self.assertEqual(summarize.STANDARD_SERIES["repobench_python"], repobench_run.SERIES)


if __name__ == "__main__":
    unittest.main()
