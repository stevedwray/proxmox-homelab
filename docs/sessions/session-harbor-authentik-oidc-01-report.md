# Session Report: Harbor Authentik OIDC 01

## Summary

Implemented Harbor wave-1 Authentik SSO groundwork and repository hygiene for the runtime CA cert.

- Added a phased rollout plan for Authentik SSO with Harbor as wave 1.
- Switched Harbor edge intent from `native` to `oidc`.
- Extended Harbor postconfiguration to accept optional `HARBOR_OIDC_*` inputs and apply Harbor OIDC settings through the Harbor configuration API.
- Documented the new Harbor OIDC secret flow in `.env.template` and secrets reference docs.
- Stopped tracking `certs/homelab-root.crt` in git and ignored future runtime drift.

## Files Changed

- `.env.template`
- `.gitignore`
- `docs/plan/authentik-sso-rollout-plan.md`
- `docs/reference/secrets-management.md`
- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`
- `terraform/lxc/ansible/roles/harbor_installer/templates/harbor.yml.j2`
- `terraform/lxc/ansible/roles/harbor_postconfigure/defaults/main.yml`
- `terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml`
- `terraform/lxc/stacks/harbor-stack/edge.yaml`
- `certs/homelab-root.crt` removed from git index only

## Validation Evidence

### Guard

Command:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
```

Result:

```text
pve-test
```

### Design Plan

Created:

- `docs/plan/authentik-sso-rollout-plan.md`

The plan includes `Wave 1`, `Harbor`, `Validation`, `Rollback`, `Branch`, and `Commit` sections required by the gate.

### Harbor Implementation

Confirmed implementation surfaces:

- `terraform/lxc/stacks/harbor-stack/edge.yaml` now declares `auth.mode: oidc`
- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml` wires `HARBOR_OIDC_*` environment inputs into `harbor_postconfigure`
- `terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml` applies Harbor OIDC settings through `/api/v2.0/configurations`
- `terraform/lxc/ansible/roles/harbor_installer/templates/harbor.yml.j2` documents that OIDC is post-install rather than installer-time

### Cert Hygiene

Commands:

```bash
git rm --cached certs/homelab-root.crt
git status --short
! git ls-files --error-unmatch certs/homelab-root.crt >/dev/null 2>&1
```

Result:

- `certs/homelab-root.crt` is no longer tracked by git.
- `.gitignore` now ignores `certs/homelab-root.crt` to prevent future runtime drift from reappearing.

### Validation

Commands:

```bash
python3 terraform/lxc/validate-edge-manifests.py terraform/lxc/stacks/*/edge.yaml
ANSIBLE_ROLES_PATH='terraform/lxc/ansible/roles' ANSIBLE_CONFIG='terraform/lxc/ansible/ansible.cfg' ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
./with-secrets python3 terraform/lxc/discover-authentik-edge.py --json --no-verify-tls
```

Results:

```text
Edge manifest validation passed. Checked 6 manifest(s).
```

```text
[WARNING]: Unable to parse /home/steve/git/proxmox-homelab/terraform/lxc/ansible/inventory as an inventory source
[WARNING]: No inventory was parsed, only implicit localhost is available
[WARNING]: provided hosts list is empty, only localhost is available. Note that the implicit localhost does not match 'all'

playbook: terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
```

```json
{
  "status": "passed",
  "classification_counts": {
    "ambiguous": 0,
    "differing": 0,
    "matching": 6,
    "missing": 0
  },
  "issue_count": 0,
  "route_count": 6
}
```

The Ansible syntax check warnings were inventory-discovery warnings only; the playbook syntax check itself passed.

## Notes

- Harbor OIDC remains opt-in through `HARBOR_OIDC_ENABLED=false` by default, so this session changes deployment wiring and validation intent without forcing immediate live cutover.
- Harbor browser SSO and Harbor CLI authentication remain separate. Users will still need Harbor CLI secrets or robot credentials for Docker and Helm workflows.
- No destructive infrastructure actions were performed.

## Repository State

- Branch: `feat/harbor-authentik-oidc-01`
- Baseline SHA: `8149524b8d2bdc76758d64b0df85dcf62bf8f295`
- Working HEAD before commit: `2e0392885ab19894844297e0047a14cebbca7c93`

---

## Session Continuation — Executor (heavy) — 2025-05-02

### Objective

Complete the end-to-end deploy path so Harbor self-provisions its Authentik OIDC client on deploy.

### Key Changes (commit eb9268e)

**reconcile-authentik-edge.py**
- Added `_resolve_oidc_candidates()` and `_oidc_provider_payload()` for native OIDC route reconciliation via Authentik OAuth2 provider API
- **Scoped orphan-check stop_conditions to current-manifest stacks only.** Previously any `edge-*` object not consumed by the run would trigger a stop condition. When called with a single-stack manifest this caused false positives from other stacks (netbox, portainer, traefik-dashboard). Fix: `any(f"edge-{intent.stack}-" in name for intent in intents)`.

**discover-authentik-edge.py**
- `fetch_oauth2_providers()`, `_classify_oidc_route()`, `_check_oidc_provider_match()`, `_oidc_route_supported()`

**reconcile-edge.py**
- `_manifest_requires_authentik()` returns `True` for `auth.mode: oidc`

**deploy-harbor-stack.yml**
- `pre_tasks` block in play 3 runs `reconcile-authentik-edge.py --apply` before postconfigure
- OIDC defaults: endpoint → Authentik well-known URL, client_id → `harbor`, enabled → `true`

### Live Verification

```json
{
  "auth_mode": "oidc_auth",
  "oidc_endpoint": "https://authentik.lab.gibbsgreatly.xyz/application/o/edge-harbor-stack-harbor/.well-known/openid-configuration",
  "oidc_client_id": "harbor",
  "oidc_name": "authentik",
  "primary_auth_mode": true
}
```

Provision run: `ok=49  failed=0`. 35 unit tests PASS.

### Commit

`eb9268eb4d3f557f99ba1bc357eabeafc3fec26d` on `feat/harbor-authentik-oidc-01`
