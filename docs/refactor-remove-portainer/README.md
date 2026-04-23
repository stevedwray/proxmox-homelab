# Portainer Removal Refactor

This directory is the source of truth for the platform provisioning refactor that removes
Portainer from the Tier 1 (platform) deployment path and separates Terraform provisioning
from Ansible configuration.

The architecture background documents (`01-revised-architecture.md`,
`02-terraform-ansible-separation.md`) remain valid reference material. The operational
package in this directory supersedes `03-refactor-plan.md` for all execution purposes.

---

## Objective

Remove Portainer from every platform stack deployment path. Platform services (Harbor,
Authentik, Traefik, monitoring, NetBox, step-ca, CoreDNS, apt-cacher-ng, CI runner,
Portainer server itself) are deployed directly by Ansible using Docker Compose on-host.
Portainer is retained as a management UI for application stacks only.

Separate Terraform and Ansible into two explicit sequential phases: Terraform provisions
infrastructure, Ansible configures it. Neither phase invokes the other.

---

## Governing contract

Read [decisions.md](decisions.md) before opening any task or prompt. Every decision in
that file is binding for all executor sessions. Stop and report to the architecture
session if any task conflicts with a decision.

---

## Scope

- `pve-test` only. Production `pve` targeting is out of scope until pve-test is proven.
- Each task is small enough for one short-lived branch and one executor session.
- Do not combine tasks unless explicitly instructed.

---

## Execution model

This refactor uses two AI session types:

**Architecture session** (high-context, sophisticated model — this session):
- Maintains this directory as the source of truth.
- Reads executor session output and updates the next prompt accordingly.
- Does not execute code changes.

**Executor session** (lower-cost implementation model):
- Receives exactly one prompt per session.
- Reads the named task document and the decisions file before doing anything.
- Reports back: what was done, validation output, any stop conditions hit, any
  unexpected findings.
- Does not skip validation steps or combine tasks.

---

## How to run a task

1. Open the architecture session.
2. Check [task-sequence.md](task-sequence.md) for the next pending task.
3. Confirm its preconditions are met (prior tasks complete and validated).
4. Open the matching prompt from [prompts/index.yaml](prompts/index.yaml).
5. Paste the prompt into a new executor session.
6. Read the executor session output.
7. Update task status in [task-sequence.md](task-sequence.md).
8. If the executor hit a stop condition or unexpected finding, update the next prompt
   before proceeding.

---

## Files

- [decisions.md](decisions.md) — binding design decisions; read first
- [task-sequence.md](task-sequence.md) — full task list with dependency graph and status
- [tasks/](tasks/) — detailed task documents (one per executor session)
- [prompts/](prompts/) — executor prompts (one per task, matching tasks/ one-to-one)
- [prompts/index.yaml](prompts/index.yaml) — ordered prompt registry
