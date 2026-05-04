# Teardown/Deploy Operations Plan

This document is the working decomposition for the `pve-test` teardown/deploy
rehearsal. It turns the high-level task sequence into atomic components that can
be executed one by one with clear handoffs.

This plan does not approve destructive work. Destructive execution still
requires the gates in [variables.md](variables.md), backup evidence, a clean
working tree, a known commit, and explicit operator approval.

## Operating Model

- One source-changing planning package should run in one short-lived branch from
  `dev/pve-test`.
- Live execution packages normally do not modify tracked source files. They write
  runtime evidence under ignored paths such as `docs/teardown-test/evidence/`.
- Every apply, destroy, or deployment validation command must first prove the
  target guard returns exactly `pve-test`:

  ```bash
  ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
  ```

- For direct Ansible validation against inline inventories, always pass
  `-u root`.
- Generated edge artifacts under `terraform/lxc/.generated/` are runtime output,
  not source. Regenerate them immediately before publish.
- Reconciler dry-run and apply commands should use the direct Authentik URL
  `http://10.57.1.10:9000` during rehearsal flows.
- Direct Portainer validation should use the API on port `9000`.
- Certificate drift in `certs/homelab-root.crt` after step-ca rebuild is an
  explicit closeout decision, not background noise.
- If any atomic component exposes a source bug, stop the rehearsal. Fix that bug
  in a separate short-lived branch, merge it back to `dev/pve-test`, then restart
  from the most recent non-destructive preflight.

## Candidate Stack Order

Task 02 must verify this candidate against current `stack.yaml` metadata before
execution. The order below reflects the current bootstrap model and keeps
Traefik independent of Authentik during Stage 3a.

| Order | Unit | VMID | IP | Stage | Reason |
|---:|---|---:|---|---|---|
| 1 | `portainer-stack` | 120 | `10.57.1.20` | Stage 1/2 foundation | Base management service; no stack dependency. |
| 2 | `apt-cacher-stack` | 142 | `10.57.3.11` | Stage 1/2 foundation | Independent apt utility; needed by later apt-backed stacks. |
| 3 | `harbor-stack` | 121 | `10.57.3.10` | Stage 1/2 foundation | Registry foundation; depends on Portainer. |
| 4 | `ci-runner-01` | 141 | `10.57.0.63` | Stage 1/2 foundation | Depends on Portainer, Harbor, and apt-cacher. |
| 5 | `dns-stack` | 151 | `10.57.1.13` | Stage 3a edge foundation | Seed authority for `lab.gibbsgreatly.xyz`. |
| 6 | `proxy-stack` | 153 | `10.57.2.10` | Stage 3a edge foundation | Traefik runtime; must not depend on Authentik. |
| 7 | `step-ca-stack` | 152 | `10.57.1.11` | Stage 3a edge foundation | Internal CA; validates after proxy/network prerequisites. |
| 8 | `authentik-stack` | 150 | `10.57.1.10` | Stage 3a edge foundation | Direct first boot and API-token bootstrap. |
| 9 | edge reconciliation activation | n/a | n/a | Stage 3a handoff | Publish generated DNS, Traefik, and Authentik state. |
| 10 | `monitoring-stack` | 154 | `10.57.1.12` | Stage 3b platform | Depends on Harbor, apt-cacher, Authentik, proxy, and step-ca. |
| 11 | `netbox-stack` | 143 | `10.57.3.12` | Stage 3b platform | Can deploy after Harbor/Portainer, but runs after edge activation so its browser route is validated on the normal path. |

Destroy order is the reverse stack order, excluding the non-Terraform edge
activation unit:

```text
netbox-stack -> monitoring-stack -> authentik-stack -> step-ca-stack ->
proxy-stack -> dns-stack -> ci-runner-01 -> harbor-stack ->
apt-cacher-stack -> portainer-stack
```

## Atomic Planning Components

