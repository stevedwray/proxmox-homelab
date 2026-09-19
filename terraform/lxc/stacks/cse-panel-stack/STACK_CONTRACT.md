# cse-panel-stack — Stack Contract

## Purpose

Web control panel for triggering CyberSecEval benchmark runs against
`cse-controller`/`cse-code-eval` and viewing their live progress, replacing
the ad hoc Ansible-driven shell scripts used earlier in this
implementation (see
`docs/cyberseceval-implementation/current-state.md`). Does not run any
benchmark itself — it only submits jobs to a Celery worker that runs on
`cse-controller` (see `docs/cyberseceval-panel/plan.md` Part B), where the
actual PurpleLlama checkout/datasets/agent keys live.

## Network

| Field   | Value |
|---|---|
| Zone | `mgmt_seg` (VLAN 20) |
| IP | `192.168.20.30/24` |
| Gateway | `192.168.20.1` |
| VMID | 20030 |
| Node | `pve-tiny` (not `pve` — see below) |

`mgmt_seg` is the same physical VLAN/subnet as `pve`'s `mgmt_seg`
(where Grafana/Graylog/Portainer actually run), already defined on
`pve-tiny` for exactly this kind of move but with zero occupants until
this stack — so this shares the zone's existing cross-zone firewall
rules (e.g. `edge_seg -> mgmt_seg` forward-auth) automatically, without
being on the same physical node as those other three stacks.

Reachable from `edge_seg` (Traefik forward-auth, matching every other
mgmt_seg web UI) and reachable *from* `cse_seg` on port 6379 only (the
worker on `cse-controller` connecting out to this stack's Redis) — see
`docs/cyberseceval-panel/plan.md`'s cross-zone firewall step. This stack
does not itself reach into `cse_seg`; the connection is always initiated
from the isolated side outward, matching `cse_seg`'s own default-deny
design (narrow egress allows, never inbound).

## Inputs

None via `.env`/SOPS beyond the standard `lab_ip_cse_panel`/`lab_gw_mgmt`
template variables. `panel-web` trusts the `X-Authentik-Username`/
`X-Authentik-Email` headers Traefik's forward-auth adds (same pattern as
`netbox-stack`'s `REMOTE_AUTH_HEADER`) for attributing who submitted a
job — not for authorization; Authentik/Traefik forward-auth is the actual
access gate.

## Provides

| Service | Port | Protocol |
|---|---|---|
| `panel-web-http` | 8000 | tcp |
| `flower-http` | 5555 | tcp |

Both exposed to the browser only through Traefik/Authentik forward-auth
(see `edge.yaml`), never directly.

## Dependencies

| Stack | Why |
|---|---|
| Harbor, via Traefik/`edge_seg` | Docker image pulls (`redis`, `flower`, `python:3.10-slim`, all via Harbor's Docker Hub proxy-cache) |
| Authentik-stack | forward-auth for both `panel-web` and `flower`'s browser routes |
| Proxy-stack (Traefik) | Ingress routing for both routes |
| `cse-controller` (cross-zone, `cse_seg`) | The actual benchmark execution -- this stack only submits jobs and displays their status; the Celery worker consuming them runs on `cse-controller`, not here |

## Persistent State

- `/srv/cse-panel/redis-data` — Redis's `appendonly` persistence, so
  queued/recent job state survives a container restart. Not a durable-nvme
  extra mount (this is dashboard state, not benchmark data) — ordinary
  LXC rootfs storage is sufficient.
- `/srv/cse-panel/app` — `panel-web`'s own application code
  (`app.py`/`requirements.txt`), written by the deploy playbook, not
  baked into the image (matches `cse-controller`'s own bind-mount-not-image
  convention).

## What May Depend on This Stack

Nothing yet — this is a leaf/operator-facing stack, not infrastructure
other stacks build on.

## What Must Not Be Edited Casually

- `panel-web`'s image stays a stock `python:3.10-slim`, not a custom
  build — its code lives in the bind-mounted `/srv/cse-panel/app`
  directory specifically so a container recreate never loses
  hand-maintained application code, same reasoning as `cse-controller`'s
  own `STACK_CONTRACT.md`.
- The cross-zone firewall rule this stack depends on
  (`cse_seg -> mgmt_seg:6379`) is scoped to `cse-controller`'s specific
  source IP, not the whole `cse_seg` subnet — do not widen it to a
  subnet-wide allow without a real reason; see the firewall step's own
  comment for why.

## Playbook

`deploy-cse-panel-stack` (roles: `lxc_base`, `docker_base`)

## Implementation Files

| File | Role |
|---|---|
| `terraform/lxc/stacks/cse-panel-stack/stack.yaml` | Terraform-side stack definition |
| `terraform/lxc/stacks/cse-panel-stack/docker-compose.yml` | Redis/Flower/panel-web container definitions |
| `terraform/lxc/stacks/cse-panel-stack/app/app.py` | panel-web's FastAPI application |
| `terraform/lxc/stacks/cse-panel-stack/edge.yaml` | Traefik/Authentik routing (EdgeManifest) |
| `terraform/lxc/environments/pve-tiny/cse-panel-stack/terragrunt.hcl` | Terragrunt entrypoint |
| `terraform/lxc/ansible/playbooks/deploy-cse-panel-stack.yml` | Stack playbook |
