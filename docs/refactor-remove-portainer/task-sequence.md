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
| 08 | Remove Terraform LXC playbook runner (`ansible_provision`) | `complete` | 02, 03, 04, 05, 06, 06a |
| 08b | Retire legacy stack_cleanup Ansible path before inventory-handoff validation | `complete` | 08 |
| 08a | Generate real inventory handoff artifact for Task 09 preflight | `complete` | 00, 07, 08, 08b |
| 09 | Create `scripts/provision.sh` orchestration path | `complete` | 08a |

## D. Validation And Documentation

| # | Title | Status | Preconditions |
|---|---|---|---|
| 10 | Sync documentation to the runbook-backed method | `complete` | 06a, 07, 08, 09 |

## E. Rebuild Unblockers

| # | Title | Status | Preconditions |
|---|---|---|---|
| 11 | Harden SDN VNet destroy path for rebuild-gate no-op handling | `complete` | 10 |
| 12 | Document stack-only, non-interactive rebuild-gate contract | `complete` | 11 |
| 13 | Fix Terragrunt flag forwarding for rebuild-gate destroy/apply | `complete` | 12 |
| 14 | Correct invalid pve-test storage fallback defaults | `complete` | 13 |
| 15 | Triage Proxmox storage lock contention on `infrastructure-containers` | `complete` | 13 |

## F. Integration Closeout

| # | Title | Status | Preconditions |
|---|---|---|---|
| 15a | Integrate Task 15 package status into `dev/pve-test` | `complete` | 15 |

## G. Host Cleanup

| # | Title | Status | Preconditions |
|---|---|---|---|
| 16 | Clear or confirm absence of stale Proxmox storage lock | `complete` | 15a |

## H. Rebuild Gate

| # | Title | Status | Preconditions |
|---|---|---|---|
| 17 | Retry the full `pve-test` rebuild gate after stale-lock cleanup | `blocked` | 16 |

## I. Rebuild Triage

| # | Title | Status | Preconditions |
|---|---|---|---|
| 18 | Triage Proxmox container shutdown timeout during rebuild-gate destroy | `complete` | 17 |

## J. Destroy Unblocker

| # | Title | Status | Preconditions |
|---|---|---|---|
| 19 | Add a stop-first rebuild-gate destroy helper | `complete` | 18 |

## K. Integration Closeout

| # | Title | Status | Preconditions |
|---|---|---|---|
| 19a | Integrate Task 19 destroy-helper commit into `dev/pve-test` | `complete` | 19 |
| 19b | Integrate Task 19a package status into `dev/pve-test` | `complete` | 19a |

## L. Historical Recovery Evidence

These tasks and reports remain part of the operational record, but they do not
define the next live execution mode. They explain why the package moved to a
cleanup-first recovery strategy.

| # | Title | Status | Preconditions |
|---|---|---|---|
| 20 | Retry rebuild gate with stop-first helper | `blocked` | 19b |
| 20a | Retry rebuild gate with corrected evidence handling | `blocked` | 19b |
| 21 | Fix `pct stop` compatibility in destroy helper | `blocked` | 20a |
| 22 | Triage Proxmox LXC config lock timeout during stop-first destroy | `complete` | 21 |
| 23 | Clear hung Proxmox stop task for VMID 150 | `complete` | 22 |
| 24 | Reconcile `pve-test` post-reboot storage health baseline | `complete` | 22 |

## M. Cleanup-First Reset

| # | Title | Status | Preconditions |
|---|---|---|---|
| 29 | Strip down disposable validation containers on `pve-test` | `blocked` | 24 |
| 29a | Manually remove orphaned disposable validation containers on `pve-test` | `complete` | 29 |
| 30 | Classify and prune disposable SDN objects after strip-down | `complete` | 29a |
| 30a | Validate retained container creation with `ci-runner-01` | `complete` | 30 |
| 30b | Validate `ci-runner-01` functional configuration | `blocked` | 30a |
| 30c | Restore repeatable `ci-runner-01` apt-cacher reachability in code | `blocked` | 30b |
| 30d | Reconcile active MikroTik baseline and build-seg carriage assumptions | `complete` | 30c |
| 30e | Reconcile `build_seg` VLAN/data-plane path between Proxmox and the active MikroTik | `blocked` | 30d |
| 30f | Reconcile active MikroTik credentials and restore VLAN 10 gateway carriage | `blocked` | 30e |
| 30g | Validate the external build trunk path between Proxmox and the active MikroTik | `pending` | 30f |
| 31 | Add a minimal build-path validation harness | `pending` | 30g |
| 32 | Run the minimal build-path harness on `pve-test` | `pending` | 30, 31 |
| 33 | Validate SDN VNet idempotency with the minimal build-path harness | `pending` | 32 |

## N. Basic SDN Reset Track

This track intentionally narrows scope to a single SDN path and one baseline
container so that deployment and validation can be proven with less moving
parts.

| # | Title | Status | Preconditions |
|---|---|---|---|
| 34 | Add a basic SDN smoke harness with simple container scope | `pending` | 30g |
| 35 | Run the basic SDN smoke harness on `pve-test` | `pending` | 34 |
| 36 | Re-run basic SDN smoke idempotency and teardown | `pending` | 35 |

Execution note:

