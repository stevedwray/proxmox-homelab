"""Unit tests for runmeta.py. Run with:
python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner -p "test_*.py"
"""

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

import runmeta

PROPS = {
    "model_path": "/m/glm.gguf",
    "model_alias": "glm-5.3-flash",
    "build_info": "b1-abc",
    "total_slots": 4,
    "chat_template": "{{ x }}",
    "default_generation_settings": {
        "n_ctx": 131072,
        "params": {"temperature": 1.0, "top_p": 0.95, "min_p": 0.01, "n_predict": -1, "seed": 4294967295,
                   "unrelated": "ignored"},
    },
}


def fake_get(models_id="glm-5.3-flash", props=PROPS):
    def get_json(url, api_key):
        if url.endswith("/v1/models"):
            return {"data": [{"id": models_id}]}
        if props is None:
            raise OSError("no /props")
        return copy.deepcopy(props)
    return get_json


class SnapshotTest(unittest.TestCase):
    def test_snapshot_records_props_subset(self):
        server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get())
        self.assertEqual(server["model_id"], "glm-5.3-flash")
        self.assertEqual(server["props"]["model_path"], "/m/glm.gguf")
        self.assertEqual(server["props"]["n_ctx"], 131072)
        self.assertEqual(server["props"]["params"]["temperature"], 1.0)
        self.assertNotIn("unrelated", server["props"]["params"])
        self.assertEqual(len(server["props"]["chat_template_sha256"]), 64)

    def test_snapshot_without_props(self):
        server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get(props=None))
        self.assertIsNone(server["props"])
        self.assertTrue(runmeta.fingerprint(server))

    def test_comma_in_model_id_rejected(self):
        with self.assertRaises(ValueError):
            runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get(models_id="a,b"))


class FingerprintTest(unittest.TestCase):
    def setUp(self):
        self.server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get())

    def test_ignores_base_url_and_slots(self):
        other = copy.deepcopy(self.server)
        other["base_url"] = "http://192.168.1.18:8080"
        other["props"]["total_slots"] = 1
        self.assertEqual(runmeta.fingerprint(self.server), runmeta.fingerprint(other))
        self.assertEqual(runmeta.server_changes(self.server, other), [])

    def test_detects_model_template_and_sampling_changes(self):
        for path, value in (
            (("props", "model_path"), "/m/other.gguf"),
            (("props", "chat_template_sha256"), "0" * 64),
            (("props", "build_info"), "b2-def"),
        ):
            other = copy.deepcopy(self.server)
            other[path[0]][path[1]] = value
            self.assertNotEqual(runmeta.fingerprint(self.server), runmeta.fingerprint(other), path)
        other = copy.deepcopy(self.server)
        other["props"]["params"]["temperature"] = 0.6
        self.assertEqual(runmeta.server_changes(self.server, other), ["props.params.temperature: 1.0 -> 0.6"])


