"""Unit tests for cse_tasks.py's use of the shared Framework lock."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
sys.path.insert(0, str(Path(__file__).parent))
# Deployed next to cse_tasks.py; in the repo it lives with the playbooks' files.
sys.path.insert(0, str(Path(__file__).parents[3] / "ansible" / "files" / "framework-lock"))

import cse_tasks  # noqa: E402
import framework_lock  # noqa: E402


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


class FrameworkLockTest(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.states = []
        self.seen_holder = []
        patches = [
            mock.patch.object(cse_tasks, "_lock_client", return_value=self.redis),
            mock.patch.object(cse_tasks.run_benchmark, "update_state",
                              side_effect=lambda state, meta: self.states.append((state, meta))),
            mock.patch.object(cse_tasks, "_run_benchmark", side_effect=self.fake_run),
            mock.patch.object(framework_lock.time, "sleep"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fake_run(self, job_id, benchmark, *rest):
        self.seen_holder.append(framework_lock.holder(self.redis))
        return {"rc": 0, "job": job_id}

    def run_task(self, **kwargs):
        return cse_tasks.run_benchmark.apply(kwargs={"benchmark": "mitre", **kwargs}, task_id="cse-1").get()

    def test_framework_run_holds_the_lock_and_releases_it(self):
        self.assertEqual(self.run_task()["rc"], 0)
        self.assertEqual((self.seen_holder[0]["job_id"], self.seen_holder[0]["suite"]), ("cse-1", "cyberseceval"))
        self.assertEqual(self.states[-1][0], "STARTED")
        self.assertIsNone(framework_lock.holder(self.redis))

    def test_waits_while_an_eval_run_holds_framework(self):
        framework_lock.try_acquire(self.redis, "eval-9", "eval", "bfcl")
        original = framework_lock.acquire

        def acquire(*args, on_wait=None, **kwargs):
            def wait_then_free(holder):
                on_wait(holder)
                framework_lock.release(self.redis, "eval-9")
            return original(*args, on_wait=wait_then_free, **kwargs)
        with mock.patch.object(cse_tasks.framework_lock, "acquire", acquire):
            self.assertEqual(self.run_task()["rc"], 0)
        state, meta = self.states[0]
        self.assertEqual(state, "WAITING")
        self.assertEqual((meta["held_by"]["job_id"], meta["held_by"]["suite"]), ("eval-9", "eval"))
        self.assertEqual(self.states[-1][0], "STARTED")

    def test_gives_up_after_max_wait(self):
        framework_lock.try_acquire(self.redis, "eval-9", "eval", "bfcl")
        with mock.patch.object(cse_tasks, "FRAMEWORK_MAX_WAIT", 0):
            result = self.run_task()
        self.assertEqual(result["rc"], 1)
        self.assertIn("held by eval job eval-9", result["stats_error"])
        self.assertEqual(self.seen_holder, [])

    def test_other_backends_skip_the_lock(self):
        framework_lock.try_acquire(self.redis, "eval-9", "eval", "bfcl")
        self.assertEqual(self.run_task(backend_base_url="http://ollama.lab:11434/v1", backend_model="m")["rc"], 0)
        self.assertEqual(self.seen_holder[0]["job_id"], "eval-9")

    def test_uses_framework(self):
        self.assertTrue(cse_tasks._uses_framework(None))
        self.assertTrue(cse_tasks._uses_framework("http://framework.gibbsgreatly.xyz:8080/v1"))
        self.assertFalse(cse_tasks._uses_framework("http://192.168.1.50:11434/v1"))


if __name__ == "__main__":
    unittest.main()
