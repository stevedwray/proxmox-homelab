# 00b-pve-test-02 — Update pve-test environment isolation after Portainer bootstrap

## Status

PENDING

## Phase

Phase 00b — pve-test Management Bootstrap

## Greenfield assumption

This task runs immediately after the local Portainer bootstrap stack is healthy on a true
greenfield `pve-test` rebuild.

## Prerequisites

- [00b-pve-test-01 — Deploy Portainer bootstrap stack on bare-metal pve-test](00b-pve-test-01-deploy-portainer.md) complete
- `.env.pve-test` exists
- `.env.template` exists

## Objective

All subsequent `pve-test` applies target the local Portainer server at `192.168.1.20`
instead of the retired production default at `192.168.1.4`.

## Scope

- Update `.env.pve-test` with `TF_VAR_portainer_server_ip=192.168.1.20`
- Add a comment-only placeholder to `.env.template`
- Verify the override is visible in the shell before later stack deploys

## Out of Scope

- Deploying ci-runner-01
- Any Terraform or Ansible applies

## Acceptance Criteria

- [ ] `.env.pve-test` exports `TF_VAR_portainer_server_ip=192.168.1.20`
- [ ] `.env.template` documents the override as a pve-test-only setting
- [ ] `echo "$TF_VAR_portainer_server_ip"` prints `192.168.1.20` after sourcing `.env` and `.env.pve-test`

## Session Prompt

```text
TASK: Update the pve-test environment so later stacks register with the local Portainer at
192.168.1.20 instead of the old production Portainer.

STEP 1 — Edit .env.pve-test:
  export TF_VAR_portainer_server_ip=192.168.1.20

STEP 2 — Add a comment-only placeholder to .env.template:
  # pve-test overrides (set in .env.pve-test, not here)
  # TF_VAR_portainer_server_ip=192.168.1.20   # pve-test Portainer

STEP 3 — Verify:
  source .env
  source .env.pve-test
  echo "$TF_VAR_portainer_server_ip"
  # Expect: 192.168.1.20

DONE WHEN: Later pve-test stack deploys will use the local Portainer server.
```
