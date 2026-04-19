# Provisioning Refactor Plan

This directory is the source of truth for the planned refactor that moves
browser-facing provisioning intent out of central proxy/DNS/Auth runbooks and
into stack-owned manifests.

The objective is to let small AI-agent tasks migrate one stack at a time while
keeping pve-test safe, observable, and easy to roll back.

## Target Model

Each browser-facing stack owns one manifest at:

```text
terraform/lxc/stacks/<stack>/edge.yaml
```

The manifest declares:

- canonical browser hostnames
- backend target or special Traefik service target
- DNS record intent
- TLS resolver policy
- Authentik/Traefik auth mode
- validation expectations

Shared platform components consume those manifests:

- Traefik renderer writes per-stack dynamic files.
- DNS renderer updates the code-managed internal lab zone.
- Authentik reconciler manages provider/app/outpost intent where needed.
- Migration tasks remove central legacy routes only after the generated path is
  validated.

## Scope Boundaries

This refactor is documentation and task planning first. Functional code changes
must happen in later feature branches, one task at a time.

The plan is pve-test only. Production `pve` targeting is intentionally out of
scope until the pve-test model is proven.

## Important Decisions

- Browser hostnames on pve-test use `*.lab.gibbsgreatly.xyz`.
- The internal lab DNS authority is CoreDNS. MikroTik remains the client
  resolver and conditional forwarder, not the per-service record owner.
- Existing Phase 04 browser-ingress prompts are treated as legacy context for
  this refactor. New work should follow this directory.
- Generated Traefik files must not duplicate legacy central host rules during
  migration.
- Authentik automation is split into read-only discovery before write-capable
  reconciliation.

See [decisions.md](decisions.md) for details.

## Files

- [findings-addressed.md](findings-addressed.md) maps the review findings to
  concrete plan changes.
- [decisions.md](decisions.md) records design decisions agents must follow.
- [task-sequence.md](task-sequence.md) lists the complete sequence of small
  implementation tasks.
- [tasks/](tasks/) contains detailed task documents.
- [prompts/](prompts/) contains matching agent prompts.
- [fixtures/](fixtures/) contains example manifest shapes for the contract task.

## How Agents Should Use This

1. Read this README and [decisions.md](decisions.md).
2. Select exactly one task from [task-sequence.md](task-sequence.md).
3. Use the matching prompt from [prompts/index.yaml](prompts/index.yaml).
4. Keep changes inside that task's declared scope.
5. Stop if validation reveals a new issue outside the task boundary.
