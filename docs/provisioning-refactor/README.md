# Provisioning Refactor Plan

This directory is the source of truth for the stack-owned edge provisioning
refactor. Older Phase 04 browser-ingress and Phase 04c planning files are
legacy context only when they conflict with this directory.

The objective is to move browser-facing DNS, Traefik, and Authentik intent out
of central runbooks and into stack-owned manifests while preserving a safe
bootstrap path for a fresh `pve-test-vm` rebuild.

## Target Model

Terraform provisions LXCs from `stack.yaml`. Browser edge intent lives in one
manifest per browser-facing stack:

```text
terraform/lxc/stacks/<stack>/edge.yaml
```

The explicit edge reconciler consumes those manifests after the edge foundation
is healthy:

- Traefik renderer writes per-stack dynamic files.
- CoreDNS renderer updates the code-managed `lab.gibbsgreatly.xyz` zone.
- Authentik discovery/reconciliation manages provider, application, and outpost
  intent where needed.
- Migration tasks replace one legacy central route at a time.

Terraform must not detect edge service readiness, run a hidden second pass, or
reconcile edge state. Edge reconciliation is a separate operator action with
dry-run as the default.

## Bootstrap Model

Fresh Mode 2 deployment uses this order:

1. Stage 0-2 from [bootstrap.md](../design/bootstrap.md): workstation,
   temporary/permanent Portainer, Harbor, and CI runner.
2. Stage 3a edge foundation: CoreDNS seed zone, Traefik runtime, step-ca, then
   Authentik direct first boot and API-token bootstrap.
3. Edge reconciler becomes active only after CoreDNS, Traefik, and Authentik API
   access are healthy.
4. Foundational browser routes converge into stack-owned manifests.
5. All later browser-facing services use `edge.yaml` plus the reconciler as the
   normal path.

Direct-IP access remains the bootstrap fallback for foundational services until
their browser routes are reconciled.

## Scope Boundaries

The plan is `pve-test-vm` only. Production `pve` targeting is out of scope
until the validation model is proven.

Each task is intentionally small enough for one short-lived branch/session. Do
not combine migration tasks unless explicitly requested.

## Important Decisions

- Browser hostnames on `pve-test-vm` use `*.lab.gibbsgreatly.xyz`.
- Generated browser DNS records target Traefik at `10.57.2.10`.
- CoreDNS is the `lab.gibbsgreatly.xyz` authority; MikroTik remains resolver,
  conditional forwarder, and network policy point.
- `stack.yaml` remains the LXC metadata contract and does not gain browser edge
  fields.
- Authentik deletes are never automatic in this refactor.
- Apply mode requires explicit operator intent; dry-run is the default.

See [decisions.md](decisions.md) for details.

## Files

- [decisions.md](decisions.md) records design decisions agents must follow.
- [task-sequence.md](task-sequence.md) lists the complete 22-task atomic sequence.
- [tasks/](tasks/) contains detailed task documents.
- [fixtures/](fixtures/) is reserved for EdgeManifest contract fixtures.
- [runbook.md](runbook.md) is the shared validation and rollback contract for
   Task 15 through Task 21 route migrations.

## How Agents Should Use This

1. Read this README and [decisions.md](decisions.md).
2. Select exactly one task from [task-sequence.md](task-sequence.md).
3. Use the matching task document in [tasks/](tasks/) as the working packet.
4. Keep changes inside that task's declared scope.
5. Stop if validation reveals a new issue outside the task boundary.
