# Teardown/Deploy Operations Plan

This document is the working decomposition for the `pve-test` teardown/deploy
rehearsal. It turns the high-level task sequence into atomic components that can
be executed one by one with clear handoffs.

This plan does not approve destructive work. Destructive execution still
requires the gates in [variables.md](variables.md), backup evidence, a clean
working tree, a known commit, and explicit operator approval.

## Operating Model

- One source-changing planning package should run in one short-lived branch from
  `baseline/teardown-validated`.
- Live execution packages normally do not modify tracked source files. They write
  runtime evidence under ignored paths such as `docs/teardown-test/artifacts/evidence/`.
- Every apply, destroy, or deployment validation command must first prove the
  target guard returns exactly `pve-test`:

  ```bash
  ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
  ```

- For direct Ansible validation against inline inventories, always pass
  `-u root`.
 - Opt-in disposable test stacks (for example `docker-socket-proxy-test`) can be included in a run by creating a temporary inventory and running the harness with the `TEARDOWN_INVENTORY_FILE` environment variable; the default inventory remains unchanged.
- Generated edge artifacts under `terraform/lxc/.generated/` are runtime output,
  not source. Regenerate them immediately before publish.
- Reconciler dry-run and apply commands should use the direct Authentik URL
  `http://${lab_ip_authentik}:9000` during rehearsal flows.
- Direct Portainer validation should use the API on port `9000`.
- Certificate drift in `certs/homelab-root.crt` after step-ca rebuild is an
  explicit closeout decision, not background noise.
- If any atomic component exposes a source bug, stop the rehearsal. Fix that bug
  in a separate short-lived branch, merge it back to `baseline/teardown-validated`, then restart
  from the most recent non-destructive preflight.

## Candidate Stack Order

Task 02 must verify this candidate against current `stack.yaml` metadata before
execution. The order below reflects the current bootstrap model and keeps
Traefik independent of Authentik during Stage 3a.

Authoritative source: [inventory.md](inventory.md). Reproduced here for context.

| Order | Unit | VMID | Stage | Reason |
|---:|---|---:|---|---|
| 1 | `apt-cacher-stack` | 142 | Stage 1/2 foundation | Independent apt utility; needed by later apt-backed stacks. |
| 2 | `ci-runner-01` | 141 | Stage 1/2 foundation | Depends on apt-cacher. |
| 3 | `dns-stack` | 151 | Stage 3a edge foundation | Seed authority for `lab.gibbsgreatly.xyz`. |
| 4 | `step-ca-stack` | 152 | Stage 3a edge foundation | Internal CA; must precede proxy-stack. |
| 5 | `proxy-stack` | 153 | Stage 3a edge foundation | Traefik runtime; requires step-ca root CA; must not depend on Authentik. |
| 6 | `authentik-stack` | 150 | Stage 3a edge foundation | Direct first boot and API-token bootstrap. |
| 7 | edge reconciliation activation | n/a | Stage 3a handoff | Publish generated DNS, Traefik, and Authentik state. |
| 8 | `harbor-stack` | 121 | Stage 3b platform | Depends on dns, step-ca, proxy, and authentik. |
| 9 | `monitoring-stack` | 154 | Stage 3b platform | Depends on Harbor, apt-cacher, Authentik, proxy, and step-ca. |
| 10 | `netbox-stack` | 143 | Stage 3b platform | Depends on Harbor. |
| 11 | `portainer-stack` | 120 | Stage 3b platform | Management service; no blocking stack dependency. |

Destroy order is the reverse stack order, excluding the non-Terraform edge
activation unit:

```text
portainer-stack -> netbox-stack -> monitoring-stack -> harbor-stack ->
authentik-stack -> step-ca-stack -> proxy-stack -> dns-stack ->
ci-runner-01 -> apt-cacher-stack
```

## Atomic Planning Components

