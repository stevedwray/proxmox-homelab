# Handoff 02: Production Environment Model

## Objective

Define how production-specific non-secret environment configuration should be
represented and loaded.

## Branch

- `work/productionize-02-production-env-model`

## Primary Source

- [Task 02: Production Environment Model](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/02-production-environment-model.md:1)

## Scope

In scope:

- `.env` layering model
- `.env.pve` design
- variable ownership between `.env`, env overlays, and encrypted secrets

Out of scope:

- real production secret material
- production storage manifest content
- production network intent content

## Files To Read First

- [.env.template](/home/steve/git/proxmox-homelab/.env.template:1)
- [with-secrets](/home/steve/git/proxmox-homelab/with-secrets:1)
- [docs/productionize-refactor/tasks/02-production-environment-model.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/02-production-environment-model.md:1)

## Files Most Likely To Change

- `.env.template`
- docs under `docs/productionize-refactor/`
- possibly a stub `.env.pve` pattern or example doc, but not a real secret file

## Constraints

- keep secret vs non-secret boundaries clear
- do not weaken `pve-test` defaults
- do not commit operator-specific live values unless they are intentionally
  example/template values

## Done When

- the production env overlay model is clearly documented
- variable ownership is explicit
- load order and override behavior are described without ambiguity

## Validation

- it is clear how `PVE_ENV=pve` should be selected
- it is clear which values should stay out of plaintext env files

## Suggested Copilot Brief

```text
Work on Task 02 in docs/productionize-refactor/tasks/02-production-environment-model.md.
Focus only on the production non-secret environment model.
Clarify how .env, .env.pve-test, .env.pve, and encrypted secrets should relate.
Do not add any real secret values.
Keep pve-test as the safe default workflow.
Update the docs so a future implementation session can follow them directly.
```
