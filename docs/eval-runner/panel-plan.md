# eval-runner control panel (an "Eval battery" page in cse-panel)

Status: **planned (2026-10-02), not built.** Operator decisions so far:
- it lives in the existing CyberSecEval panel, as a tab, not as a
  separate panel;
- the first version covers starting runs, watching and controlling them,
  publishing and links, and Framework status.

## Goal

Start, watch and control eval-runner benchmark runs (GPQA, IFEval, BFCL,
AgentBench, RepoBench) from a web page, as `cse-panel` already does for
CyberSecEval, instead of over `ssh root@ai-services-stack eval-run …`.
Results keep flowing to Nextcloud exactly as now.

## How it fits (mirrors cse-panel's own design)

```
browser -> Traefik + Authentik forward-auth -> cse-panel-stack (mgmt_seg, pve-tiny)
             panel-web: existing CSE pages + new /eval page (eval_battery.py)
             Redis: broker + results; queues "celery" (CSE) and "eval-runner" (new)
                                   ^ 6379, outbound from ai_seg only (new MikroTik rule)
ai-services-stack (ai_seg, pve-tiny)
             eval-runner-worker (systemd, Celery, queue eval-runner, concurrency 1)
               -> /usr/local/bin/eval-run (unchanged) -> eval containers -> Framework :8080
               -> writes Framework status + run progress into Redis
```

- **The panel never reaches ai_seg or Framework.** The worker connects out
  to the panel's Redis, as cse-controller's worker does from `cse_seg`.
- **Framework status comes from the worker.** ai-services-stack can already
  reach `framework:8080`; the panel in `mgmt_seg` can't, and doesn't need
  to. Every 30 s a background loop in the worker writes `eval:framework`:
  model id, slots busy, checked-at.
- **`eval-run` stays the single entry point.** The worker shells out to it,
  so the CLI and the panel can't drift. Its one-run-at-a-time guard still
  applies to both.
- **Separate queue.** Eval tasks are routed to `eval-runner`, so the CSE
  worker (default queue) never takes them and vice versa.

## Features (v1)

1. **Start runs.**
   - Pick one or more benchmarks.
   - Choose full, pilot, or `--limit N`.
   - Add a note; optionally use the 32k budget (GPQA/IFEval only).
   - Each benchmark is one queued job, and the worker runs them in
     submission order.
2. **Watch and control.**
   - A list of jobs: queued, waiting for Framework, running, done or
     failed.
   - For each job: run name, elapsed time, and the last 20 log lines,
     refreshed every 10 s.
   - Cancel works on queued jobs (revoke) and running ones
     (`docker stop eval-<run>`).
   - Resume an interrupted run (`eval-run resume`).
3. **Publish and links.**
   - Every finished run is published automatically.
   - A "Publish now" button.
   - Links to the Nextcloud Tables table and the `Reports/eval-runner`
     folder.
4. **Framework status.**
   - The served model, slot state, and when it was last checked.
   - Before a job starts, the worker waits until Framework's slots are
     idle (polling every 60 s, up to 12 h), so an eval run doesn't land on
     top of a CSE suite. The page shows "waiting for Framework" while it
     does.

## Steps

1. **`eval_tasks.py`** (in `terraform/lxc/ansible/files/eval-runner/`),
   the Celery task module:
   - **Tasks:**
     - `run` (wait for idle Framework, `eval-run <task> …`, follow the
       container, `eval-run publish`, return `eval-run results <run>`);
     - `resume`;
     - `cancel`;
     - `publish`.
   - **Status loop:** a background thread, started on `worker_ready`.
   - **Celery settings:** `task_acks_late`, prefetch 1,
     `visibility_timeout` 48 h (longer than the longest run; see
     reference_celery_redis_visibility_timeout_redelivery).
   - **Tests:** unit tests with `eval-run`, `docker` and Redis faked.
2. **Worker deploy:** a new task block in `deploy-ai-services-stack.yml`'s
   eval-runner play. It installs:
   - a venv under `/opt/eval-runner-worker` (`celery==5.4.0`,
     `redis==5.2.1`, the same pins as cse-panel);
   - the task module;
   - a systemd unit `eval-runner-worker.service`:
     `celery -A eval_tasks worker -Q eval-runner --concurrency 1`,
     restart always, `CELERY_BROKER_URL` pointing at cse-panel's Redis.
3. **Panel page:** `eval_battery.py` in `cse-panel-stack/app/`.
   - A FastAPI `APIRouter` under `/eval`:
     - the HTML page;
     - JSON endpoints `/eval/framework`, `/eval/jobs` (GET/POST),
       `/eval/jobs/{id}` (GET/DELETE), `/eval/jobs/{id}/resume` and
       `/eval/publish`.
   - `app.py` gets two lines: include the router, and a nav link.
   - Tests use a fake Celery and a fake Redis.
4. **Network:** `ansible/00-initial-setup/mikrotik-firewall-eval-runner-panel.yml`,
   a copy of `mikrotik-firewall-cse-panel-cross-zone.yml` with one
   forward rule: `192.168.50.11 -> LAB_IP_CSE_PANEL:6379`, inserted
   before the first forward drop. The operator runs it (MikroTik
   credentials).
5. **Deploy order:** the MikroTik rule first, then ai-services-stack (the
   worker), then cse-panel-stack (the page). Each step goes through the
   normal production approval flow, on pve-tiny with
   `./with-secrets-prod-tiny`.
6. **End-to-end check, without the GPU:**
   - submit a `--limit 1` BFCL job from the page, aimed at the selftest
     mock;
   - the worker runs it, the page shows the log tail and the finished
     state, and the publish is triggered.
   - A real Framework smoke run only with the operator's go-ahead.

## Open decisions

- **Sharing Framework with CSE.** v1 makes eval jobs wait for idle
  slots, and leaves the CSE worker unchanged. A true shared lock means
  editing `cse_tasks.py`, which another session is changing on
  `fix/cse-report-transcript-content`. Revisit after that merges.
- **Redis has no password.** The firewall is its only gate, exactly as
  for cse-controller. This plan adds one more allowed source, so a
  compromised ai-services-stack could enqueue CSE jobs as well as eval
  jobs. Options:
  - accept it, the same trust level as cse-controller;
  - add a Redis password, which touches the CSE worker and panel, so it
    needs coordinating with the CSE session.
- **Merge order.** This branches from `task/eval-runner`. It touches
  `cse-panel-stack/app/app.py` (two lines) and adds files. The CSE
  branch changes 13 lines of the same `app.py`. A small manual merge is
  likely; whichever lands second resolves it.