- `docs/refactor-remove-portainer/reports/29-status-clarification-report.md`
  reconciles the stale first-attempt Task 29 report with the later rerun
  artifact.
- The current authoritative Task 29 report on disk records the corrected rerun
  and shows that the disposable validation CTs are orphaned: they still exist
  on `pve-test`, but the corresponding Terraform state is empty.
- Task 29a completed manual orphaned CT cleanup for VMIDs `130` through `140`.
  It does not authorize SDN object removal by itself.
- Task 30 completed as a validated no-op: no live SDN object was proven
  disposable or unused.
- Task 30a completed a retained-stack container creation test for
  `ci-runner-01`.
- Task 30b is authoritative blocked evidence: the supported
  `./scripts/provision.sh --stack ci-runner-01` path failed because VMID `141`
  could not reach apt-cacher at `10.57.3.11:3142` from `build_seg`.
- Task 30c proved that the scoped firewall-rule fix alone was insufficient and
  narrowed the remaining failure to the lower network plane.
- Task 30d completed runtime-baseline reconciliation for the active MikroTik:
  authoritative management IP `192.168.1.251`, live input contract via
  `.env/.env.<env>` plus `terraform/secrets.enc.yaml`, and updated template
  defaults/comments.
- Task 30e is blocked with authoritative evidence: Proxmox emits correct VLAN
  10 tagged ARP for `10.57.0.1`, but no reply returns from the active
  MikroTik side.
- Task 30f is also blocked with newer evidence: repo-managed auth and the
  minimum bridge/VLAN trunk model were applied on the active router, but the
  router still learned no `10.57.0.x` ARP/source state from `pve-test`.
- Task 30g is the required next unblocker before any minimal-harness work
  resumes. It validates the external trunk/carriage assumption outside the
  scoped router automation change.
- Do not start Tasks 31 or 32 unless the Task 30g report on disk explicitly
  shows `Status: complete`.
- Tasks 34-36 provide a simpler, lower-blast-radius SDN execution path:
  `test-lxc` + `net-build-01`, one gateway probe, and explicit teardown.

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
                                        ├── 08b (retire legacy stack_cleanup path)
                                        └── 08a (real inventory handoff artifact) ─── 09 (provision.sh)

00 (inventory handoff contract) ────────────────────────────────────────────────┘

10 (runbook + docs sync) ─── 11 (SDN destroy no-op handling) ─── 12 (stack-only rebuild-gate contract) ─── 13 (Terragrunt flag forwarding fix)
                                                                                                                ├── 14 (storage fallback correction)
                                                                                                                └── 15 (storage lock triage)
                                                                                                                     └── 15a (Task 15 package status integration)
                                                                                                                         └── 16 (stale lock cleanup or no-op confirmation)
                                                                                                                             └── 17 (fresh rebuild-gate retry)
                                                                                                                                 └── 18 (shutdown-timeout triage)
                                                                                                                                     └── 19 (stop-first destroy helper)
                                                                                                                                         └── 19a (destroy-helper integration)
                                                                                                                                             └── 19b (Task 19a package status integration)
                                                                                                                                                 ├── 20 / 20a / 21 (historical blocked rebuild retries)
                                                                                                                                                 └── 22 (lock-timeout triage)
                                                                                                                                                     ├── 23 (hung stop-task cleanup/no-op)
                                                                                                                                                     └── 24 (post-reboot recovery baseline)
                                                                                                                                                         └── 29 (strip disposable validation containers)
                                                                                                                                                             └── 29a (manual orphaned CT cleanup)
                                                                                                                                                                 ├── 30 (classify/prune disposable SDN state)
                                                                                                                                                                 │   └── 30a (ci-runner-01 retained creation test)
                                                                                                                                                                 │       └── 30b (ci-runner-01 functional validation; blocked)
                                                                                                                                                                 │           └── 30c (fix apt-cacher reachability + revalidate ci-runner-01; blocked)
                                                                                                                                                                 │               └── 30d (reconcile active MikroTik runtime baseline)
                                                                                                                                                                 │                   └── 30e (reconcile build_seg VLAN/data-plane path; blocked)
                                                                                                                                                                 │                       └── 30f (restore active MikroTik creds + VLAN10 gateway carriage; blocked)
                                                                                                                                                                 │                           └── 30g (validate external Proxmox↔MikroTik trunk path)
                                                                                                                                                                 │                               └── 31 (minimal build-path harness)
                                                                                                                                                                 │                                   └── 32 (run minimal build-path harness)
                                                                                                                                                                 │                                       └── 33 (SDN idempotency validation on minimal harness)
                                                                                                                                                                 └── 34 (basic SDN smoke harness code)
                                                                                                                                                                   └── 35 (run basic SDN smoke harness)
                                                                                                                                                                     └── 36 (basic SDN smoke idempotency + teardown)
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

After all tasks are complete, including Tasks 14, 15, 15a, 16, 17, 18, 19, 19a, 19b, 29, 29a, 30, 30a, 30b, 30c, 30d, 30e, 30f, 30g, 31, 32, 33, 34, 35, 36, and any rebuild-unblocker tasks opened by a
rebuild-gate stop condition, use [runbook.md](runbook.md) for the full
`pve-test` rebuild gate. Do not mark the overall refactor complete on
source-only validation alone.
