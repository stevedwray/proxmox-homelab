"""Unit tests for eval_battery.py (cse-panel's Eval battery page), with
Celery and Redis faked. Needs fastapi, httpx and celery (skipped
otherwise). Run with:
python3 -m unittest discover -s terraform/lxc/stacks/cse-panel-stack/app -p "test_*.py"
"""

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import eval_battery
except ImportError:
    eval_battery = None


class FakeRedis:
    def __init__(self):
        self.data, self.lists = {}, {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start:end + 1]

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]


@unittest.skipUnless(eval_battery, "fastapi/httpx/celery not installed")
class EvalBatteryTest(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.sent = []
        self.revoked = []
        counter = iter(range(1, 1000))

        def send_task(name, args=None, kwargs=None, queue=None):
            self.sent.append((name, args, kwargs, queue))
            return mock.Mock(id=f"job-{next(counter)}")
        patches = [
            mock.patch.object(eval_battery, "_redis", return_value=self.redis),
            mock.patch.object(eval_battery.celery_app, "send_task", side_effect=send_task),
            mock.patch.object(eval_battery.celery_app.control, "revoke", side_effect=self.revoked.append),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app = FastAPI()
        app.include_router(eval_battery.router)
        self.client = TestClient(app)

    def submit(self, **body):
        return self.client.post("/eval/api/jobs", json={"tasks": ["bfcl"], **body},
                                headers={"X-Authentik-Username": "steve"})

    def test_page_renders_every_benchmark(self):
        page = self.client.get("/eval").text
        for task in eval_battery.TASKS:
            self.assertIn(f'value="{task}"', page)
        self.assertIn("Results table (Nextcloud Tables)", page)

    def test_submit_queues_one_job_per_benchmark_in_order(self):
        res = self.client.post("/eval/api/jobs", json={"tasks": ["gpqa", "ifeval"], "mode": "limit", "limit": 5,
                                                       "note": "smoke", "budget_32k": True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual([(n, k["task"], k["limit"], k["budget_32k"], q) for n, _, k, q in self.sent],
                         [("eval_tasks.run", "gpqa", 5, True, "eval-runner"),
                          ("eval_tasks.run", "ifeval", 5, True, "eval-runner")])
        state = self.client.get("/eval/api/state").json()
        self.assertEqual([j["task"] for j in state["jobs"]], ["ifeval", "gpqa"])  # newest first
        self.assertEqual(state["jobs"][0]["state"], "queued")

    def test_bad_requests_are_rejected_before_queueing(self):
        for body in ({"tasks": ["rm -rf"]}, {"tasks": ["bfcl"], "mode": "all"},
                     {"tasks": ["bfcl"], "mode": "limit", "limit": 0},
                     {"tasks": ["bfcl"], "budget_32k": True}, {"tasks": ["bfcl"], "note": "a\nb"},
                     {"tasks": []}):
            res = self.client.post("/eval/api/jobs", json=body)
            self.assertIn(res.status_code, (400, 422), body)
        self.assertEqual(self.sent, [])

    def test_cancel_queued_revokes_and_running_asks_worker(self):
        queued = self.submit().json()["submitted"][0]
        self.client.post(f"/eval/api/jobs/{queued}/cancel")
        self.assertEqual(self.revoked, [queued])
        self.assertEqual(json.loads(self.redis.data[f"eval:job:{queued}"])["state"], "cancelled")

        running = self.submit().json()["submitted"][0]
        eval_battery._put_job(running, state="running", run="glm-bfcl-S")
        self.client.post(f"/eval/api/jobs/{running}/cancel")
        self.assertEqual(self.sent[-1], ("eval_tasks.cancel", [running], None, "eval-runner-ctl"))
        self.assertEqual(self.client.post(f"/eval/api/jobs/{queued}/cancel").status_code, 409)

    def test_resume_only_for_failed_jobs_with_a_run(self):
        job = self.submit().json()["submitted"][0]
        self.assertEqual(self.client.post(f"/eval/api/jobs/{job}/resume").status_code, 409)
        eval_battery._put_job(job, state="failed", run="glm-bfcl-S")
        res = self.client.post(f"/eval/api/jobs/{job}/resume")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.sent[-1][0], "eval_tasks.resume")
        self.assertEqual(self.sent[-1][2]["run_name"], "glm-bfcl-S")

    def test_publish_goes_to_control_queue(self):
        self.client.post("/eval/api/publish")
        self.assertEqual(self.sent[-1][0::3], ("eval_tasks.publish", "eval-runner-ctl"))

    def test_state_includes_framework_status(self):
        self.redis.set("eval:framework", json.dumps({"model": "glm-5.3-flash", "busy": 0, "slots": 4}))
        self.assertEqual(self.client.get("/eval/api/state").json()["framework"]["model"], "glm-5.3-flash")

    def test_main_app_mounts_the_page(self):
        import app as panel_app
        paths = {r.path for r in panel_app.app.routes}
        self.assertIn("/eval/api/jobs", paths)


if __name__ == "__main__":
    unittest.main()
