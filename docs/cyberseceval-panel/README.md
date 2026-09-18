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

**Not started.** `plan.md` is written and ready for step-by-step execution
(by a local model via `implement-step`, or manually). No step has been run
yet.

## Step hand-backs

(none yet — each step's real result gets recorded here as it lands, per
`docs/agent-design/README.md`)
