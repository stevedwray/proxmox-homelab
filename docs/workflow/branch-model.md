# Branch Model

## Overview

```
feat/* / fix/* / task/* / work/*    ← active development (short-lived)
        ↓  appropriate validation tier (see below)
stable                              ← validated on pve-test, ready for pve
        ↓  incremental deploy on pve + smoke test passes
main                                ← current production state
```

This model replaces the `baseline/teardown-validated` intermediate branch.

---

## Branches

### Development branches (`feat/*`, `fix/*`, `task/*`, `work/*`)

Cut from the current working HEAD. All active work happens here. Validation
happens on the branch before promotion. Never develop directly on `stable` or `main`.

### `stable`

The intermediate branch. Represents: **validated on pve-test, cleared for
incremental deploy to pve**.

The promotion gate is the appropriate validation tier for the change class
(see below). A full teardown is only required for high-risk structural changes —
not every promotion.

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
| Ansible task or role changes | `scripts/provision.sh --stack <affected>` on pve-test |
| Terraform / network / SDN / firewall | Full teardown cycle on pve-test |
| Authentik, Traefik, or cross-stack integration changes | Full teardown cycle on pve-test |

**Ansible changes are not low-risk even when they appear comment-only.** A
`# nosonar` comment inside a Jinja `{{ }}` expression block or a `content: |`
env file block becomes runtime-evaluated content that can silently break deploys.
Always run `--syntax-check` after any Ansible edit.

---

## Teardown Testing

The full teardown cycle (Terraform destroy → redeploy all stacks from scratch) is
**no longer a gate on every promotion to `stable`**. It is a periodic health check:

- Run before any major structural change (Terraform, SDN, cross-stack auth)
- Run on pve-test after a cluster of related changes when there is uncertainty
  about fresh-install behaviour
- Run as a periodic maintenance check (roughly monthly or when pve-test diverges
  from main significantly)

The teardown cycle validates: can the infrastructure be rebuilt from scratch in
the repo's current state? This matters for disaster recovery and for catching
provisioning-path regressions that incremental deploys mask. It does not need to
happen on every PR.

---

## `baseline/teardown-validated`

This branch is frozen as a historical marker: the last state of the repo that was
validated via a full teardown + redeploy cycle. Do not use it as a base for new
development. It will eventually be archived.

The intent it encoded — "known-good, tested" — is now represented by `stable`,
with a gate that matches what is actually being validated.

---

## Merge Rules

- `stable` is a promotion target only, never a development base.
- `main` is updated only after a successful incremental deploy to pve.
- Force-pushing `main` requires explicit operator action with a documented reason.
- If an operator explicitly names a merge target, use that target exactly.
- `dev/pve-test` is retired (archival only — do not use as a PR target).
