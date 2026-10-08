"""Unit tests for eval_tasks.py (the panel's Celery worker), with eval-run,
docker and Redis faked. Skipped where celery isn't installed (it's only in
the worker's venv on ai-services-stack). Run with:
python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner -p "test_*.py"
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

# Deployed side by side; in the repo the lock lives in ../framework-lock.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "framework-lock"))

try:
    import eval_tasks
except ImportError:  # celery not installed locally
    eval_tasks = None


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def expire(self, key, seconds):
        pass

    def delete(self, key):
        self.data.pop(key, None)


def done(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class FakeHost:
    """Stands in for eval-run and docker: one run container that runs for
    `polls` inspections, then exits with `exit_code`."""

    def __init__(self, polls=2, exit_code=0, start_output="Started eval-glm-bfcl-limit2-S\n"):
        self.polls, self.exit_code, self.start_output = polls, exit_code, start_output
        self.calls = []
        self.stopped = False

    def __call__(self, argv, timeout=600):
        self.calls.append(argv)
        if argv[0] == eval_tasks.EVAL_RUN:
            if argv[1] in eval_tasks.TASKS or argv[1] == "resume":
                return done(self.start_output)
            if argv[1] == "publish":
                return done("published 71 files ...; 1 rows created\n")
            if argv[1] == "results":
                return done("glm-bfcl-limit2-S: BFCL simple 50.00%\n")
        if argv[:2] == ["docker", "ps"]:
            return done("")
        if argv[:2] == ["docker", "inspect"]:
            self.polls -= 1
            if self.stopped or self.polls < 0:
                return done(f"exited {143 if self.stopped else self.exit_code}\n")
            return done("running 0\n")
        if argv[:2] == ["docker", "logs"]:
            return done("Generating: 50%\rGenerating: 100%\n")
        if argv[:2] == ["docker", "stop"]:
            self.stopped = True
            return done("")
        return done("")


@unittest.skipUnless(eval_tasks, "celery not installed")
class ArgsTest(unittest.TestCase):
    def test_modes_and_options(self):
        f = eval_tasks.eval_run_args
        self.assertEqual(f("bfcl", "full")[1:], ["bfcl"])
        self.assertEqual(f("gpqa", "pilot", note="x")[1:], ["gpqa", "--pilot", "--note", "x"])
        self.assertEqual(f("ifeval", "limit", 5, budget_32k=True)[1:],
                         ["ifeval", "--limit", "5", "--max-gen-toks", "32768"])

    def test_rejects_anything_unexpected(self):
        f = eval_tasks.eval_run_args
        for kwargs in ({"task": "rm", "mode": "full"}, {"task": "bfcl", "mode": "everything"},
                       {"task": "bfcl", "mode": "limit", "limit": 0},
                       {"task": "bfcl", "mode": "full", "budget_32k": True},
                       {"task": "bfcl", "mode": "full", "note": "a\nb"}):
            with self.assertRaises(ValueError):
                f(**kwargs)

    def test_started_run_parsed(self):
        self.assertEqual(eval_tasks.started_run("Started eval-glm-bfcl-limit2-S\n  follow: ..."), "glm-bfcl-limit2-S")
        self.assertIsNone(eval_tasks.started_run("eval-run: an eval is already running"))


@unittest.skipUnless(eval_tasks, "celery not installed")
class RunJobTest(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        patches = [
            mock.patch.object(eval_tasks, "_redis", return_value=self.redis),
            mock.patch.object(eval_tasks, "framework_counters", side_effect=self.counters),
            mock.patch.object(eval_tasks, "RESULTS_DIR", tempfile.mkdtemp()),
            mock.patch.object(eval_tasks.time, "sleep"),
            mock.patch.object(eval_tasks, "FOLLOW_EVERY", 0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    counter_reads = None

    def counters(self):
        if self.counter_reads is None:
            self.counter_reads = [
                {"prompt_tokens": 100.0, "prompt_seconds": 1.0, "completion_tokens": 1000.0, "generation_seconds": 50.0},
                {"prompt_tokens": 600.0, "prompt_seconds": 2.0, "completion_tokens": 3000.0, "generation_seconds": 150.0},
            ]
        reads = self.counter_reads
        return reads.pop(0) if len(reads) > 1 else reads[0]

    def run_job(self, host, **kwargs):
        with mock.patch.object(eval_tasks, "run_cmd", host):
            return eval_tasks.run.apply(kwargs={"task": "bfcl", "mode": "limit", "limit": 2, **kwargs},
                                        task_id="job-1").get()

    def test_happy_path_publishes_and_records(self):
        host = FakeHost()
        job = self.run_job(host)
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["run"], "glm-bfcl-limit2-S")
        self.assertIn("BFCL simple 50.00%", job["results"])
        self.assertEqual(job["log_tail"], "Generating: 100%")
        self.assertIn([eval_tasks.EVAL_RUN, "publish"], host.calls)
        self.assertIn(["docker", "rm", "eval-glm-bfcl-limit2-S"], host.calls)
        self.assertEqual(json.loads(self.redis.data["eval:job:job-1"])["state"], "done")

    def test_failed_run_is_failed_but_still_published(self):
        host = FakeHost(exit_code=1)
        job = self.run_job(host)
        self.assertEqual((job["state"], job["exit_code"]), ("failed", 1))
        self.assertIn([eval_tasks.EVAL_RUN, "publish"], host.calls)

    def test_eval_run_refusing_to_start_fails_the_job(self):
        host = FakeHost(start_output="")
        job = self.run_job(host)
        self.assertEqual(job["state"], "failed")

    def test_bad_input_never_reaches_eval_run(self):
        host = FakeHost()
        with mock.patch.object(eval_tasks, "run_cmd", host):
            job = eval_tasks.run.apply(kwargs={"task": "bfcl; reboot", "mode": "full"}, task_id="job-2").get()
        self.assertEqual(job["state"], "failed")
        self.assertEqual(host.calls, [])

    def test_cancel_while_running_stops_the_container(self):
        host = FakeHost(polls=5)
        original = eval_tasks.update_job

        def update(job_id, client=None, **fields):
            if fields.get("state") == "running":
                original(job_id, client, cancel_requested=True)
            return original(job_id, client, **fields)
        with mock.patch.object(eval_tasks, "update_job", update):
            job = self.run_job(host)
        self.assertEqual(job["state"], "cancelled")
        self.assertIn(["docker", "stop", "eval-glm-bfcl-limit2-S"], host.calls)

    def test_run_metrics_from_counter_deltas(self):
        job = self.run_job(FakeHost())
        mut = job["run_metrics"]["model_under_test"]
        self.assertEqual((mut["prompt_tokens"], mut["completion_tokens"]), (500, 2000))
        self.assertEqual((mut["generation_tokens_per_second"], mut["prompt_tokens_per_second"]), (20.0, 500.0))
        self.assertIn("duration_seconds", job["run_metrics"])

    def test_lock_is_held_during_the_run_and_released_after(self):
        host = FakeHost()
        seen = []
        original = eval_tasks.follow

        def follow(job_id, run, client, sleep=None):
            seen.append(eval_tasks.framework_lock.holder(client))
            return original(job_id, run, client, sleep)
        with mock.patch.object(eval_tasks, "follow", follow):
            job = self.run_job(host)
        self.assertEqual(job["state"], "done")
        self.assertEqual((seen[0]["job_id"], seen[0]["suite"], seen[0]["benchmark"]), ("job-1", "eval", "bfcl"))
        self.assertIsNone(eval_tasks.framework_lock.holder(self.redis))

    def test_waits_for_a_cse_run_holding_framework_then_runs(self):
        eval_tasks.framework_lock.try_acquire(self.redis, "cse-job", "cyberseceval", "mitre")
        waits = []
        original = eval_tasks.update_job

        def update(job_id, client=None, **fields):
            if fields.get("state") == "waiting":
                waits.append(fields["waiting_for"])
                eval_tasks.framework_lock.release(self.redis, "cse-job")
            return original(job_id, client, **fields)
        with mock.patch.object(eval_tasks, "update_job", update):
            job = self.run_job(FakeHost())
        self.assertEqual(job["state"], "done")
        self.assertEqual(waits, ["Framework (held by cyberseceval mitre job cse-job)"])

    def test_cancel_while_waiting_never_starts(self):
        host = FakeHost()
        eval_tasks.framework_lock.try_acquire(self.redis, "cse-job", "cyberseceval", "mitre")
        eval_tasks.update_job("job-1", self.redis, cancel_requested=True)
        job = self.run_job(host)
        self.assertEqual(job["state"], "cancelled")
        self.assertFalse(any(c[:2] == [eval_tasks.EVAL_RUN, "bfcl"] for c in host.calls))
        self.assertEqual(eval_tasks.framework_lock.holder(self.redis)["job_id"], "cse-job")

    def test_redelivered_job_reattaches_instead_of_starting_again(self):
        eval_tasks.update_job("job-1", self.redis, state="running", run="glm-bfcl-limit2-S")
        host = FakeHost(polls=1)
        job = self.run_job(host)
        self.assertEqual(job["state"], "done")
        self.assertFalse(any(c[:2] == [eval_tasks.EVAL_RUN, "bfcl"] for c in host.calls))

    def test_resume_validates_run_name(self):
        host = FakeHost()
        with mock.patch.object(eval_tasks, "run_cmd", host):
            bad = eval_tasks.resume.apply(args=["../etc"], task_id="job-3").get()
            good = eval_tasks.resume.apply(args=["glm-bfcl-limit2-S"], task_id="job-4").get()
        self.assertEqual(bad["state"], "failed")
        self.assertEqual(good["state"], "done")
        self.assertIn([eval_tasks.EVAL_RUN, "resume", "glm-bfcl-limit2-S"], host.calls)


METRICS_TEXT = """# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 1200
llamacpp:prompt_seconds_total 3.5
llamacpp:tokens_predicted_total 45000
llamacpp:tokens_predicted_seconds_total 2100.25
llamacpp:n_decode_total 999
"""


@unittest.skipUnless(eval_tasks, "celery not installed")
class MetricsTest(unittest.TestCase):
    def test_counters_parsed(self):
        c = eval_tasks.framework_counters(lambda path: METRICS_TEXT)
        self.assertEqual(c, {"prompt_tokens": 1200.0, "prompt_seconds": 3.5,
                             "completion_tokens": 45000.0, "generation_seconds": 2100.25})

    def test_missing_counters_or_unreachable(self):
        self.assertIn("missing counters", eval_tasks.framework_counters(lambda p: "# nothing\n")["error"])

        def down(path):
            raise OSError("refused")
        self.assertIn("refused", eval_tasks.framework_counters(down)["error"])

    def test_reload_mid_run_marks_tokens_unavailable(self):
        before = eval_tasks.framework_counters(lambda p: METRICS_TEXT)
        after = dict(before, completion_tokens=10.0)
        m = eval_tasks.run_metrics(before, after, "2026-10-08T10:00:00Z", "2026-10-08T10:30:00Z")
        self.assertEqual(m["duration_seconds"], 1800.0)
        self.assertIn("reloaded", m["unavailable"])
        self.assertNotIn("model_under_test", m)

    def test_resume_merges_segments_into_run_json(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "r1"))
        with open(os.path.join(root, "r1", "run.json"), "w") as fh:
            json.dump({"task": "bfcl"}, fh)
        seg = {"source": "llama-server /metrics", "segments": 1, "duration_seconds": 100.0,
               "model_under_test": {"prompt_tokens": 10, "completion_tokens": 200,
                                    "prompt_seconds": 1.0, "generation_seconds": 10.0}}
        eval_tasks.record_metrics("r1", seg, root)
        total = eval_tasks.record_metrics("r1", seg, root)
        self.assertEqual((total["segments"], total["duration_seconds"]), (2, 200.0))
        self.assertEqual(total["model_under_test"]["completion_tokens"], 400)
        self.assertEqual(total["model_under_test"]["generation_tokens_per_second"], 20.0)
        with open(os.path.join(root, "r1", "run.json")) as fh:
            self.assertEqual(json.load(fh)["task"], "bfcl")


def gpqa_sample(doc_id, filt, extracted, match):
    return {"doc_id": doc_id, "doc": {"Question": "q"}, "target": "(B)", "filter": filt,
            # as lm_eval 0.4.12 writes it: a one-item list holding the JSON messages
            "arguments": {"gen_args_0": {"arg_0": [json.dumps([{"role": "user", "content": f"Question {doc_id}?"}])],
                                         "arg_1": {"max_gen_toks": 8192}}},
            "resps": [["Thinking... The answer is (B)"]], "filtered_resps": [extracted],
            "metrics": ["exact_match"], "exact_match": match}


@unittest.skipUnless(eval_tasks, "celery not installed")
class SamplesTest(unittest.TestCase):
    def write(self, root, name, rows):
        path = os.path.join(root, "glm", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in rows) + "\n")

    def test_one_row_per_question_using_the_headline_filter(self):
        root = tempfile.mkdtemp()
        rows = []
        for doc in range(3):
            rows += [gpqa_sample(doc, "strict-match", "[invalid]", 0.0), gpqa_sample(doc, "flexible-extract", "(B)", 1.0)]
        self.write(root, "samples_gpqa_diamond_cot_zeroshot_2026-10-08T14-00-00.jsonl", rows)
        out = eval_tasks.read_samples(root, offset=1, limit=1)
        task = out["tasks"][0]
        self.assertEqual((task["task"], task["total"], task["offset"]), ("gpqa_diamond_cot_zeroshot", 3, 1))
        item = task["items"][0]
        self.assertEqual((item["doc_id"], item["extracted"], item["target"]), (1, "(B)", "(B)"))
        self.assertEqual(item["scores"], {"exact_match": 1.0})
        self.assertEqual(item["prompt"], "[user]\nQuestion 1?")
        self.assertIn("The answer is (B)", item["response"])

    def test_newest_file_wins_and_long_text_is_clipped(self):
        root = tempfile.mkdtemp()
        self.write(root, "samples_ifeval_2026-10-08T10-00-00.jsonl", [{"doc_id": 0, "resps": [["old"]]}])
        self.write(root, "samples_ifeval_2026-10-08T11-00-00.jsonl", [{"doc_id": 0, "resps": [["x" * 20000]]}])
        item = eval_tasks.read_samples(root)["tasks"][0]["items"][0]
        self.assertTrue(item["response"].startswith("xxx"))
        self.assertIn("more characters", item["response"])

    def test_wrapper_runs_and_bad_names(self):
        self.assertFalse(eval_tasks.read_samples(tempfile.mkdtemp())["available"])
        self.assertEqual(eval_tasks.samples.apply(args=["../etc"]).get()["reason"], "bad run name")


@unittest.skipUnless(eval_tasks, "celery not installed")
class CseRowTest(unittest.TestCase):
    def test_record_cse_stores_the_row_and_publishes(self):
        root = tempfile.mkdtemp()
        host = FakeHost()
        row = {"job_id": "3bf79d63-aaaa", "benchmark": "mitre", "headline": {"value": 50.0}, "extra": "dropped"}
        with mock.patch.object(eval_tasks, "RESULTS_DIR", root), mock.patch.object(eval_tasks, "run_cmd", host):
            out = eval_tasks.record_cse.apply(args=[row]).get()
            bad = eval_tasks.record_cse.apply(args=[{"job_id": "../x"}]).get()
        self.assertTrue(out["ok"])
        with open(os.path.join(root, "_cse", "3bf79d63-aaaa.json")) as fh:
            stored = json.load(fh)
        self.assertEqual((stored["benchmark"], stored["headline"]), ("mitre", {"value": 50.0}))
        self.assertNotIn("extra", stored)
        self.assertIn([eval_tasks.EVAL_RUN, "publish"], host.calls)
        self.assertFalse(bad["ok"])

    def test_compare_uses_publish_rows(self):
        # Only the "publish" entry: patch.dict(sys.modules) would also drop
        # modules Celery imports during the call and break later tests.
        fake = mock.Mock(compare_rows=lambda root: [{"Model": "m", "Task": "IFEval"}])
        saved = sys.modules.get("publish")
        sys.modules["publish"] = fake
        try:
            out = eval_tasks.compare.apply().get()
        finally:
            if saved is None:
                del sys.modules["publish"]
            else:
                sys.modules["publish"] = saved
        self.assertEqual(out["rows"], [{"Model": "m", "Task": "IFEval"}])


@unittest.skipUnless(eval_tasks, "celery not installed")
class StatusTest(unittest.TestCase):
    def test_framework_status(self):
        def get_json(path):
            return {"data": [{"id": "glm-5.3-flash"}]} if path == "/v1/models" else \
                [{"is_processing": True}, {"is_processing": False}]
        status = eval_tasks.framework_status(get_json)
        self.assertEqual((status["model"], status["slots"], status["busy"], status["error"]),
                         ("glm-5.3-flash", 2, 1, None))

    def test_unreachable_framework_reports_error(self):
        def get_json(path):
            raise OSError("connection refused")
        status = eval_tasks.framework_status(get_json)
        self.assertIn("connection refused", status["error"])

    def test_status_loop_writes_key(self):
        redis = FakeRedis()
        with mock.patch.object(eval_tasks, "framework_status", return_value={"model": "m", "busy": 0}), \
                mock.patch.object(eval_tasks, "eval_container_running", return_value=None):
            eval_tasks.status_loop(redis, sleep=lambda s: None, rounds=1)
        status = json.loads(redis.data[eval_tasks.FRAMEWORK_KEY])
        self.assertEqual((status["model"], status["lock"]), ("m", None))


if __name__ == "__main__":
    unittest.main()
