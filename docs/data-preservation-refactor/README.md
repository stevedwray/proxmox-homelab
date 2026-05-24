# Data Preservation Refactor

## Purpose

This document tree defines the plan for optional data preservation across a
teardown and redeploy cycle.

The goal is not "never destroy anything." The goal is to make selected stacks
capable of:

- replacing the LXC cleanly
- keeping the durable application data outside the disposable container
- redeploying onto that preserved data when the operator wants continuity

This is optional behavior. A full destroy-and-recreate path must still remain
possible.

## Plan Documents

- [Execution Plan](./plan.md)

## Why This Refactor Exists

For several stacks, teardown and redeploy may be easier and safer than complex
in-place day-2 credential mutation. But that only becomes attractive if we can
preserve the right data between rebuilds.

Today, the repo mostly treats the LXC, Docker data mount, and any extra mount
as one lifecycle unit under Terraform. That means a normal destroy removes the
container and the storage attached to it.

The refactor opportunity is to split:

- disposable container lifecycle
- durable application data lifecycle

## Current State

The rebuild picture today is mixed:

- some stacks are easy to recreate from source with little or no important live
  data
- some stacks already isolate important data onto an extra mount, but that
  mount is still destroyed with the container
- other stacks keep their durable data inside Docker volumes on the
  Terraform-managed Docker disk, which makes retention harder but still
  tractable with storage remodeling
- `step-ca` is special because preserving data there means preserving CA
  identity, not just application content

## Core Strategy

The storage-remodeling approach is:

1. identify the durable state for a stack
2. move that state onto a mount whose lifecycle can be managed separately from
   the LXC
3. teach the stack deploy path to attach and use that preserved mount
4. validate both modes:
   - normal rebuild from scratch
   - rebuild while reusing preserved data

## Candidate Tiers

### Easy First Targets

These are the best first candidates because storage remodeling alone should get
most of the way there.

| Stack | Why it is a good target | Expected work |
|---|---|---|
| `harbor-stack` | Important data is already conceptually isolated at `/var/lib/harbor` | Preserve and reattach the Harbor data mount across LXC replacement |
| `proxy-stack` | Cert and ACME state is already isolated at `/opt/proxy-stack/certs` | Preserve and reattach the cert mount |
| `portainer-stack` | Durable state is small and well-bounded at `/var/lib/portainer` | Move Portainer data onto an explicit durable mount |

### Medium Targets

These look solvable through storage remodeling, but need more redesign because
the durable state currently lives in Docker volumes on the managed Docker disk.

| Stack | Durable state | Main challenge |
|---|---|---|
| `authentik-stack` | Postgres, media, and related volumes | Externalize important Docker volume payloads onto preserved host paths |
| `monitoring-stack` | Grafana, Loki, and VictoriaMetrics data | Move multiple volume-backed datasets without breaking compose behavior |
| `netbox-stack` | Postgres, Redis, media, reports, scripts | Split several interdependent datasets into preserved mounts |

### Low-Value But Easy Targets

These are technically easy but not operationally important enough to lead the
program.

| Stack | Why low value |
|---|---|
| `apt-cacher-stack` | Preserving cache is nice, not critical |
| `ci-runner-01` | Preserves runner cache/workspace, not core platform state |

### Special-Handling Target

| Stack | Why special |
|---|---|
| `step-ca-stack` | Preserving `/etc/step-ca` means preserving CA identity and trust continuity |

`step-ca` may still use storage remodeling eventually, but it should not be the
first implementation target.

## Out Of Scope For The First Pass

- generic preservation for every stack at once
- changing the meaning of `baseline/teardown-validated`
- preserving data for stacks where the value of continuity is low
- CA identity migration as an early milestone

## Relationship To Branching

This work should start only after the baseline/prod convergence stream gives us
a `pve-test` branch that behaves like production in the areas that matter.

That lets us validate preservation on `pve-test` first, instead of designing
and testing the first storage-remodeling flows directly on `pve`.

See
[docs/baseline-merge/README.md](/home/steve/git/proxmox-homelab/docs/baseline-merge/README.md:1).

## Suggested Delivery Sequence

1. Complete baseline/prod convergence.
2. Implement one preserved-mount pattern on `harbor-stack`.
3. Reuse that pattern for `proxy-stack`.
4. Move `portainer-stack` onto a durable mount.
5. Decide whether the Docker-volume-heavy stacks should share one remodeling
   pattern or get service-specific designs.

## Validation Model

Each preservation-capable stack needs two validation paths:

- scratch rebuild:
  destroy and redeploy without reusing preserved state
- preserve-and-rebuild:
  destroy the LXC, reattach the durable mount, and confirm the application
  returns with expected data intact

Validation should happen on `pve-test` first, on a short-lived work branch cut
from the refreshed baseline.

## Initial Success Criteria

- at least one easy target proves preserved rebuild on `pve-test`
- the preserved-data path is optional, not mandatory
- the disposable-versus-durable storage boundary is explicit in code and docs
- a successful `pve-test` result is credible evidence for later `pve` rollout
