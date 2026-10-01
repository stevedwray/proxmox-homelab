"""Unit tests for summarize.py and selftest_checks.py. Run with:
python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner -p "test_*.py"
"""

import json
import os
import tempfile
import unittest
from unittest import mock

import runmeta
import selftest_checks
import summarize

STAMP = "2026-10-01T00-00-00.000000"


COMPARABLE = {"limit": None, "gen_kwargs": {"max_gen_toks": 8192}, "model_args": {"model": "m:q4"}}


def write_run(root, name, tasks, gpqa_rows=None, ifeval_rows=None, run_json=True, config=None):
    """Create a run dir shaped like lm_eval's output (<run>/<model>/results_*.json)."""
    run_dir = os.path.join(root, name)
    model_dir = os.path.join(run_dir, "model")
    os.makedirs(model_dir)
    results = {}
    n_samples = {}
    if "gpqa" in tasks:
        results["gpqa_diamond_cot_zeroshot"] = {"exact_match,flexible-extract": 0.5, "exact_match,strict-match": 0.25}
        n_samples["gpqa_diamond_cot_zeroshot"] = {"original": 198, "effective": len(gpqa_rows or [])}
    if "ifeval" in tasks:
        results["ifeval"] = {"prompt_level_strict_acc,none": 0.9, "prompt_level_loose_acc,none": 0.95}
        n_samples["ifeval"] = {"original": 541, "effective": len(ifeval_rows or [])}
    with open(os.path.join(model_dir, f"results_{STAMP}.json"), "w") as fh:
        json.dump({"results": results, "n-samples": n_samples, "config": config or COMPARABLE}, fh)
    for task, rows in (("gpqa_diamond_cot_zeroshot", gpqa_rows), ("ifeval", ifeval_rows)):
        if rows is not None:
            with open(os.path.join(model_dir, f"samples_{task}_{STAMP}.jsonl"), "w") as fh:
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
    if run_json:
        with open(os.path.join(run_dir, "run.json"), "w") as fh:
            json.dump({"run": name, "fingerprint": "f", "server": {"props": {"model_path": "/m"}}}, fh)
    return run_dir


def gpqa_rows(answers):
    """answers: list of raw response strings; each doc gets strict + flexible rows."""
    rows = []
    for doc_id, raw in enumerate(answers):
        parsed = "[invalid]" if "(" not in raw else "(A)"
        for filt in ("strict-match", "flexible-extract"):
            rows.append({"doc_id": doc_id, "filter": filt, "resps": [[raw]], "filtered_resps": [parsed]})
    return rows


def ifeval_rows(answers):
    return [{"doc_id": i, "filter": "none", "resps": [[raw]], "filtered_resps": [raw]} for i, raw in enumerate(answers)]


