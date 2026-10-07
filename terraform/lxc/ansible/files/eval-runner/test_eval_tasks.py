"""Unit tests for eval_tasks.py (the panel's Celery worker), with eval-run,
docker and Redis faked. Skipped where celery isn't installed (it's only in
the worker's venv on ai-services-stack). Run with:
python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner -p "test_*.py"
"""

import json
import subprocess
import unittest
from unittest import mock

try:
    import eval_tasks
except ImportError:  # celery not installed locally
    eval_tasks = None


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value


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
            mock.patch.object(eval_tasks, "framework_idle", return_value=True),
            mock.patch.object(eval_tasks.time, "sleep"),
            mock.patch.object(eval_tasks, "FOLLOW_EVERY", 0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

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

    def test_waits_for_busy_framework_then_runs(self):
        host = FakeHost()
        with mock.patch.object(eval_tasks, "framework_idle", side_effect=[False, False, True]):
            job = self.run_job(host)
        self.assertEqual(job["state"], "done")

    def test_cancel_while_waiting_never_starts(self):
        host = FakeHost()
        eval_tasks.update_job("job-1", self.redis, cancel_requested=True)
        with mock.patch.object(eval_tasks, "framework_idle", return_value=False):
            job = self.run_job(host)
        self.assertEqual(job["state"], "cancelled")
        self.assertFalse(any(c[:2] == [eval_tasks.EVAL_RUN, "bfcl"] for c in host.calls))

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
        self.assertEqual(json.loads(redis.data[eval_tasks.FRAMEWORK_KEY])["model"], "m")


if __name__ == "__main__":
    unittest.main()
