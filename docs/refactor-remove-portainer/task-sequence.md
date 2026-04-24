# Portainer Removal Refactor Task Sequence

Each task is one short-lived branch/session. Keep changes inside the listed
scope unless the task document explicitly expands it.

Follow the same execution discipline as `docs/provisioning-refactor/`:

- read `README.md`, `decisions.md`, and `runbook.md` first
- select exactly one task
- use the matching prompt
- stop when preconditions are not met
- stop when validation reveals a new issue outside the current task boundary

## Status Legend

- `pending` — not started
- `in-progress` — executor session active
- `complete` — task validation passed
- `blocked` — stop condition hit; architecture session must update the package

## A. Contracts And Metadata

| # | Title | Status | Preconditions |
|---|---|---|---|
| 00a | Establish scoped Terragrunt validation baseline | `complete` | None |
| 00b | Split downstream validation scope from the 00a baseline helper | `complete` | 00a |
| 00c | Harden downstream plan validation and null-resource expectations | `complete` | 00a, 00b |
| 00 | Update inventory handoff contract (`inventory.tpl` renders `ansible_playbook`) | `complete` | 00a, 00b, 00c |
| 07 | Classify stacks with explicit `deployment_tier` metadata | `complete` | 00a, 00b, 00c |

## B. Playbook Capability

| # | Title | Status | Preconditions |
|---|---|---|---|
| 01 | Create `direct_stack` Ansible role | `complete` | 00 |
| 02 | Update harbor playbook | `complete` | 01 |
| 03 | Update authentik playbook | `complete` | 01 |
| 04 | Update monitoring playbook | `complete` | 01 |
| 05 | Update proxy playbook | `complete` | 01 |
| 06 | Update netbox playbook | `complete` | 01 |
| 06a | Add Tier 1 service masking to remaining non-agent playbooks | `complete` | None |

## C. Orchestration Boundary

| # | Title | Status | Preconditions |
|---|---|---|---|
| 08 | Remove Terraform LXC playbook runner (`ansible_provision`) | `pending` | 02, 03, 04, 05, 06, 06a |
| 09 | Create `scripts/provision.sh` orchestration path | `pending` | 00, 07, 08 |

## D. Validation And Documentation

| # | Title | Status | Preconditions |
|---|---|---|---|
| 10 | Sync documentation to the runbook-backed method | `pending` | 06a, 07, 08, 09 |

## Dependency Graph

```text
00a (scoped validation baseline)
└── 00b (validation split)
    └── 00c (validation hardening)
        ├── 00 (inventory handoff)
        └── 07 (stack classification)

00 (inventory handoff)
└── 01 (direct_stack)
    ├── 02 (harbor)
    ├── 03 (authentik)
    ├── 04 (monitoring)
    ├── 05 (proxy)
    └── 06 (netbox)

06a (mask remaining Tier 1 playbooks) ─┐
07  (stack classification)             ├── 08 (remove Terraform playbook runner)
                                        └── 09 (provision.sh)  ← also needs 00 and 08

10 (runbook + docs sync) ← needs 06a, 07, 08, 09
```

## Tier 1 Playbook Coverage Reference

The task package must account for all Tier 1 playbooks, not only the five that
currently use Portainer roles directly.

| Playbook | Current Portainer coupling | Required refactor action |
|---|---|---|
| `deploy-harbor-stack.yml` | `portainer_agent`, `portainer_api` | remove Portainer coupling; add service mask |
| `deploy-authentik-stack.yml` | `portainer_agent` | remove Portainer coupling; add service mask |
| `deploy-monitoring-stack.yml` | `portainer_agent` | remove Portainer coupling; add service mask |
| `deploy-proxy-stack.yml` | `portainer_agent` | remove Portainer coupling; add service mask |
| `deploy-netbox-stack.yml` | `portainer_agent`, `portainer_api`, `app_stack` | replace with direct deployment; add service mask |
| `deploy-portainer-stack.yml` | no role coupling | add service mask |
| `deploy-step-ca.yml` | no role coupling | add service mask |
| `deploy-coredns.yml` | no role coupling | add service mask |
| `deploy-apt-cacher-stack.yml` | no role coupling | add service mask |
| `deploy-ci-runner.yml` | no role coupling | add service mask |

## Final Gate

After all tasks are complete, use [runbook.md](runbook.md) for the full
`pve-test` rebuild gate. Do not mark the overall refactor complete on
source-only validation alone.
