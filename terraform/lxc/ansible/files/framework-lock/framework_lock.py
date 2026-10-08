"""One benchmark run at a time on Framework (docs/benchmark-panel/plan.md, C).

Shared by both benchmark workers, which already talk to cse-panel's Redis:
cse-controller's cse_tasks.py (CyberSecEval) and ai-services-stack's
eval_tasks.py (the eval battery). Each copies this file next to itself
(deploy-cse-controller.yml, deploy-ai-services-stack.yml).

The lock is one Redis key holding its holder as JSON:

  framework:run-lock  {"job_id", "suite", "benchmark", "started"}

It is set with NX and a short TTL, and the holder renews it every
RENEW_EVERY seconds while its run is active (held()). A worker that dies
without releasing it frees Framework within TTL seconds. A job that is
redelivered after a worker restart (both workers use acks_late) has the
same job id, so it takes its own lock back straight away instead of
waiting for it to expire.

Only benchmark runs take the lock (decision 2); interactive clients
(Open WebUI, deep-research) never wait for it.
"""

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

LOCK_KEY = "framework:run-lock"
TTL = 180
RENEW_EVERY = 60
POLL = 30


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def holder(client):
    """The current holder's record, or None if Framework is free."""
    raw = client.get(LOCK_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"job_id": None, "raw": str(raw)}


def try_acquire(client, job_id, suite, benchmark):
    """Take the lock if it's free or already ours. Returns True if held."""
    value = json.dumps({"job_id": job_id, "suite": suite, "benchmark": benchmark, "started": _now()})
    if client.set(LOCK_KEY, value, nx=True, ex=TTL):
        return True
    current = holder(client)
    if current and current.get("job_id") == job_id:
        client.set(LOCK_KEY, value, ex=TTL)
        return True
    return False


def _ours(client, job_id):
    current = holder(client)
    return bool(current) and current.get("job_id") == job_id


def renew(client, job_id):
    """Extend our lock's TTL. False if it is no longer ours.

    Check-then-act rather than a Lua script: another worker can only take
    the key after it expires, and we renew at a third of the TTL."""
    if not _ours(client, job_id):
        return False
    client.expire(LOCK_KEY, TTL)
    return True


def release(client, job_id):
    """Free the lock if it is ours. Never removes another job's lock."""
    if not _ours(client, job_id):
        return False
    client.delete(LOCK_KEY)
    return True


def acquire(client, job_id, suite, benchmark, on_wait=None, cancelled=None,
            poll=POLL, max_wait=None, sleep=None):
    """Wait until the lock is ours. on_wait(holder) is called before each
    wait, so the caller can show who it is waiting for. Returns False if
    cancelled() turns true or max_wait seconds pass first."""
    sleep = sleep or time.sleep
    waited = 0
    while not try_acquire(client, job_id, suite, benchmark):
        if cancelled and cancelled():
            return False
        if max_wait is not None and waited >= max_wait:
            return False
        if on_wait:
            on_wait(holder(client))
        sleep(poll)
        waited += poll
    return True


@contextmanager
def held(client, job_id, renew_every=RENEW_EVERY):
    """Keep our lock renewed for the duration of the block, then release it."""
    stop = threading.Event()

    def keep_renewing():
        while not stop.wait(renew_every):
            try:
                renew(client, job_id)
            except Exception:  # Redis blip: the next round tries again
                pass

    thread = threading.Thread(target=keep_renewing, daemon=True, name="framework-lock-renew")
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(5)
        try:
            release(client, job_id)
        except Exception:  # unreachable Redis: the TTL frees it
            pass
