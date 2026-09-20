# cse-code-eval — Stack Contract

## Purpose

Execution environment for CyberSecEval components that compile and run
model-generated code directly — primarily the Vulnerability Exploitation
benchmark (`canary-exploit`, plan §3.2/§7). Confirmed by reading the
actual upstream source, not assumed: `canary_exploit/verify_response.py`
calls `compile_and_run(code, answer)` as a plain local subprocess — the
model's answer is fed as input to compiled C/C++ challenge code. There is
no remote-execution abstraction in the tool itself, so isolating the
actual compile-and-run step means running the whole
`benchmark.run --benchmark=canary-exploit` invocation on this LXC, not
dispatching a sub-step from `cse-controller`.

Separated from `cse-controller` for **security, not performance** (the
plan's own words) — this LXC directly executes untrusted, potentially
exploit-grade code.

## Network

| Field   | Value |
|---|---|
| Zone | `cse_seg` (VLAN 100) |
| IP | `192.168.100.71/24` |
| Gateway | `192.168.100.1` |
| VMID | 100071 |

**NOT `infra_seg`** — that was the original build's shortcut ("get
moving fast"), reconsidered before this stack was ever deployed (plan
§1b, 2026-09-19). `infra_seg` has no default-deny egress at all
(confirmed live), so it can't actually provide what plan §3.2 requires
here ("must not have access to Proxmox management interfaces, NAS
storage, ordinary LAN, Framework management interfaces"). `cse_seg` is a
genuinely new, dedicated, default-deny zone built specifically for this
and `cse-controller` — see plan §1b for the full MikroTik/Proxmox-SDN
design (VLAN, gateway, firewall rules). **This stack must not be
deployed until `cse_seg` actually exists.**

Same-subnet traffic to `cse-controller` (`192.168.100.70`, same
`cse_seg`) needs no explicit rule — intra-VLAN traffic doesn't transit
the MikroTik router at all.

## Inputs

None. No secrets, no `.env`-sourced template variables.

## Provides

None. No persistent service — an on-demand execution sandbox, invoked
by running `benchmark.run --benchmark=canary-exploit` directly on it
(not yet automated into a script, unlike `cse-controller`'s
`run-autonomous-uplift.sh` — no live canary-exploit run has happened
yet).

## Dependencies

| Stack | Why |
|---|---|
| `infra_seg`'s Harbor (on `pve`, reached cross-node) | Docker image pull (`python:3.10-slim`) |
| Framework's `llama-server` (live, port 8080) | Model inference calls during a `canary-exploit` run — the one narrow LAN allow this box has |

## Persistent State

`/srv/cyberseceval` on `pve-tiny`'s `nvme-lvm` pool (`durable-nvme`
profile, 50G) — same layout convention as `cse-controller`:
`repo/PurpleLlama` (cloned, pinned to the same commit as
`cse-controller`, same `upstream`/`cse-lab` branch convention) and
`.venv` (Python 3.10, same requirements). **`backup_policy: exclude`**
(unlike `cse-controller`'s `include`) — this LXC's data is disposable
execution scratch space by design, not worth backing up.

## What May Depend on This Stack

Nothing yet. Once a `canary-exploit` run-orchestration script exists
(mirroring `cse-controller`'s `run-autonomous-uplift.sh` pattern), it
would live here, invoked from `cse-controller` or manually.

## What Must Not Be Edited Casually

- `cse_seg`'s default-deny MikroTik rules (plan §1b) are this stack's
  entire isolation boundary. Don't move this stack to a different zone
  (especially not back to `infra_seg`, which is open) without
  re-establishing equivalent isolation first.
- The build toolchain in `deploy-cse-code-eval.yml`'s
  `cse_code_eval_packages` covers what plan §3.2 lists (gcc/g++/make/
  cmake/gdb/binutils/sqlite/node) — extend it there if a benchmark needs
  a runtime not yet installed, not via a manual `docker exec apt-get
  install` that won't survive a redeploy.
- The PurpleLlama clone/branch-setup tasks are gated on `.git` not
  already existing (one-time bootstrap) — same reasoning as
  `cse-controller`'s identical gate. Don't remove it.

## Playbook

`deploy-cse-code-eval` (roles: `lxc_base`, `docker_base`)

Mirrors `deploy-cse-controller.yml`'s PurpleLlama/venv setup exactly
(same pin, same one-time-bootstrap gating), with a build-toolchain
package list instead of CyberSecEval-orchestration tooling, and no
Harbor-project or autonomous-uplift-specific tasks (those belong to
`cse-controller`/`cse-kali` respectively).

## Implementation Files

| File | Role |
|---|---|
| `terraform/lxc/stacks/cse-code-eval/stack.yaml` | Terraform-side stack definition |
| `terraform/lxc/stacks/cse-code-eval/docker-compose.yml` | Code-eval container definition |
| `terraform/lxc/environments/pve-tiny/cse-code-eval/terragrunt.hcl` | Terragrunt entrypoint |
| `terraform/lxc/ansible/playbooks/deploy-cse-code-eval.yml` | Stack playbook |
