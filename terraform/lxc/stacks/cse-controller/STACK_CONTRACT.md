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
| Zone | `infra_seg` (VLAN 40) |
| IP | `192.168.40.70/24` |
| Gateway | `192.168.40.1` |
| VMID | 40070 |

Deployed on `pve-tiny` (production node). `infra_seg` was the operator's
explicit choice over standing up a new dedicated zone or reusing
`mgmt_seg` — neither existing zone's stated purpose (registry/artifact
cache/IPAM vs. identity/PKI/monitoring/logging) is a close match for a
benchmark-orchestration workload, but `infra_seg` at least shares this
stack's real dependency on Harbor. `cse-code-eval`/`cse-autopatch`
(plan §1a decision #3: all three CyberSecEval LXCs on `pve-tiny`) are
expected to join the same zone later at `192.168.40.71`/`.72`.

No cross-zone MikroTik rule exists yet for `cse-controller` → `cse-kali`
(on `pve-test`'s `pentest_seg`, a separate physical VLAN/SDN fabric) —
flagged in the plan (§12) as a genuinely new rule that won't exist by
default, deliberately deferred until the controller has something to
reach the range for (autonomous-offensive benchmark, sequenced last per
`current-state.md`).

## Inputs

None yet. No secrets, no `.env`-sourced template variables — Phase 1 is
infrastructure-only.

## Provides

None yet. No persistent service is exposed — the container makes outbound
calls only (once the Framework side exists). A later phase may add an
API for CI/webhook-triggered runs; update this table then.

## Dependencies

| Stack | Why |
|---|---|
| `infra_seg`'s Harbor (on `pve`, reached cross-node) | Docker image pull (`python:3.10-slim` via Harbor's `dockerhub` proxy-cache) |
| Framework's `llama-server` (not yet built — dedicated Nathanw fork, plan §1a decision #4) | Model inference calls once CyberSecEval code lands (Phase 2+) |

## Persistent State

`/srv/cyberseceval` — a dedicated Proxmox mount point on `pve-tiny`'s
`nvme-lvm` pool (`durable-nvme` profile), separate from the LXC root
filesystem so the root stays small. Intended layout per the plan (§3.1):
`repo/`, `config/`, `datasets/`, `downloads/`, `runs/`, `results/`,
`reports/`, `manifests/`, `logs/` — none of these subdirectories are
created yet; that's the CyberSecEval-checkout step, still pending
(`current-state.md` next-steps #3).

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
- `extra_mount.resize_control_plane: provider`, not `operational` — every
  other stack's extra mount in this repo resolves to a ZFS-backed
  profile, where `main.tf`'s own check block requires `operational`; this
  is the first extra mount backed by `nvme-lvm` (lvm-thin, deliberately
  not ZFS on `pve-tiny` — see `terraform/lxc/storage/pve-tiny.yaml`), and
  that same check block only allows `operational` for a zfs-backed
  backend. `provider` is correct here, not a typo.

## Playbook

`deploy-cse-controller` (roles: `lxc_base`, `docker_base`)

Follows `deploy-cse-kali.yml`'s shape (write compose, `docker compose up
-d`, wait-for-ready, idempotent `apt-get install`) with a much smaller
package list (`curl`, `git`) — no pentest tooling, this is the
orchestrator, not an attacker.

## Implementation Files

| File | Role |
|---|---|
| `terraform/lxc/stacks/cse-controller/stack.yaml` | Terraform-side stack definition |
| `terraform/lxc/stacks/cse-controller/docker-compose.yml` | Controller container definition |
| `terraform/lxc/environments/pve-tiny/cse-controller/terragrunt.hcl` | Terragrunt entrypoint |
| `terraform/lxc/ansible/playbooks/deploy-cse-controller.yml` | Stack playbook |