| ID | Component | Preconditions | Operations | Postconditions | Files modified or added |
|---|---|---|---|---|---|
| OP-00 | Source baseline and branch setup | Current branch is clean. | Merge the current completed branch into `baseline/teardown-validated`; cut the next short-lived branch from `baseline/teardown-validated`; record branch and base commit. | New work starts from the integration branch. | None unless recording the base commit in `variables.md`. |
| OP-01 | Resolve execution variables | OP-00 complete. | Fill operator, window, target, branch, commit, scope, resolver, and approval fields. | `variables.md` has no unresolved destructive-gate values. | `docs/teardown-test/variables.md`; `docs/teardown-test/decisions.md` only if a governing decision changes. |
| OP-02 | Freeze inventory and dependency order | OP-01 complete. | Extract selected stack VMIDs, IPs, zones, dependencies, and playbooks; verify the candidate order; write the approved deploy and destroy order. | Every later operation has a single approved stack order. | Add `docs/teardown-test/inventory.md`; update `docs/teardown-test/variables.md`; update `docs/teardown-test/runbook.md` only for command/order corrections. |
| OP-03 | Approve persistent-data policy | OP-02 complete. | Record backup source, restore confidence, or explicit data-loss approval for every persistent service. | Destruction is blocked unless each selected persistent service has an approved policy. | Add `docs/teardown-test/backup-plan.md`; update `docs/teardown-test/variables.md`. |
| OP-04 | Harden runbook commands | OP-03 complete. | Review target guards, Ansible users, generated-artifact refresh, publish commands, stop conditions, and rollback commands. | The runbook can be followed without inventing commands during the live window. | `docs/teardown-test/runbook.md`; task docs only when their scope or gate changes. |
 | OP-05 | Non-destructive source and edge preflight | OP-04 complete. | Run source validation, edge manifest validation, unit tests, generated artifact refresh, and edge dry-run. | Source and generated outputs are ready for an approval packet. | No tracked source files; ignored generated output under `terraform/lxc/.generated/`; evidence under `docs/teardown-test/artifacts/evidence/<stamp>/`. |
| OP-06 | Destructive approval packet | OP-05 complete. | Present clean tree, branch, commit, target guard, stack list, backup evidence, rollback deadline, and stop conditions. | Operator either approves the destructive window or the plan stops. | No tracked source files; evidence packet under `docs/teardown-test/artifacts/evidence/<stamp>/approval/`. |

## Atomic Destroy Components

Each destroy component starts by re-running the target guard. Each component
destroys exactly one approved stack and verifies the VMID is absent before the
next component begins. In live execution the harness delegates stack destroy to
`scripts/rebuild-gate-destroy.sh --execute --stack <name>` so stopped CTs and
missing local state ownership can be repaired before `terragrunt destroy`.

| ID | Component | Preconditions | Operation | Postconditions | Files modified or added |
|---|---|---|---|---|---|
| OP-07 | Destroy `netbox-stack` | OP-06 approved; stack is in scope. | Run the destroy helper for `netbox-stack`, then verify VMID `143` absent. | NetBox is absent; no other VMID affected. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/destroy-netbox-stack.log`. |
| OP-08 | Destroy `monitoring-stack` | OP-07 complete. | Run the destroy helper for `monitoring-stack`, then verify VMID `154` absent. | Monitoring is absent; no other VMID affected. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/destroy-monitoring-stack.log`. |
| OP-09 | Destroy `authentik-stack` | OP-08 complete. | Run the destroy helper for `authentik-stack`, then verify VMID `150` absent. | Authentik is absent after dependent services are gone. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/destroy-authentik-stack.log`. |
| OP-10 | Destroy `step-ca-stack` | OP-09 complete. | Run the destroy helper for `step-ca-stack`, then verify VMID `152` absent. | step-ca is absent. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/destroy-step-ca-stack.log`. |
| OP-11 | Destroy `proxy-stack` | OP-10 complete. | Run the destroy helper for `proxy-stack`, then verify VMID `153` absent. | Traefik is absent. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/destroy-proxy-stack.log`. |
| OP-12 | Destroy `dns-stack` | OP-11 complete. | Run the destroy helper for `dns-stack`, then verify VMID `151` absent. | CoreDNS is absent. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/destroy-dns-stack.log`. |
| OP-13 | Destroy `ci-runner-01` | OP-12 complete. | Run the destroy helper for `ci-runner-01`, then verify VMID `141` absent. | CI runner is absent. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/destroy-ci-runner-01.log`. |
| OP-14 | Destroy `harbor-stack` | OP-13 complete. | Run the destroy helper for `harbor-stack`, then verify VMID `121` absent. | Harbor is absent after consumers are gone. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/destroy-harbor-stack.log`. |
| OP-15 | Destroy `apt-cacher-stack` | OP-14 complete. | Run the destroy helper for `apt-cacher-stack`, then verify VMID `142` absent. | apt-cacher is absent. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/destroy-apt-cacher-stack.log`. |
| OP-16 | Destroy `portainer-stack` | OP-15 complete. | Run the destroy helper for `portainer-stack`, then verify VMID `120` absent. | Approved platform scope is absent. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/destroy-portainer-stack.log`. |

## Atomic Rebuild Components

