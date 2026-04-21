# OP-26 and OP-27 Platform Redeploy Checkpoint

Date: 2026-04-21 (UTC)
Branch: docs/teardown-test-execution-variables

## Scope Guardrails Followed

- Dry-run only for reconciler confirmation
- No reconcile --apply
- No Terraform apply/destroy in this checkpoint step
- No CoreDNS or Traefik publish
- No OP-28 or OP-29 execution
- certs/homelab-root.crt was left modified and was not staged or reverted

## OP-26 Monitoring Outcome (Checkpoint Summary)

- OP-26 encountered interruption/orphaned-state behavior during earlier execution and required recovery handling.
- Import/recovery attempts were used to reconcile state continuity.
- OP-26 concluded with a clean redeploy outcome and monitoring service paths restored for subsequent validation.

## OP-27 NetBox Outcome (Checkpoint Summary)

- OP-27 completed with successful stack deployment and service reachability.
- NetBox direct/routed behavior was revalidated after reconciliation fixes.

## Authentik Outpost Issue and Fix Summary

- Root issue: routed NetBox previously hit Authentik 404 on the outpost endpoint path.
- First fix wave: preferred the served embedded outpost model and ensured provider links were attached to the serving outpost.
- Second fix wave: refined reconciler status semantics and probe behavior.
  - Pre/post-apply discovery handling avoids stale drift signaling after convergence.
  - Forward-auth probe treats valid redirect/unauthorized responses as serving success.
  - Connectivity-only probe failures are separated from drift classification.
  - Legacy unmanaged outpost remains visible but non-blocking when managed routes are converged.

## Final Non-Mutating Reconcile Confirmation

Command run:

./with-secrets python3 terraform/lxc/reconcile-edge.py --authentik-url http://10.57.1.10:9000 --no-verify-tls --json | tee /tmp/reconcile-edge-post-op27-final-confirmation.json

Result summary:

- status: passed
- issues: []
- Traefik validation: passed
- CoreDNS validation: passed
- Authentik discovery classification matching: 6
- unmanaged legacy outpost: present (count 1), non-blocking
- Authentik reconcile write_count: 0
- Authentik reconcile action_counts: noop 7

## Routed Grafana and NetBox Checks

Commands run:

- curl -skI --resolve grafana.lab.gibbsgreatly.xyz:443:10.57.2.10 https://grafana.lab.gibbsgreatly.xyz
- curl -skI --resolve netbox.lab.gibbsgreatly.xyz:443:10.57.2.10 https://netbox.lab.gibbsgreatly.xyz

Observed:

- Grafana: HTTP 302 to /login through Traefik; no forward-auth redirect behavior observed.
- NetBox: HTTP 302 through Traefik into Authentik authorization flow; no Authentik 404 observed.

## Status at This Gate

- OP-26 and OP-27 are checkpointed.
- Reconciler fix set is checkpointed with final non-mutating confirmation.
- OP-28 and OP-29 remain intentionally not executed.
