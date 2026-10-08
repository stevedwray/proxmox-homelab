"""Unit tests for framework_lock.py. Run with:
python3 -m unittest discover -s terraform/lxc/ansible/files/framework-lock -p "test_*.py"
"""

import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import framework_lock as fl  # noqa: E402


class FakeRedis:
    """The subset of redis-py the lock uses; TTLs are tracked, not enforced."""

    def __init__(self):
        self.data, self.ttl = {}, {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key], self.ttl[key] = value, ex
        return True

    def expire(self, key, seconds):
        self.ttl[key] = seconds

    def delete(self, key):
        self.data.pop(key, None)

    def expire_now(self, key):
        self.delete(key)


class LockTest(unittest.TestCase):
    def setUp(self):
        self.r = FakeRedis()

    def test_first_taker_holds_it_second_waits(self):
        self.assertTrue(fl.try_acquire(self.r, "job-a", "cse", "mitre"))
        self.assertFalse(fl.try_acquire(self.r, "job-b", "eval", "bfcl"))
        self.assertEqual(fl.holder(self.r)["job_id"], "job-a")
        self.assertEqual(self.r.ttl[fl.LOCK_KEY], fl.TTL)

    def test_redelivered_job_takes_its_own_lock_back(self):
        fl.try_acquire(self.r, "job-a", "cse", "mitre")
        self.assertTrue(fl.try_acquire(self.r, "job-a", "cse", "mitre"))

    def test_release_only_frees_our_own_lock(self):
        fl.try_acquire(self.r, "job-a", "cse", "mitre")
        self.assertFalse(fl.release(self.r, "job-b"))
        self.assertIsNotNone(fl.holder(self.r))
        self.assertTrue(fl.release(self.r, "job-a"))
        self.assertIsNone(fl.holder(self.r))

    def test_renew_fails_once_someone_else_holds_it(self):
        fl.try_acquire(self.r, "job-a", "cse", "mitre")
        self.r.ttl[fl.LOCK_KEY] = 5
        self.assertTrue(fl.renew(self.r, "job-a"))
        self.assertEqual(self.r.ttl[fl.LOCK_KEY], fl.TTL)
        self.r.expire_now(fl.LOCK_KEY)
        fl.try_acquire(self.r, "job-b", "eval", "bfcl")
        self.assertFalse(fl.renew(self.r, "job-a"))

    def test_acquire_waits_reports_holder_then_takes_it(self):
        fl.try_acquire(self.r, "job-a", "cse", "mitre")
        seen, sleeps = [], []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                fl.release(self.r, "job-a")
        ok = fl.acquire(self.r, "job-b", "eval", "bfcl", on_wait=seen.append, poll=7, sleep=sleep)
        self.assertTrue(ok)
        self.assertEqual(sleeps, [7, 7])
        self.assertEqual([h["job_id"] for h in seen], ["job-a", "job-a"])
        self.assertEqual(fl.holder(self.r)["benchmark"], "bfcl")

    def test_acquire_gives_up_on_cancel_or_timeout(self):
        fl.try_acquire(self.r, "job-a", "cse", "mitre")
        self.assertFalse(fl.acquire(self.r, "job-b", "eval", "bfcl", cancelled=lambda: True, sleep=lambda s: None))
        self.assertFalse(fl.acquire(self.r, "job-b", "eval", "bfcl", poll=10, max_wait=30, sleep=lambda s: None))
        self.assertEqual(fl.holder(self.r)["job_id"], "job-a")

    def test_held_renews_then_releases_even_on_error(self):
        fl.try_acquire(self.r, "job-a", "cse", "mitre")
        with self.assertRaises(RuntimeError):
            with fl.held(self.r, "job-a", renew_every=0.01):
                self.r.ttl[fl.LOCK_KEY] = 1
                time.sleep(0.1)
                self.assertEqual(self.r.ttl[fl.LOCK_KEY], fl.TTL)
                raise RuntimeError("run failed")
        self.assertIsNone(fl.holder(self.r))

    def test_garbage_value_is_still_a_holder(self):
        self.r.data[fl.LOCK_KEY] = "not json"
        self.assertFalse(fl.try_acquire(self.r, "job-a", "cse", "mitre"))
        self.assertEqual(fl.holder(self.r)["raw"], "not json")
        self.assertEqual(json.loads(json.dumps(fl.holder(self.r)))["job_id"], None)


if __name__ == "__main__":
    unittest.main()