Each rebuild component starts by re-running the target guard, applies exactly one
stack or one non-Terraform reconciliation unit, then validates the service before
the next component starts.

| ID | Component | Preconditions | Operation | Postconditions | Files modified or added |
|---|---|---|---|---|---|
| OP-17 | Deploy `apt-cacher-stack` | OP-16 complete. | Apply `apt-cacher-stack`; validate apt-cacher service on port 3142. | apt-cacher is running at VMID `142`. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/deploy-apt-cacher-stack.log`. |
| OP-18 | Deploy `ci-runner-01` | OP-17 complete; runner token procedure approved. | Apply `ci-runner-01`; validate runner registration or explicitly record re-registration steps. | CI runner is running at VMID `141`. | No tracked source files unless runner token handling changes `terraform/secrets.enc.yaml`; evidence log required. |
| OP-19 | Deploy `dns-stack` | OP-18 complete. | Apply `dns-stack` with seed zone; validate authoritative and delegated seed lookups. | CoreDNS is running at VMID `151`. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/deploy-dns-stack.log`. |
| OP-20 | Deploy `step-ca-stack` | OP-19 complete. | Apply `step-ca-stack`; validate CA/ACME prerequisites. | step-ca is running at VMID `152`. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/deploy-step-ca-stack.log`. |
| OP-21 | Deploy `proxy-stack` | OP-20 complete. | Apply `proxy-stack` runtime; validate Traefik accepts HTTPS without needing Authentik. | Traefik runtime is running at VMID `153`. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/deploy-proxy-stack.log`. |
| OP-22 | Deploy `authentik-stack` | OP-21 complete. | Apply `authentik-stack`; complete direct first boot if needed; verify or store API token. | Authentik is healthy at VMID `150` and API token is available through `./with-secrets`. | `terraform/secrets.enc.yaml` only if an API token must be created or rotated; otherwise no tracked source files. Evidence log required. |
| OP-23 | Activate edge reconciliation | OP-22 complete; CoreDNS, Traefik, and Authentik API healthy. | Regenerate edge artifacts; run reconciler apply using the direct Authentik URL; publish generated CoreDNS and Traefik files; run full reconciler dry-run with the same URL. | Browser edge state is generated from manifests and active. | No tracked source files; ignored `terraform/lxc/.generated/`; evidence log required. |
| OP-24 | Deploy `harbor-stack` | OP-23 complete. | Apply `harbor-stack`; validate direct Harbor health and `/v2/` auth challenge. | Harbor is running at VMID `121`. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/deploy-harbor-stack.log`. |
| OP-25 | Deploy `monitoring-stack` | OP-24 complete. | Apply `monitoring-stack`; validate direct services and Grafana browser route behavior. | Monitoring is running at VMID `154`. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/deploy-monitoring-stack.log`. |
| OP-26 | Deploy `netbox-stack` | OP-25 complete. | Apply `netbox-stack`; validate direct service and NetBox browser route behavior. | NetBox is running at VMID `143`. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/deploy-netbox-stack.log`. |
| OP-27 | Deploy `portainer-stack` | OP-26 complete. | Apply `portainer-stack`; validate direct Portainer health. | Portainer is running at VMID `120`. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/deploy-portainer-stack.log`. |
| OP-28 | End-to-end validation | OP-27 complete. | Validate VMIDs/IPs, DNS, HTTPS, certificate, auth behavior, Harbor registry auth, direct Portainer API health on port `9000`, and final full reconciler no-op using the direct Authentik URL. | The rebuilt platform has pass/fail evidence for the full contract. | No tracked source files; `docs/teardown-test/artifacts/evidence/<stamp>/final-validation.log`. |
| OP-29 | Closeout and follow-ups | OP-28 complete. | Summarize result, evidence paths, accepted deviations, certificate-drift decisions, and follow-up tasks. Promote durable lessons into tracked docs instead of leaving them only in raw evidence. | The rehearsal outcome is durable without committing raw evidence. | `docs/teardown-test/README.md`; `docs/teardown-test/variables.md`; `docs/teardown-test/lessons-learned.md`; optionally add `docs/teardown-test/artifacts/reports/<stamp>.md` for a tracked summary. |

## Stop-And-Branch Rule

If an atomic component fails because the source is wrong, do not patch during
the destructive sequence. Record the failure, stop, and create a focused fix
branch. The fix branch should list its own smallest file set, such as one
`stack.yaml`, one Ansible playbook, one test file, and the relevant teardown task
doc. After the fix is validated and merged back to `baseline/teardown-validated`, rerun the
non-destructive preflight before resuming any live operation.
