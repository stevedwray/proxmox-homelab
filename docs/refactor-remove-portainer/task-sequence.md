# Task Sequence — Portainer Removal Refactor

Tasks must be executed in the order shown. Each task's preconditions name the tasks
that must be complete and validated before it can begin.

Tasks marked as independent have no preconditions and can begin immediately. Where
multiple independent tasks exist, prefer sequential execution over parallel to keep
the executor feedback loop clean.

---

## Status legend

- `pending` — not started
- `in-progress` — executor session active
- `complete` — executor session finished and validation passed
- `blocked` — stop condition hit; waiting for architecture session

---

## Tasks

| # | Title | Status | Preconditions |
|---|---|---|---|
| 00 | Update `inventory.tpl` to render `ansible_playbook` | `pending` | None |
| 01 | Create `direct_stack` Ansible role | `pending` | 00 |
| 02 | Update harbor playbook | `pending` | 01 |
| 03 | Update authentik playbook | `pending` | 01 |
| 04 | Update monitoring playbook | `pending` | 01 |
| 05 | Update proxy playbook | `pending` | 01 |
| 06 | Update netbox playbook | `pending` | 01 |
| 07 | Classify all `stack.yaml` files | `pending` | None (independent) |
| 08 | Remove `ansible_provision` from Terraform | `pending` | 02, 03, 04, 05, 06 |
| 09 | Create `scripts/provision.sh` | `pending` | 00, 08 |
| 10 | Update platform documentation | `pending` | 07, 08, 09 |

---

## Dependency graph

```
00 (inventory.tpl)
└── 01 (direct_stack role)
    ├── 02 (harbor)
    ├── 03 (authentik)
    ├── 04 (monitoring)
    ├── 05 (proxy)
    └── 06 (netbox)
        └── (all 02–06 complete)
            └── 08 (remove local-exec)
                └── 09 (provision.sh)  ← also needs 00
                    └── 10 (docs)  ← also needs 07

07 (classify stacks) — independent
```

---

## Playbook compliance reference

The following Tier 1 playbooks require changes. Review this before executing any
playbook task (02–06).

| Playbook | `portainer_agent` | `portainer_api` | `app_stack` | Changes needed |
|---|---|---|---|---|
| `deploy-harbor-stack.yml` | Yes (Play 1) | Yes (Play 2) | No | Remove Play 1 portainer_agent role; remove Play 2 entirely; mask service |
| `deploy-authentik-stack.yml` | Yes (Play 1) | No | No | Remove portainer_agent from Play 1; mask service |
| `deploy-monitoring-stack.yml` | Yes (Play 1) | No | No | Remove portainer_agent from Play 1; mask service |
| `deploy-proxy-stack.yml` | Yes (Play 1) | No | No | Remove portainer_agent from Play 1; mask service |
| `deploy-netbox-stack.yml` | Yes (Play 1) | Yes (Play 3) | Yes (Play 3) | Remove portainer_agent from Play 1; replace Plays 3 with direct_stack; mask service |
| `deploy-portainer-stack.yml` | No | No | No | Add service mask only |
| `deploy-step-ca.yml` | No | No | No | Add service mask only |
| `deploy-coredns.yml` | No | No | No | Add service mask only |
| `deploy-apt-cacher-stack.yml` | No | No | No | Add service mask only |
| `deploy-ci-runner.yml` | No | No | No | Add service mask only |

---

## Full rebuild validation sequence

After all tasks are complete, validate with a full pve-test wipe-and-rebuild:

```bash
# 1. Destroy all LXCs
./with-secrets terragrunt run-all destroy

# 2. Provision all LXC infrastructure
./with-secrets terragrunt run-all apply

# 3. Configure platform tier
./with-secrets ./scripts/provision.sh --tier platform

# 4. Smoke test platform services
curl -sf http://10.57.3.10/api/v2.0/ping          # Harbor
curl -sf http://10.57.1.11/health                  # step-ca
curl -sf http://10.57.2.10/ping                    # Traefik

# 5. Confirm Portainer has zero registered environments after platform provisioning
# Portainer UI → Environments: should show only the local Docker socket endpoint,
# no agent-based endpoints.

# 6. Verify provision.sh is idempotent
./with-secrets ./scripts/provision.sh --tier platform
# Expected: no changed tasks on second run
```
