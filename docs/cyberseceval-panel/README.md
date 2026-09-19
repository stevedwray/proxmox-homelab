# CyberSecEval Control Panel — planning workspace

Entrypoint per `docs/workflow/documentation-workspaces.md`. `plan.md` is the
step-by-step plan (`docs/agent-design/step-packet-schema.md` shape); this
file is the durable status record and where each step's hand-back gets
written (see `docs/agent-design/README.md`'s process).

## What this is

A web-based control panel for triggering CyberSecEval benchmark runs against
`cse-controller`/`cse-code-eval` and watching their progress live, instead of
the ad hoc Ansible-driven shell scripts used so far this implementation pass.
Requested 2026-09-19, after running a manual small-batch test made clear how
much repeated manual work (writing throwaway scripts, `docker exec`, reading
raw log files) each run currently takes.

## Architecture, in one paragraph

A new stack, `cse-panel-stack`, on `mgmt_seg` — the existing home for
every ops/dashboard stack in this repo (Grafana/Graylog/Portainer,
confirmed via `terraform/lxc/network/pve.yaml`) — runs Redis (the Celery
broker/result backend), Flower (Celery's own monitoring UI — reused as-is
for progress display, not rebuilt), and a small bespoke FastAPI app
(`panel-web`) that only handles job submission. **Placed on `pve-tiny`,
not `pve`** (operator's choice, 2026-09-19): `mgmt_seg` is already
defined on `pve-tiny` too (same VLAN/subnet as `pve`'s, MikroTik trunk
already tagged) with zero occupants so far — this is the first thing to
land there, not a new zone-extension project. A Celery **worker** process
is added to `cse-controller` itself (not a separate reachable service),
because that's where the actual PurpleLlama venv, datasets, and `cse-kali`
agent SSH key already live — the worker connects *out* to Redis in
`mgmt_seg`, which is the one new cross-zone firewall rule this needs
(`cse_seg -> mgmt_seg:6379`). Benchmark run logs also start forwarding to
Graylog as part of this work, fixing a real, already-confirmed gap
(`cse-controller`/`cse-code-eval` currently use the Docker default `json-file`
log driver, not `syslog` like every other stack).

## Operator decisions already made (2026-09-19)

- Zone: `mgmt_seg`, matching every existing dashboard stack.
- Trigger mechanism: a real job queue (Celery + Redis), not a bespoke REST
  API on `cse-controller` or an SSH-based trigger.
- Progress display: hybrid — bespoke UI for triggering, Flower (reused, not
  built) plus Graylog/Grafana for live status and log drill-down.
- Build scope for this pass: write the full plan now; implementation happens
  afterward, one step at a time.

## Status

**All 14 file-authoring steps (Parts A/B/C) executed 2026-09-19.**
Everything up to the operator-only deploy actions is done and gated —
no `terragrunt apply`, `provision.sh`, or real MikroTik mutation has
happened yet. Executed directly (not via a local model's
`implement-step` loop), but every step's own gates were actually run,
not assumed.

## Step hand-backs

All 14 steps (`cse-panel-01` through `cse-panel-14`) landed with every
`critical: true` gate passing for real (not "looks right" — each YAML/
compose file was parsed, each Ansible playbook syntax-checked with the
real `ansible-playbook` binary, each Python file `py_compile`d and, for
`app.py`, actually executed to confirm no runtime error). Files: see
`git log` / `git show` on this commit for the full list (new
`cse-panel-stack` directory, new `environments/pve-tiny/cse-panel-stack`
terragrunt entrypoint, edits to `cse-controller`'s compose/deploy
playbook, new firewall playbook, `.env`/`variables.tf`/`main.tf`
additions, `pve-tiny.yaml` zone registration).

**Real bugs found and fixed while executing, not assumed away**
(the plan's own literal content was wrong in these ways until now):

1. `app.py`'s homepage route had an f-string that would throw a real
   `NameError` on first load (`${{'{LAB_DOMAIN}'}}` inside an f-string
   evaluates `{LAB_DOMAIN}` as a live expression, not a literal).
   Fixed: pass `LAB_DOMAIN` as a real env var, read via
   `os.environ.get`. Verified by actually calling the function, not
   just `py_compile`.
2. The `STACK_CONTRACT.md` gate referenced
   `terraform/lxc/scripts/validate-stack-metadata.sh` (wrong path --
   no `scripts/` subdirectory) with a `cse-panel-stack` positional arg
   the script doesn't accept at all, and the script itself only
   validates a fixed list of already-*active* stacks, so it could
   never have caught a real problem with this one anyway. Fixed the
   gate's command and scope, and documented the real limitation.
3. `deploy-cse-controller.yml`'s worker-support tasks (`cse-panel-11`/
   `cse-panel-12` in the original plan) were missing the actual copy
   task that writes `cse_tasks.py` to
   `/srv/cyberseceval/config/cse_tasks.py` -- without it, the worker's
   `PYTHONPATH=/srv/cyberseceval/config` has nothing to import.
4. The biggest one: `worker.env`'s write task was originally placed
   *after* `deploy-cse-controller.yml`'s "Validate docker compose
   configuration"/"Start controller container" tasks. Since the
   `worker` service's `env_file` points at that exact path, this would
   have broken `cse-controller`'s **entire** deploy on a fresh apply --
   `docker compose config` genuinely fails with "env file not found"
   the moment it runs, confirmed by actually reproducing it locally
   with a real `docker compose config` call. Fixed by moving the task
   to right after "Create stack directory", well before compose ever
   reads the file. Re-verified with a second real `docker compose
   config` call, this time with the file present -- passes.

`terragrunt plan` for `cse-panel-stack` (read-only, real Proxmox API
call) also confirmed clean: 5 to add, 0 to change, 0 to destroy, correct
IP (`192.168.20.30/24`), VMID (`20030`), zone (`mgmt_seg`), and node
(`pve-tiny`) -- this also caught that `lab_ip_cse_panel` needed adding
to `variables.tf`/`main.tf`'s hardcoded template-vars list, not just
`.env` (same class of gap as the earlier `cse_seg` lesson).

**Not done yet** (the 5 operator-only prose actions at the end of
`plan.md`): `terragrunt apply`, `provision.sh` redeploys for both
`cse-panel-stack` and `cse-controller`, the real MikroTik firewall run,
and end-to-end verification with a real submitted job. All still need
the normal production approval flow before running.
