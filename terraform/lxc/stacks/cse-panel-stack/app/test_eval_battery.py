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

    def lrem(self, key, count, value):
        self.lists[key] = [v for v in self.lists.get(key, []) if v != value]

    def delete(self, key):
        self.data.pop(key, None)


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

    def test_old_page_redirects_to_the_dash_panel(self):
        with mock.patch.dict(os.environ, {"LAB_DOMAIN": "lab.example"}):
            resp = self.client.get("/eval", follow_redirects=False)
        self.assertEqual((resp.status_code, resp.headers["location"]), (307, "https://cse-panel.lab.example/"))

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

    def test_delete_removes_the_run_and_its_resumes_and_asks_the_worker(self):
        first, other = self.submit().json()["submitted"][0], self.submit().json()["submitted"][0]
        eval_battery._put_job(first, state="failed", run="glm-bfcl-S")
        eval_battery._put_job(other, state="done", run="glm-ifeval-S")
        resumed = self.client.post(f"/eval/api/jobs/{first}/resume").json()["submitted"][0]
        eval_battery._put_job(resumed, state="running")
        self.assertEqual(self.client.delete(f"/eval/api/jobs/{first}").status_code, 409)  # resume still going
        eval_battery._put_job(resumed, state="done")
        res = self.client.delete(f"/eval/api/jobs/{first}").json()
        self.assertEqual((sorted(res["deleted"]), res["run"]), (sorted([first, resumed]), "glm-bfcl-S"))
        self.assertEqual(self.sent[-1], ("eval_tasks.delete_run", ["glm-bfcl-S"], None, "eval-runner-ctl"))
        self.assertEqual([j["id"] for j in self.client.get("/eval/api/state").json()["jobs"]], [other])
        self.assertEqual(self.client.delete(f"/eval/api/jobs/{first}").status_code, 404)

    def test_delete_a_job_that_never_got_a_run_only_clears_the_list(self):
        job = self.submit().json()["submitted"][0]
        self.assertEqual(self.client.delete(f"/eval/api/jobs/{job}").status_code, 409)  # queued
        eval_battery._put_job(job, state="cancelled")
        sent = len(self.sent)
        self.assertEqual(self.client.delete(f"/eval/api/jobs/{job}").json()["run"], None)
        self.assertEqual(len(self.sent), sent)
        self.assertEqual(self.client.get("/eval/api/state").json()["jobs"], [])

    def test_publish_goes_to_control_queue(self):
        self.client.post("/eval/api/publish")
        self.assertEqual(self.sent[-1][0::3], ("eval_tasks.publish", "eval-runner-ctl"))

    def test_state_includes_framework_status(self):
        self.redis.set("eval:framework", json.dumps({"model": "glm-5.3-flash", "busy": 0, "slots": 4}))
        self.assertEqual(self.client.get("/eval/api/state").json()["framework"]["model"], "glm-5.3-flash")

    def test_samples_ask_the_ctl_worker_for_the_jobs_run(self):
        self.redis.set("eval:job:j1", json.dumps({"run": "glm-gpqa-limit1-S", "state": "done"}))
        page = {"available": True, "tasks": []}
        with mock.patch.object(eval_battery.celery_app, "send_task",
                               return_value=mock.Mock(get=lambda timeout: page)) as send:
            body = self.client.get("/eval/api/jobs/j1/samples?offset=10&limit=500").json()
        self.assertEqual(body, page)
        self.assertEqual(send.call_args.args, ("eval_tasks.samples",))
        self.assertEqual(send.call_args.kwargs, {"args": ["glm-gpqa-limit1-S", 10, 25], "queue": "eval-runner-ctl"})
        self.assertEqual(self.client.get("/eval/api/jobs/nope/samples").status_code, 409)

    def test_reports_link_is_the_shared_folder(self):
        self.assertTrue(eval_battery.LINKS["Reports folder"].endswith("?dir=/eval-runner"))

    def test_compare_asks_the_ctl_worker(self):
        import app as panel_app
        with mock.patch.object(panel_app.celery_app, "send_task",
                               return_value=mock.Mock(get=lambda timeout: {"rows": [{"Model": "m"}]})) as send:
            body = TestClient(panel_app.app).get("/compare").json()
        self.assertEqual(body["rows"], [{"Model": "m"}])
        self.assertEqual(send.call_args.kwargs, {"queue": "eval-runner-ctl"})

    def test_cse_summary_carries_the_headline(self):
        import app as panel_app
        head = {"metric": "malicious %", "value": 50.0, "better": "lower", "n": 4}
        res = mock.Mock(state="SUCCESS", result={"rc": 0, "headline": head, "finished_at": "2026-10-08T05:00:00"})
        with mock.patch.object(panel_app, "AsyncResult", return_value=res), \
                mock.patch.object(panel_app, "_get_job_meta", return_value={"benchmark": "mitre"}):
            entry = panel_app._job_summary("cse-1")
        self.assertEqual((entry["headline"], entry["finished_at"]), (head, "2026-10-08T05:00:00"))

    def test_main_app_mounts_the_page(self):
        import app as panel_app
        paths = {r.path for r in panel_app.app.routes}
        self.assertIn("/eval/api/jobs", paths)

    def test_framework_endpoint_shows_lock_holder_and_model(self):
        import app as panel_app
        self.redis.set("framework:run-lock", json.dumps({"job_id": "e1", "suite": "eval", "benchmark": "bfcl"}))
        self.redis.set("eval:framework", json.dumps({"model": "glm-5.3-flash", "busy": 1, "slots": 4}))
        def redis_json(key):
            raw = self.redis.get(key)
            return json.loads(raw) if raw else None
        with mock.patch.object(panel_app, "_redis_json", redis_json):
            body = TestClient(panel_app.app).get("/framework").json()
        self.assertEqual((body["lock"]["suite"], body["model"], body["busy"]), ("eval", "glm-5.3-flash", 1))
        self.assertIsNone(body["builds"])  # not published in this fixture

    def test_waiting_cse_job_is_labelled_with_the_holder(self):
        import app as panel_app
        res = mock.Mock(state="WAITING", info={"waiting_for": "Framework",
                                               "held_by": {"job_id": "e1", "suite": "eval", "benchmark": "bfcl"}})
        with mock.patch.object(panel_app, "AsyncResult", return_value=res), \
                mock.patch.object(panel_app, "_get_job_meta", return_value={"benchmark": "mitre"}):
            entry = panel_app._job_summary("cse-1")
        self.assertEqual(entry["state_label"], "Waiting for Framework (eval bfcl)")
        self.assertIn("WAITING", panel_app.NON_TERMINAL_STATES)


if __name__ == "__main__":
    unittest.main()
