# Harbor/Auth Parity Handoff (pve)

## Purpose

Use this handoff to fix the Harbor/Authentiк parity drift on production `pve`
so Harbor follows the same Authentik-integrated behavior that worked on
`pve-test`, without leaving Harbor in a partial OIDC state.

## Problem Statement

The current Harbor production canary shows an internal contradiction:

- the Harbor playbook skipped the Authentik OIDC client reconcile because
  Authentik was considered unavailable
- Harbor still finished the run in `auth_mode=oidc_auth`
- Harbor then skipped local breakglass-user creation because it was already in
  OIDC mode

This creates a risky half-configured state on `pve`.

## Evidence To Start From

Primary production evidence:

- [docs/productionize-refactor/evidence/harbor-canary-20260523-130537/README.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/harbor-canary-20260523-130537/README.md:1)
- [docs/productionize-refactor/evidence/harbor-canary-20260523-130537/31-provision-live.txt](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/harbor-canary-20260523-130537/31-provision-live.txt:163)
- [docs/productionize-refactor/evidence/harbor-canary-20260523-130537/43-registries.txt](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/harbor-canary-20260523-130537/43-registries.txt:1)

Known-good Authentik production evidence from the same day:

- [docs/productionize-refactor/evidence/authentik-canary-20260523-122756/34-provision-live-retry2.txt](/home/steve/git/proxmox-homelab/docs/productionize-refactor/evidence/authentik-canary-20260523-122756/34-provision-live-retry2.txt:140)

Useful parity notes:

- [docs/productionize-refactor/14-pve-parity-pass-01.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/14-pve-parity-pass-01.md:1)

## Code Paths To Inspect First

- [terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml:1)
- [terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml:1)
- [terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md:1)
- [terraform/lxc/stacks/harbor-stack/edge.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/stacks/harbor-stack/edge.yaml:1)

## Current Behavior To Explain

From the Harbor canary evidence:

- Authentik health probe for Harbor reconcile ran
- Harbor logged that Authentik was not reachable yet and reconcile would be
  deferred
- Harbor later logged that breakglass local-user creation was skipped because
  `auth_mode` had already been switched to `oidc_auth`
- Harbor post-deploy health showed `auth_mode: oidc_auth`

From the Authentik canary evidence:

- Authentik direct TLS endpoint at
  `https://authentik-int.lab.gibbsgreatly.xyz:9443/` was already healthy

The next session should explain this mismatch, not just patch around it.

## Goal

Make Harbor on `pve` converge safely:

1. Harbor must not switch into OIDC mode unless the Authentik side is actually
   ready and the Harbor Authentik client reconcile has succeeded.
2. If Authentik is unavailable or reconcile fails, Harbor should remain in a
   safe local-auth state rather than a partial OIDC state.
3. A later rerun, once Authentik is healthy, should converge Harbor cleanly
   into the intended OIDC configuration.
4. The `pve-test` known-good path must not regress.

## Acceptable Fix Shapes

Any solution that meets the goal is fine. Likely shapes:

- gate the Harbor OIDC configuration task on successful Authentik health plus
  successful client reconcile
- fail early when OIDC is requested but the Authentik side is not ready, so the
  operator gets a hard stop instead of a half-configured Harbor
- temporarily keep Harbor in local auth mode and only enable OIDC in a later
  convergent step once reconcile has succeeded

## Constraints

- Treat `pve-test` as the reference model.
- Prefer fixing the playbook sequencing and guards over adding one-off
  production exceptions.
- Do not broaden TLS skips casually; if TLS verification behavior changes,
  explain exactly why.
- Avoid live production mutation unless the operator explicitly asks for it in
  that session.
- Preserve idempotence.

## Suggested Work Sequence

1. Read the Harbor playbook and `harbor_postconfigure` tasks.
2. Compare that with the Harbor production evidence and Authentik production
   evidence.
3. Trace which variable or task path allows OIDC config to proceed after the
   reconcile-deferred branch.
4. Patch the sequencing/guards.
5. Update any docs that still describe the old behavior.
6. Run bounded validation suitable for the changed files.

## Minimum Validation

At minimum, the next session should do read-only or low-risk validation such as:

- code-path inspection with `rg` / `sed`
- Ansible syntax check if applicable
- check-mode or dry-run-safe validation if available

If live validation is not performed, the handback must say so clearly.

## Required Handback Artifact

The next session must create a tracked handback note at:

- `docs/productionize-refactor/handoffs/14-harbor-authentik-parity-handback.md`

That note should include:

- what root cause it found
- what files it changed
- what validation it ran
- whether the fix is code-only or also executed live
- any remaining operator steps or risks

## Done When

- Harbor/Auth parity root cause is explained in the handback
- code changes are made if needed
- the handback file exists and is populated
- the branch is left in a state that can be reviewed or continued by a later
  session without re-deriving the issue
