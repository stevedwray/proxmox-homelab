# 08 — Networking Refactor Resolution Checkpoint

## Purpose

Record that the networking/provisioning blocker previously discovered during
production canary preparation has now been resolved and promoted into
`baseline/teardown-validated`.

This file is no longer a pause notice. It is the bridge between the preserved
productionizing work and the now-validated direct-access network model that
production canary work should use.

## What Changed Since The Original Pause

The dedicated network refactor was completed on `refactor/network`, validated
through representative stack checks plus a full teardown/redeploy cycle on
`pve-test`, then promoted to `baseline/teardown-validated`.

Key outcomes:

1. `prime_sdn_host_route` was removed from the active provisioning model.
2. SDN-backed guest inventories now default to direct routed access instead of
   default `ProxyJump` behavior.
3. The Proxmox host no longer carries the old `.254` guest-subnet workaround on
   `pve-test`.
4. A preflight workflow now exists in:
   - `scripts/preflight-network-refactor.sh`
5. Representative validation passed for:
   - `apt-cacher-stack`
   - `dns-stack`
   - `proxy-stack`
6. The teardown/redeploy validation gate passed and was recorded in:
   - `docs/network-refactor/session-8-summary.md`

## Current Branch State

Branch:

- `refactor/productionize`

This branch has now been rebased in practice by merging the promoted baseline
forward. It includes both:

1. the earlier productionizing work that was preserved during the pause
2. the validated network refactor that removed the provisioning-model blocker

## What Remains Valuable From The Pre-Pause Productionize Work

The earlier productionizing work remains the right base for continued progress:

1. production credential controls and separate production secret handling
2. `.env.pve` and production non-secret environment overlays
3. production storage intent in `terraform/lxc/storage/pve.yaml`
4. production network intent in `terraform/lxc/network/pve.yaml`
5. stack targeting decoupled from hardcoded `pve-test`
6. production SDN guardrails widened beyond the old `pve-test`-only behavior

## What This Means For Task Sequencing

The original reason to pause this branch has been removed.

Updated sequencing:

1. Treat Task 05 as a closeout/verification step unless new contrary evidence
   appears.
2. Resume with Task 06:
   - define and run the production canary validation gate on `pve`
3. Use the validated direct-access model from `docs/network-refactor/` as the
   networking basis for that canary.
4. Only move to Task 07 migration planning after the `pve` canary evidence is
   real.

## Immediate Next Work

The next concrete effort should happen on:

- `work/productionize-06-canary-validation`

Focus:

1. define the production canary runbook
2. confirm the production preflight and operator guardrails
3. choose the first canary target
4. capture evidence criteria before any mutating `pve` run

Recommended first canary:

- `apt-cacher-stack`, unless a disposable validation target is preferred for an
  even lower-risk first pass

## Files To Use As Inputs

Read these first when resuming:

- `docs/network-refactor/validation-gate.md`
- `docs/network-refactor/session-8-summary.md`
- `scripts/preflight-network-refactor.sh`
- `docs/productionize-refactor/tasks/06-canary-validation-gate.md`
- `docs/productionize-refactor/pve-production-readiness.md`
- `terraform/lxc/network/pve.yaml`

## Status Summary

This branch is no longer a preserved checkpoint waiting on a future network
redesign.

It is now an active continuation branch that should resume at the production
canary gate using the validated network model already promoted into baseline.