class FlagsTest(unittest.TestCase):
    def test_counts_per_question_not_per_filter_row(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = write_run(root, "r", ["gpqa"], gpqa_rows=gpqa_rows(["The answer is (A)", "", "no letter here"]))
            entry = summarize.load(run_dir)["gpqa_diamond_cot_zeroshot"]
            flags = summarize.response_flags(entry["samples"], "gpqa_diamond_cot_zeroshot")
            self.assertEqual(flags, {"questions": 3, "empty": 1, "unparsed": 2})

    def test_ifeval_has_no_unparsed(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = write_run(root, "r", ["ifeval"], ifeval_rows=ifeval_rows(["ok", "   ", "fine"]))
            entry = summarize.load(run_dir)["ifeval"]
            self.assertEqual(summarize.response_flags(entry["samples"], "ifeval"),
                             {"questions": 3, "empty": 1, "unparsed": None})


class DescribeTest(unittest.TestCase):
    def test_line_has_scores_and_flags(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = write_run(root, "glm-both", ["gpqa", "ifeval"],
                                gpqa_rows=gpqa_rows(["(A)", ""]), ifeval_rows=ifeval_rows(["ok"]))
            line, ok = summarize.describe(run_dir, check=True)
            self.assertTrue(ok)
            self.assertIn("GPQA flex 50.00%", line)
            self.assertIn("IFEval p-loose 95.00%", line)
            self.assertIn("[empty 1, unparsed 1 <- inspect samples]", line)
            self.assertIn("[empty 0]", line)

    def test_check_fails_when_task_missing(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = write_run(root, "gpqa-only", ["gpqa"], gpqa_rows=gpqa_rows(["(A)"]))
            self.assertFalse(summarize.describe(run_dir, check=True)[1])
            self.assertTrue(summarize.describe(run_dir, check=False)[1])

    def test_empty_dir_reports_no_results(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "pending"))
            line, ok = summarize.describe(os.path.join(root, "pending"), check=False)
            self.assertIn("no results yet", line)
            self.assertFalse(ok)

    def test_main_skips_underscore_dirs(self):
        with tempfile.TemporaryDirectory() as root:
            write_run(root, "_selftest", ["ifeval"], ifeval_rows=ifeval_rows(["x"]))
            write_run(root, "real", ["ifeval"], ifeval_rows=ifeval_rows(["x"]))
            with mock.patch.object(summarize, "RESULTS_ROOT", root), mock.patch("builtins.print") as printed:
                summarize.main([])
            lines = [call.args[0] for call in printed.call_args_list]
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].startswith("real:"))


class ComparabilityTest(unittest.TestCase):
    def test_full_run_with_token_cap_is_comparable(self):
        self.assertIsNone(summarize.exclusion_reason({"config": COMPARABLE}))
        as_string = {"limit": None, "gen_kwargs": "max_gen_toks=8192,temperature=0"}
        self.assertIsNone(summarize.exclusion_reason({"config": as_string}))

    def test_pilot_and_bug6_excluded(self):
        self.assertEqual(summarize.exclusion_reason({"config": {"limit": 40.0, "gen_kwargs": {"max_gen_toks": 8192}}}),
                         "pilot (limit 40)")
        self.assertIn("Bug 6", summarize.exclusion_reason({"config": {"limit": None, "gen_kwargs": {}}}))
        self.assertIn("Bug 6", summarize.exclusion_reason({"config": {"limit": None, "gen_kwargs": {"max_gen_toks": 256}}}))

    def test_model_name_dict_or_string(self):
        self.assertEqual(summarize.model_name({"config": {"model_args": {"model": "x"}}}), "x")
        self.assertEqual(summarize.model_name({"config": {"model_args": "base_url=u,model=y,num_concurrent=1"}}), "y")

    def test_historical_section_filters_and_explains(self):
        with tempfile.TemporaryDirectory() as root:
            hist = os.path.join(root, summarize.HISTORICAL_DIR)
            os.makedirs(hist)
            write_run(hist, "good", ["gpqa", "ifeval"], gpqa_rows=gpqa_rows(["(A)"]), ifeval_rows=ifeval_rows(["ok"]))
            write_run(hist, "bug6", ["ifeval"], ifeval_rows=ifeval_rows(["ok"]),
                      config={"limit": None, "gen_kwargs": {}})
            lines = summarize.historical_lines(root)
        text = "\n".join(lines)
        self.assertIn("  good: GPQA flex 50.00%", text)
        self.assertIn("(m:q4)", text)
        self.assertNotIn("  bug6: ", text)
        self.assertIn("excluded:\n  bug6 ifeval: no max_gen_toks=8192", text)

    def test_no_historical_dir_adds_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(summarize.historical_lines(root), [])


class SelftestChecksTest(unittest.TestCase):
    def _log(self, root, requests):
        path = os.path.join(root, "req.jsonl")
        with open(path, "w") as fh:
            for req in requests:
                fh.write(json.dumps(req) + "\n")
        return path

    def good(self):
        return {"model": "m", "max_tokens": runmeta.MAX_GEN_TOKS, "temperature": 0, "seed": 1234,
                "messages": [{"role": "user", "content": "q"}]}

    def test_good_requests_pass(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(selftest_checks.request_errors(self._log(root, [self.good()] * 2), 2, "m"), [])

    def test_bug6_truncation_caught(self):
        bad = self.good()
        bad["max_tokens"] = 256
        with tempfile.TemporaryDirectory() as root:
            errors = selftest_checks.request_errors(self._log(root, [bad]), 1, "m")
        self.assertTrue(any("max_tokens 256" in e for e in errors))

    def test_count_temperature_and_messages_checked(self):
        bad = self.good()
        bad["temperature"] = 1.0
        bad["messages"] = []
        with tempfile.TemporaryDirectory() as root:
            errors = selftest_checks.request_errors(self._log(root, [bad]), 3, "m")
        self.assertEqual(len(errors), 3)

    def test_flag_errors(self):
        with tempfile.TemporaryDirectory() as root:
            run_dir = write_run(root, "r", ["gpqa", "ifeval"],
                                gpqa_rows=gpqa_rows(["", "(A)"]), ifeval_rows=ifeval_rows(["", "ok"]))
            self.assertEqual(selftest_checks.flag_errors(run_dir, 2), [])
            self.assertEqual(len(selftest_checks.flag_errors(run_dir, 3)), 1)


if __name__ == "__main__":
    unittest.main()
