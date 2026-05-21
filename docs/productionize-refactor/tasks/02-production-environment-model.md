# Task 02: Production Environment Model

## Goal

Define how production-specific non-secret configuration is represented and
loaded, so `pve` becomes a first-class environment without contaminating the
default dev workflow.

## Objective

Create a production environment model that clearly defines:

- host targeting
- stack IP allocations
- gateway and subnet inputs
- environment-specific service endpoints
- load order and override rules

## Key Design Constraint

Environment modeling must support:

- `pve-test` remaining the default AI and developer target
- `pve` becoming explicitly selectable
- future canary and one-stack-at-a-time migration workflows

## Deliverables

- documented `.env` layering model
- production env overlay design, likely `.env.pve`
- inventory of required production `LAB_IP_*`, `LAB_GW_*`, and
  `LAB_SUBNET_*` values
- explicit statement of which values remain non-secret and which belong only in
  encrypted secret storage

## Questions This Task Must Answer

- what should live in `.env`
- what should live in `.env.pve-test`
- what should live in `.env.pve`
- what should never live outside SOPS-encrypted secret material
- how should `PVE_ENV`, `TF_VAR_proxmox_node`, and `TF_WORKSPACE` behave for
  production

## Files Likely Involved

- [.env.template](/home/steve/git/proxmox-homelab/.env.template:1)
- `.env.pve-test`
- new `.env.pve`
- [with-secrets](/home/steve/git/proxmox-homelab/with-secrets:1)

## Dependencies

- task 01 design should inform how production env material is accessed

## Validation

- a production env overlay can be sourced or injected without overwriting dev
  defaults accidentally
- the effective target node resolves to `pve` when intended
- the effective target node still resolves to `pve-test` by default

## Risks

- mixing secret and non-secret values in the env model
- allowing `.env` defaults to drift toward production accidentally
- stale variable names causing network or service mis-targeting

## Suggested Branch

- `work/productionize-02-production-env-model`