| ID | Component | Preconditions | Operations | Postconditions | Files modified or added |
|---|---|---|---|---|---|
| OP-00 | Source baseline and branch setup | Current branch is clean. | Merge the current completed branch into `dev/pve-test`; cut the next short-lived branch from `dev/pve-test`; record branch and base commit. | New work starts from the integration branch. | None unless recording the base commit in `variables.md`. |
| OP-01 | Resolve execution variables | OP-00 complete. | Fill operator, window, target, branch, commit, scope, resolver, and approval fields. | `variables.md` has no unresolved destructive-gate values. | `docs/teardown-test/variables.md`; `docs/teardown-test/decisions.md` only if a governing decision changes. |
| OP-02 | Freeze inventory and dependency order | OP-01 complete. | Extract selected stack VMIDs, IPs, zones, dependencies, and playbooks; verify the candidate order; write the approved deploy and destroy order. | Every later operation has a single approved stack order. | Add `docs/teardown-test/inventory.md`; update `docs/teardown-test/variables.md`; update `docs/teardown-test/runbook.md` only for command/order corrections. |
| OP-03 | Approve persistent-data policy | OP-02 complete. | Record backup source, restore confidence, or explicit data-loss approval for every persistent service. | Destruction is blocked unless each selected persistent service has an approved policy. | Add `docs/teardown-test/backup-plan.md`; update `docs/teardown-test/variables.md`. |
| OP-04 | Harden runbook commands | OP-03 complete. | Review target guards, Ansible users, generated-artifact refresh, publish commands, stop conditions, and rollback commands. | The runbook can be followed without inventing commands during the live window. | `docs/teardown-test/runbook.md`; task docs only when their scope or gate changes. |
| OP-05 | Non-destructive source and edge preflight | OP-04 complete. | Run source validation, edge manifest validation, unit tests, generated artifact refresh, and edge dry-run. | Source and generated outputs are ready for an approval packet. | No tracked source files; ignored generated output under `terraform/lxc/.generated/`; evidence under `docs/teardown-test/evidence/<stamp>/`. |
| OP-06 | Destructive approval packet | OP-05 complete. | Present clean tree, branch, commit, target guard, stack list, backup evidence, rollback deadline, and stop conditions. | Operator either approves the destructive window or the plan stops. | No tracked source files; evidence packet under `docs/teardown-test/evidence/<stamp>/approval/`. |

## Atomic Destroy Components

Each destroy component starts by re-running the target guard. Each component
destroys exactly one approved stack and verifies the VMID is absent before the
next component begins.

| ID | Component | Preconditions | Operation | Postconditions | Files modified or added |
|---|---|---|---|---|---|
| OP-07 | Destroy `netbox-stack` | OP-06 approved; stack is in scope. | `terragrunt destroy` for `terraform/lxc/stacks/netbox-stack`; verify VMID `143` absent. | NetBox is absent; no other VMID affected. | No tracked source files; `docs/teardown-test/evidence/<stamp>/destroy-netbox-stack.log`. |
| OP-08 | Destroy `monitoring-stack` | OP-07 complete. | Destroy `monitoring-stack`; verify VMID `154` absent. | Monitoring is absent; no other VMID affected. | No tracked source files; `docs/teardown-test/evidence/<stamp>/destroy-monitoring-stack.log`. |
| OP-09 | Destroy `authentik-stack` | OP-08 complete. | Destroy `authentik-stack`; verify VMID `150` absent. | Authentik is absent after dependent services are gone. | No tracked source files; `docs/teardown-test/evidence/<stamp>/destroy-authentik-stack.log`. |
| OP-10 | Destroy `step-ca-stack` | OP-09 complete. | Destroy `step-ca-stack`; verify VMID `152` absent. | step-ca is absent. | No tracked source files; `docs/teardown-test/evidence/<stamp>/destroy-step-ca-stack.log`. |
| OP-11 | Destroy `proxy-stack` | OP-10 complete. | Destroy `proxy-stack`; verify VMID `153` absent. | Traefik is absent. | No tracked source files; `docs/teardown-test/evidence/<stamp>/destroy-proxy-stack.log`. |
| OP-12 | Destroy `dns-stack` | OP-11 complete. | Destroy `dns-stack`; verify VMID `151` absent. | CoreDNS is absent. | No tracked source files; `docs/teardown-test/evidence/<stamp>/destroy-dns-stack.log`. |
| OP-13 | Destroy `ci-runner-01` | OP-12 complete. | Destroy `ci-runner-01`; verify VMID `141` absent. | CI runner is absent. | No tracked source files; `docs/teardown-test/evidence/<stamp>/destroy-ci-runner-01.log`. |
| OP-14 | Destroy `harbor-stack` | OP-13 complete. | Destroy `harbor-stack`; verify VMID `121` absent. | Harbor is absent after consumers are gone. | No tracked source files; `docs/teardown-test/evidence/<stamp>/destroy-harbor-stack.log`. |
| OP-15 | Destroy `apt-cacher-stack` | OP-14 complete. | Destroy `apt-cacher-stack`; verify VMID `142` absent. | apt-cacher is absent. | No tracked source files; `docs/teardown-test/evidence/<stamp>/destroy-apt-cacher-stack.log`. |
| OP-16 | Destroy `portainer-stack` | OP-15 complete. | Destroy `portainer-stack`; verify VMID `120` absent. | Approved platform scope is absent. | No tracked source files; `docs/teardown-test/evidence/<stamp>/destroy-portainer-stack.log`. |

## Atomic Rebuild Components

Each rebuild component starts by re-running the target guard, applies exactly one
stack or one non-Terraform reconciliation unit, then validates the service before
the next component starts.