class ArgvTest(unittest.TestCase):
    def test_argv_carries_battery_settings(self):
        argv = runmeta.lm_eval_argv("http://f:8080", "glm", ["ifeval"], 1, None, "/results/r")
        self.assertEqual(argv[:2], ["lm_eval", "run"])
        model_args = argv[argv.index("--model_args") + 1]
        self.assertIn("base_url=http://f:8080/v1/chat/completions", model_args)
        self.assertIn("model=glm", model_args)
        self.assertIn("num_concurrent=1", model_args)
        self.assertIn("timeout=3600", model_args)
        self.assertEqual(argv[argv.index("--gen_kwargs") + 1], "max_gen_toks=8192")
        self.assertIn("--apply_chat_template", argv)
        self.assertIn("--log_samples", argv)
        self.assertNotIn("--limit", argv)
        self.assertEqual(argv[argv.index("--use_cache") + 1], "/results/r/cache/responses")
        self.assertEqual(argv[argv.index("--output_path") + 1], "/results/r")

    def test_limit_added_when_set(self):
        argv = runmeta.lm_eval_argv("http://f:8080", "glm", ["ifeval"], 2, 40, "/r")
        self.assertEqual(argv[argv.index("--limit") + 1], "40")


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get())

    def test_pilot_defaults_limit_and_names_run(self):
        record, run_dir = runmeta.build_record(self.server, "gpqa", True, None, 1, "effort=high", "20261001T000000Z", "/results")
        self.assertEqual(record["run"], "glm-5.3-flash-gpqa-pilot-20261001T000000Z")
        self.assertEqual(run_dir, "/results/glm-5.3-flash-gpqa-pilot-20261001T000000Z")
        self.assertEqual(record["limit"], runmeta.PILOT_LIMIT)
        self.assertEqual(record["tasks"], ["gpqa_diamond_cot_zeroshot"])
        self.assertEqual(record["note"], "effort=high")
        self.assertEqual(record["fingerprint"], runmeta.fingerprint(self.server))

    def test_full_run_has_no_limit(self):
        record, _ = runmeta.build_record(self.server, "ifeval", False, None, 1, "", "S", "/results")
        self.assertIsNone(record["limit"])
        self.assertEqual(record["run"], "glm-5.3-flash-ifeval-S")

    def test_limit_named_in_run(self):
        record, _ = runmeta.build_record(self.server, "bfcl", False, 10, 1, "", "S", "/results")
        self.assertEqual((record["run"], record["limit"]), ("glm-5.3-flash-bfcl-limit10-S", 10))

    def test_safe_name(self):
        self.assertEqual(runmeta.safe_name("org/model:q4 x"), "org-model-q4-x")


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get())

    def test_32k_series_named_recorded_and_timed(self):
        record, _ = runmeta.build_record(self.server, "gpqa", False, None, 1, "", "S", "/results", 32768)
        self.assertEqual(record["run"], "glm-5.3-flash-gpqa-32k-S")
        self.assertEqual(record["max_gen_toks"], 32768)
        argv = record["lm_eval_argv"]
        self.assertEqual(argv[argv.index("--gen_kwargs") + 1], "max_gen_toks=32768")
        self.assertIn(f"timeout={runmeta.request_timeout(32768)}", argv[argv.index("--model_args") + 1])
        self.assertGreater(runmeta.request_timeout(32768), runmeta.REQUEST_TIMEOUT)

    def test_standard_budget_keeps_old_name_and_timeout(self):
        record, _ = runmeta.build_record(self.server, "gpqa", True, None, 1, "", "S", "/results")
        self.assertEqual(record["run"], "glm-5.3-flash-gpqa-pilot-S")
        self.assertEqual(record["max_gen_toks"], runmeta.MAX_GEN_TOKS)
        self.assertEqual(runmeta.request_timeout(runmeta.MAX_GEN_TOKS), runmeta.REQUEST_TIMEOUT)

    def test_context_too_small_refused(self):
        small = copy.deepcopy(PROPS)
        small["default_generation_settings"]["n_ctx"] = 32768
        server = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get(props=small))
        self.assertIsNotNone(runmeta.context_problem(server, 32768))
        self.assertIsNone(runmeta.context_problem(server, 8192))
        no_props = runmeta.snapshot_server("http://f:8080", "k", get_json=fake_get(props=None))
        self.assertIsNone(runmeta.context_problem(no_props, 32768))
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(runmeta, "_get_json", fake_get(props=small)), \
                    mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                rc = runmeta.main(["start", "--base-url", "http://f:8080", "--task", "gpqa", "--stamp", "S",
                                   "--results-root", root, "--max-gen-toks", "32768"])
            self.assertEqual(rc, 2)
            self.assertEqual(os.listdir(root), [])

    def test_selftest_mock_passes_the_context_check(self):
        import mock_openai
        server = runmeta.snapshot_server("http://m", "k", get_json=fake_get(props=mock_openai.PROPS))
        self.assertIsNone(runmeta.context_problem(server, runmeta.MAX_GEN_TOKS))

    def test_budget_below_standard_rejected(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            runmeta.main(["start", "--base-url", "http://f:8080", "--task", "gpqa", "--max-gen-toks", "4096"])


class CommandTest(unittest.TestCase):
    def test_start_then_check_and_changed_exit_code(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.object(runmeta, "_get_json", fake_get()), \
                    mock.patch("sys.stdout"):
                rc = runmeta.main(["start", "--base-url", "http://f:8080", "--task", "ifeval",
                                   "--stamp", "S", "--results-root", root])
            self.assertEqual(rc, 0)
            run_dir = os.path.join(root, "glm-5.3-flash-ifeval-S")
            with open(os.path.join(run_dir, "run.json")) as fh:
                self.assertEqual(json.load(fh)["run"], "glm-5.3-flash-ifeval-S")

            with mock.patch.object(runmeta, "_get_json", fake_get()), mock.patch("sys.stdout"):
                self.assertEqual(runmeta.main(["check", run_dir]), 0)

            changed = copy.deepcopy(PROPS)
            changed["model_path"] = "/m/other.gguf"
            with mock.patch.object(runmeta, "_get_json", fake_get(props=changed)), mock.patch("sys.stdout"):
                self.assertEqual(runmeta.main(["check", run_dir]), runmeta.EXIT_CHANGED)

    def test_start_refuses_existing_run(self):
        with tempfile.TemporaryDirectory() as root:
            args = ["start", "--base-url", "http://f:8080", "--task", "gpqa", "--stamp", "S", "--results-root", root]
            with mock.patch.object(runmeta, "_get_json", fake_get()), mock.patch("sys.stdout"):
                runmeta.main(args)
                with self.assertRaises(FileExistsError):
                    runmeta.main(args)


if __name__ == "__main__":
    unittest.main()
