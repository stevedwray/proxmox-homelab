# Branch Model

## Overview

```
feat/* / fix/* / task/* / work/*    ← active development (short-lived)
        ↓  appropriate validation tier (see below)
stable                              ← validated per its tier, ready for pve
        ↓  incremental deploy on pve + smoke test passes
main                                ← current production state
```

All active validation runs directly against `pve` through the production
approval flow in `AGENTS.md`. `pve-test-vm` is retired and is not a validation
target. Match validation depth to risk: structural changes require a specific
production preflight, rollback plan, and targeted regression checks.

---

## Branches

### Development branches (`feat/*`, `fix/*`, `task/*`, `work/*`)

Cut from the current working HEAD. All active work happens here. Validation
happens on the branch before promotion. Never develop directly on `stable` or `main`.

### `stable`

The intermediate branch. Represents: **validated directly on pve under the
production approval flow, at the depth appropriate to the change — cleared for
incremental deploy to pve**.

The promotion gate is the appropriate validation tier for the change class
(see below).

### `main`

The production branch. Represents: **deployed to pve, smoke test passed**.

Promotion from `stable` to `main` requires:
- The relevant playbooks have run incrementally against pve without failures
- Smoke tests (health endpoints, target status, service reachability) confirm
  no regressions

`main` is not a frozen branch — it tracks actual pve state. A change on `stable`
that has not yet been deployed to pve does not belong on `main`.

---

## Validation Tiers

Match validation depth to change risk. Run the minimum required tier; run higher
tiers only when the change warrants it.

| Change class | Minimum validation before promoting to `stable` |
|---|---|
| Python logic with unit tests | `python3 -m unittest discover -s . -p "test_*.py"` |
| Ansible comment or nosonar changes | `ansible-playbook --syntax-check` on affected playbooks |
| Ansible task or role changes | `scripts/provision.sh --stack <affected>` directly on pve, under the production approval flow |
| Terraform / network / SDN / firewall — additive | Review a production `terragrunt plan`; after approval, apply on pve and test the explicit source-to-target path plus affected consumers |
| Terraform / network / SDN / firewall — modifying or removing | Review the production plan and rollback path before approval; apply on pve, then test every affected path and consumer |
| Authentik, Traefik, or cross-stack integration changes | Redeploy directly on pve and test actual consumer login/routing paths under the production approval flow |

**Ansible changes are not low-risk even when they appear comment-only.** A
`# nosonar` comment inside a Jinja `{{ }}` expression block or a `content: |`
env file block becomes runtime-evaluated content that can silently break deploys.
Always run `--syntax-check` after any Ansible edit.

### Promotion scans and issue handling

Before any branch is promoted, run the security scan(s) required by the files
changed:

| Change type | Required scan before promotion |
|---|---|
| Terraform files | `/home/steve/.local/bin/snyk iac test terraform/` |
| Python, shell, YAML, Ansible, or workflow files | `./with-secrets /home/steve/.local/bin/sonar-scanner` |

If a scan reports new findings, do not promote the branch silently. Create a
GitHub issue for each actionable finding or tightly related group of findings,
link the scan evidence in the issue, and decide whether the issue blocks the
promotion. Blocking findings must be fixed before promotion unless the operator
explicitly accepts the risk in the issue and in the promotion notes.

---

## `baseline/teardown-validated`

This branch is frozen as a historical marker: the last state of the repo that was
validated via a full teardown + redeploy cycle. Do not use it as a base for new
development. It will eventually be archived.

The intent it encoded — "known-good, tested" — is now represented by `stable`,
with a gate that matches what is actually being validated.

### Migration requirements

Before `stable` becomes the active promotion target:

- Create and push the `stable` branch from the agreed current integration point.
- Update `AGENTS.md`, `.github/copilot-instructions.md`, and active workflow
  triggers from `baseline/teardown-validated` to `stable`.
- Update any active planning docs that still instruct operators to branch from
  or merge to `baseline/teardown-validated`.
- Keep `baseline/teardown-validated` read-only as a historical marker until it
  can be archived.

---

## Sprint branches

For multi-session work, use a single long-lived sprint branch rather than a
separate branch per session:

- Named `work/sprint-<topic>` (e.g., `work/sprint-harness`, `work/sprint-env-isolation`)
- Cut from the current working HEAD (or `stable` if the previous sprint just merged)
- All sessions for that sprint land on the sprint branch directly
- Sub-branches are opt-in only — use them when a session needs isolated review,
  not by default
- Delete the sprint branch immediately after it merges to `stable`

Short-lived task branches (`fix/*`, `feat/*`, etc.) follow the normal model and
are deleted on merge. Do not let stale branches accumulate.

---

## Merge Rules

- `stable` is a promotion target only, never a development base.
- `main` is updated only after a successful incremental deploy to pve.
- Force-pushing `main` requires explicit operator action with a documented reason.
- If an operator explicitly names a merge target, use that target exactly.
