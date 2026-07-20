# Framework Desktop: Bare-Metal Ubuntu 26 Migration

Workspace for moving `pve-framework` (the Framework Desktop) off Proxmox
VE/LXC/Terraform onto bare-metal Ubuntu 26.04 LTS, Ansible-managed, no
hypervisor.

Status: **Ubuntu 26.04 migration and core GPU runtimes complete; follow-on
validation in progress.** See [`plan.md`](./plan.md) for the live execution
checkpoint, [`decisions.md`](./decisions.md) for the choices behind it, and
[`benchmarks.md`](./benchmarks.md) for the active autonomous Ollama/llama.cpp/
LM Studio benchmark and morning-processing runbook.

## Why

The prior Proxmox+LXC setup for this node turned out to have a real,
diagnosed reliability problem: `llm-gpu-stack`'s LXC container had an 8GB
memory ceiling that had nothing to do with the model's actual GPU memory
use, and the kernel OOM-killer was silently terminating the LLM service
whenever host-RAM-side pressure crossed it — the thing that looked all of
last night like a "probabilistic Vulkan driver crash" was this, every
single time it was checked. See
[`docs/framework-integration/findings-plan.md`](../framework-integration/findings-plan.md)
for the original investigation and its OOM-diagnosis addendum.

Beyond that specific bug, the operator's actual intent for this hardware
is a single flexible GPU resource — LLM inference or ComfyUI generation,
whichever's needed — not two containers each independently and statically
partitioned. That's the deeper reason for dropping the LXC boundary
rather than just re-tuning its memory limit.

## Contents

- [`plan.md`](./plan.md) — the full phased migration plan: scope, target
  platform, NFS model storage, Ansible role adaptation, Terraform
  removal, carried-forward technical requirements (GTT tuning, the
  Vulkan long-context reliability bug), phases, risks, rollback.
- [`decisions.md`](./decisions.md) — the specific decisions this plan
  rests on, with rationale, in the same style as the (now historical)
  `docs/framework-integration/decisions.md`.
- [`overnight-llm-benchmark.md`](./overnight-llm-benchmark.md) — one-command,
  detached overnight benchmark for chat, story generation, code generation,
  refactoring, and vulnerability review across all three installed runtimes.
- [`benchmarks.md`](./benchmarks.md) — record of the active full run, collected
  evidence, failure triage, performance/resource analysis, and morning cloud-LLM
  judging procedure.

## Related documents

- [`docs/framework-integration/`](../framework-integration/) — the
  Proxmox/LXC-era workspace this supersedes for the *hosting* question.
  `README.md` there marks which documents are now historical
  (`lessons-learned.md`) versus still the live reference for the
  *AI-stack* question (model/server/client selection — unaffected by
  this migration).
- [`docs/framework/`](../framework/) — earlier research (model
  bake-offs, ComfyUI findings, unified-memory/Vulkan hardware notes).
  Hardware/driver findings here are platform-independent and carried
  forward directly into `plan.md`; Proxmox-specific setup notes are
  consolidated into `lessons-learned.md`.
- [`CLAUDE.md`](../../CLAUDE.md) — Production Credential Controls will
  need a follow-up update once `pve-framework` stops being a Proxmox
  node (flagged, not yet resolved — see `plan.md` §6, `decisions.md`
  "Open").
