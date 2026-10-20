# cse-controller — Stack Contract

## Purpose

Primary orchestration service for the CyberSecEval implementation (Meta
CyberSecEval 4) — see
`docs/cyberseceval-implementation/plan/cyberseceval-implementation-plan.md`
§3.1. Does not perform LLM inference itself: it drives benchmark runs
(Python execution, dataset processing, JSON/result generation,
Semgrep/CodeShield-style analysis), calling out to the Framework host's
`llama-server` for anything model-related. Phase 1 (this deploy) only
stands up the LXC and its container shell — no CyberSecEval code is
cloned yet, and no inference call has been wired up (the Framework side,
a dedicated Nathanw Strix-Halo `llama.cpp` fork build, doesn't exist yet
either — plan §1a open decision #4).

## Network

| Field   | Value |
|---|---|
| Zone | `cse_seg` (VLAN 100) |
| IP | `192.168.100.70/24` |
| Gateway | `192.168.100.1` |
| VMID | 40070 (kept unchanged across the migration below — see plan §1b) |

**Migrated from `infra_seg` (2026-09-19, plan §1b)** — the original build
put this on `infra_seg` to move fast, but that zone has no default-deny
egress at all, so it never actually isolated anything. `cse_seg` is a
genuinely new, dedicated, default-deny zone (VLAN 100,
`192.168.100.0/24`) shared with `cse-code-eval`. Confirmed live: the
container's network update was in-place (same VMID, no destroy/
recreate), durable mount/repo/branch all survived untouched.

`cse_seg`'s MikroTik rules (narrow allows + default-deny, see
`ansible/00-initial-setup/mikrotik-firewall-cse-seg.yml`) are this
stack's actual network boundary. Three real bugs were found and fixed
getting them right — worth knowing before touching that file:
1. `input`-chain rules (DNS/ping to the router) must be inserted before
   the **input** chain's own catch-all drop, not the forward chain's —
   using the wrong anchor produced rules that "existed" but were never
   evaluated, breaking DNS resolution silently.
2. Harbor is reached via `192.168.30.10` (Traefik/`edge_seg`) — the
   hostname every stack's compose file actually uses
   (`harbor.lab.gibbsgreatly.xyz`) does **not** resolve to an `infra_seg`
   address.