| ID | Component | Preconditions | Operation | Postconditions | Files modified or added |
|---|---|---|---|---|---|
| OP-17 | Deploy `portainer-stack` | OP-16 complete. | Apply `portainer-stack`; validate direct Portainer health. | Portainer is running at VMID `120`, `10.57.1.20`. | No tracked source files; `docs/teardown-test/evidence/<stamp>/deploy-portainer-stack.log`. |
| OP-18 | Deploy `apt-cacher-stack` | OP-17 complete. | Apply `apt-cacher-stack`; validate apt-cacher service. | apt-cacher is running at VMID `142`, `10.57.3.11`. | No tracked source files; `docs/teardown-test/evidence/<stamp>/deploy-apt-cacher-stack.log`. |
| OP-19 | Deploy `harbor-stack` | OP-18 complete. | Apply `harbor-stack`; validate direct Harbor health and `/v2/` auth challenge. | Harbor is running at VMID `121`, `10.57.3.10`. | No tracked source files; `docs/teardown-test/evidence/<stamp>/deploy-harbor-stack.log`. |
| OP-20 | Deploy `ci-runner-01` | OP-19 complete; runner token procedure approved. | Apply `ci-runner-01`; validate runner registration or explicitly record re-registration steps. | CI runner is running at VMID `141`, `10.57.0.63`. | No tracked source files unless runner token handling changes `terraform/secrets.enc.yaml`; evidence log required. |
| OP-21 | Deploy `dns-stack` | OP-20 complete. | Apply `dns-stack` with seed zone; validate authoritative and delegated seed lookups. | CoreDNS is running at VMID `151`, `10.57.1.13`. | No tracked source files; `docs/teardown-test/evidence/<stamp>/deploy-dns-stack.log`. |
| OP-22 | Deploy `proxy-stack` | OP-21 complete. | Apply `proxy-stack` runtime; validate Traefik accepts HTTPS on `10.57.2.10:443`. | Traefik runtime is running at VMID `153`, `10.57.2.10`, without needing Authentik. | No tracked source files; `docs/teardown-test/evidence/<stamp>/deploy-proxy-stack.log`. |
| OP-23 | Deploy `step-ca-stack` | OP-22 complete. | Apply `step-ca-stack`; validate CA/ACME prerequisites. | step-ca is running at VMID `152`, `10.57.1.11`. | No tracked source files; `docs/teardown-test/evidence/<stamp>/deploy-step-ca-stack.log`. |
| OP-24 | Deploy `authentik-stack` | OP-23 complete. | Apply `authentik-stack`; complete direct first boot if needed; verify or store API token. | Authentik is healthy at VMID `150`, `10.57.1.10`, and API token is available through `./with-secrets`. | `terraform/secrets.enc.yaml` only if an API token must be created or rotated; otherwise no tracked source files. Evidence log required. |
| OP-25 | Activate edge reconciliation | OP-24 complete; CoreDNS, Traefik, and Authentik API healthy. | Regenerate edge artifacts; run reconciler apply using the direct Authentik URL; publish generated CoreDNS and Traefik files; run full reconciler dry-run with the same URL. | Browser edge state is generated from manifests and active. | No tracked source files; ignored `terraform/lxc/.generated/`; evidence log required. |
| OP-26 | Deploy `monitoring-stack` | OP-25 complete. | Apply `monitoring-stack`; validate direct services and Grafana browser route behavior. | Monitoring is running at VMID `154`, `10.57.1.12`. | No tracked source files; `docs/teardown-test/evidence/<stamp>/deploy-monitoring-stack.log`. |
| OP-27 | Deploy `netbox-stack` | OP-26 complete. | Apply `netbox-stack`; validate direct service and NetBox browser route behavior. | NetBox is running at VMID `143`, `10.57.3.12`. | No tracked source files; `docs/teardown-test/evidence/<stamp>/deploy-netbox-stack.log`. |
| OP-28 | End-to-end validation | OP-27 complete. | Validate VMIDs/IPs, DNS, HTTPS, certificate, auth behavior, Harbor registry auth, direct Portainer API health on port `9000`, and final full reconciler no-op using the direct Authentik URL. | The rebuilt platform has pass/fail evidence for the full contract. | No tracked source files; `docs/teardown-test/evidence/<stamp>/final-validation.log`. |
| OP-29 | Closeout and follow-ups | OP-28 complete. | Summarize result, evidence paths, accepted deviations, certificate-drift decisions, and follow-up tasks. Promote durable lessons into tracked docs instead of leaving them only in raw evidence. | The rehearsal outcome is durable without committing raw evidence. | `docs/teardown-test/README.md`; `docs/teardown-test/variables.md`; `docs/teardown-test/lessons-learned.md`; optionally add `docs/teardown-test/reports/<stamp>.md` for a tracked summary. |

## Stop-And-Branch Rule

If an atomic component fails because the source is wrong, do not patch during
the destructive sequence. Record the failure, stop, and create a focused fix
branch. The fix branch should list its own smallest file set, such as one
`stack.yaml`, one Ansible playbook, one test file, and the relevant teardown task
doc. After the fix is validated and merged back to `dev/pve-test`, rerun the
non-destructive preflight before resuming any live operation.