3. `docker exec ... tee` needs `-i`; without it, stdin never reaches the
   container and the write silently produces an empty file (same root
   cause hit earlier in `cse-kali`'s own SSH setup).

Cross-zone reachability to `cse-kali`'s agent (`pentest_seg` on
`pve-test`, a separate physical fabric) is a real allow rule now
(`cse-controller`'s specific IP → `192.168.70.212:22`), verified live —
this is the first genuinely cross-zone rule this stack needed, since
`infra_seg` never required one (nothing was restricted).

The `pentest_tasks.py` Celery worker and `viewer_proxy.py` reverse proxy
live in `cse-controller/pentest-worker-config/`. The worker needs a
dedicated SSH identity to
`pentest-runner`/`pentest-fixture` (never a fleet-wide key) — same zone as
`pentest-runner`, so that leg needs no new firewall rule, only the
identity. `viewer_proxy.py` binds port 18810 for the panel's existing
narrow `mgmt_seg` → `cse_seg` rule. It is stateless: control and viewer
requests go to the runner's supervisor at `192.168.100.72:18820` on the
same subnet. Only the worker retains SSH; the proxy does not hold a tunnel.

**Design only as of 2026-10-20, not yet deployed** —
`docs/autonomous-pentesting-lab/research-snapshot-plan.md` adds a second,
separate Celery worker, `pentest-research-worker`, with its own dedicated
SSH identity (`GVM_RESEARCH_GATEWAY_SSH_PRIVATE_KEY`) to
`greenbone-stack`'s research gateway — a genuinely new cross-zone path
(`cse_seg → pentest_seg tcp/22`, same `mikrotik-firewall-cse-seg.yml` file
as the existing `cse-kali` rule above). Its own `/srv/pentest-research`
mount is deliberately kept separate from `pentest_worker_dir`
(`/srv/pentest-worker`), since that directory is mounted whole into
`pentest-viewer-proxy` and the new key must never be reachable there.
`pentest-worker` and `pentest-viewer-proxy` each get a new read-only mount
scoped to just `/srv/pentest-research/metasploitable3-linux` (the snapshot data, not the key).
A third shared mount, `/srv/pentest-target-guard`, is mounted at the
identical host path into both `pentest-worker` and
`pentest-research-worker` — `research_target_guard.py`'s `fcntl` locking
only provides real cross-container mutual exclusion when both containers
see the same underlying inode, not two separate bind mounts.

## Inputs

None yet. No secrets, no `.env`-sourced template variables — Phase 1 is
infrastructure-only.

## Provides

The pentest viewer proxy exposes `18810/tcp` to panel-web through the
existing narrow firewall rule. It does not expose raw Strix child ports.

## Dependencies

| Stack | Why |
|---|---|
| Harbor, via Traefik/`edge_seg` (on `pve`, reached cross-node) | Docker image pull (`python:3.10-slim` via Harbor's `dockerhub` proxy-cache) |
| Framework's `llama-server` (live — `qwen38-flash-next-q4`, port 8080, see `current-state.md`) | Model inference calls once CyberSecEval code lands (Phase 2+) |
| `github.com/meta-llama/PurpleLlama` (direct outbound HTTPS, not proxied through Harbor) | One-time repo clone (plan §6) |
| `greenbone-stack` (design only as of 2026-10-20) | `pentest-research-worker` → its research gateway, `cse_seg → pentest_seg tcp/22` |
| `cve-mcp.${LAB_DOMAIN}` (`mcp-utility-stack`, design only) | CVE triage via `triage_cve` — reachability from a real `pentest-research-worker` container is an explicit open validation gate, not assumed |

## Persistent State

`/srv/cyberseceval` — a dedicated Proxmox mount point on `pve-tiny`'s
`nvme-lvm` pool (`durable-nvme` profile), separate from the LXC root
filesystem so the root stays small.

- `repo/PurpleLlama/` — clone of `meta-llama/PurpleLlama`, pinned to a
  known commit (plan §6: never track `main` implicitly for benchmark
  runs). Remote renamed `origin` → `upstream`; a local `cse-lab` branch
  carries only documented compatibility changes on top of the pin.
  **One-time bootstrap only** — `deploy-cse-controller`'s clone/branch
  tasks are gated on the repo not already existing, specifically so a
  routine redeploy never resets or re-checks-out this repo once it's
  been hand-maintained.
- `.venv/` — Python 3.10 venv (matches the container's `python:3.10-slim`
  base), `CybersecurityBenchmarks/requirements.txt` installed into it.
  Rerunning the playbook reinstalls requirements (idempotent) but never
  recreates the venv if it already exists.
- `config/`, `datasets/`, `downloads/`, `runs/`, `results/`, `reports/`,
  `manifests/`, `logs/` — remaining layout per plan §3.1; only
  `manifests/` (Phase 1's acceptance record) exists so far.

## What May Depend on This Stack

Every later CyberSecEval phase (Phase 2 onward) — this is the box
everything else in the compute track runs from.

## What Must Not Be Edited Casually

- The container image is a stock `python:3.10-slim`, not a custom build —
  keep it that way until there's a concrete reason (a pinned CyberSecEval
  Python-version requirement) to change it. CyberSecEval's own venv/deps
  belong inside `/srv/cyberseceval` (the durable mount), not baked into
  the image, so a container recreate doesn't lose them.
- `extra_mount_profile: durable-nvme` — do not switch this to
  `durable-default` (which resolves to `local-lvm`, the boot SSD); the
  whole point of this mount is to live on the 2TB NVMe pool, not compete
  with the LXC root filesystem for space.
- The PurpleLlama clone/branch-setup tasks in `deploy-cse-controller.yml`
  are gated on `.git` not already existing — this is deliberate
  (one-time bootstrap, see Persistent State above). Do not remove that
  gate; it's what stops a routine redeploy from resetting the hand-
  maintained `cse-lab` branch or re-checking-out the pinned commit over
  any local work in progress.
- `extra_mount.resize_control_plane: provider`, not `operational` — every
  other stack's extra mount in this repo resolves to a ZFS-backed
  profile, where `main.tf`'s own check block requires `operational`; this
  is the first extra mount backed by `nvme-lvm` (lvm-thin, deliberately
  not ZFS on `pve-tiny` — see `terraform/lxc/storage/pve-tiny.yaml`), and
  that same check block only allows `operational` for a zfs-backed
  backend. `provider` is correct here, not a typo.
- `/srv/pentest-research` must stay a separate mount from
  `/srv/pentest-worker` (design only as of 2026-10-20) — the latter is
  bind-mounted whole into `pentest-viewer-proxy`, so putting the research
  gateway's private key anywhere under it would make the key reachable
  from a container that has no legitimate need for it.
- `/srv/pentest-target-guard` must be mounted at the *identical* host
  path in both `pentest-worker` and `pentest-research-worker` — a
  different path on either side defeats `research_target_guard.py`'s
  `fcntl`-based mutual exclusion entirely (two different host directories
  are two different inodes, so the lock would never actually conflict).

## Playbook

`deploy-cse-controller` (roles: `lxc_base`, `docker_base`)

Follows `deploy-cse-kali.yml`'s shape (write compose, `docker compose up
-d`, wait-for-ready, idempotent `apt-get install`) with no pentest
tooling — this is the orchestrator, not an attacker. Package list
(`curl`, `git`, `git-lfs`, `build-essential`, `poppler-utils`, `jq`,
`python3-venv`) matches plan §8's "Core Controller Installation" list
in full — confirmed live during Phase 4 (CyberSOCEval) work, 2026-09-19.

## Implementation Files

| File | Role |
|---|---|
| `terraform/lxc/stacks/cse-controller/stack.yaml` | Terraform-side stack definition |
| `terraform/lxc/stacks/cse-controller/docker-compose.yml` | Controller container definition |
| `terraform/lxc/environments/pve-tiny/cse-controller/terragrunt.hcl` | Terragrunt entrypoint |
| `terraform/lxc/ansible/playbooks/deploy-cse-controller.yml` | Stack playbook |
