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

---

## Session Continuation — Grafana OIDC Runtime Fix — 2026-05-02

### Problem

Grafana SSO button rendered, but login failed with `InternalError`.

Observed runtime error sequence:
- initial failure: token exchange TLS trust error (`x509: certificate signed by unknown authority`)
- after TLS workaround: repeated userinfo failure where Grafana requested `.../application/o/userinfo/emails` and received `404`

### Root Cause

Mixed compatibility behavior between Grafana Generic OAuth (`11.1.4`) and Authentik userinfo handling:
- Grafana attempted an email sub-resource lookup (`/userinfo/emails`) that Authentik does not expose.
- Existing provider defaults did not guarantee stable claim behavior for this integration path.

### Repo-owned Fixes Implemented

**Monitoring deploy wiring**
- `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`
  - Added explicit Generic OAuth settings and claim controls.
  - Added `GF_AUTH_GENERIC_OAUTH_TLS_SKIP_VERIFY_INSECURE` (lab trust compatibility).
  - Enabled ID-token-first behavior (`GF_AUTH_GENERIC_OAUTH_USE_ID_TOKEN=true`).
  - Set Generic OAuth API URL default to empty so Grafana does not rely on userinfo sub-resource behavior.

**Environment template defaults**
- `.env.template`
  - Added/updated Grafana OAuth defaults used by the playbook (including `GRAFANA_OAUTH_USE_ID_TOKEN` and empty `GRAFANA_OAUTH_API_URL`).

**Authentik reconciler hardening**
- `terraform/lxc/reconcile-authentik-edge.py`
  - Added scope property mapping discovery via `/api/v3/propertymappings/provider/scope/`.
  - OIDC providers now enforce default scope property mappings: `openid`, `profile`, `email`.
  - Added preflight failure `AKR008` when required scope mappings are missing.

**Unit tests**
- `terraform/lxc/test_reconcile_authentik_edge.py`
  - Extended fake client with scope property mappings.
  - Added assertion that OIDC provider payload includes expected property mappings.

### Validation Evidence

Commands and outcomes:

```bash
python3 -m unittest terraform/lxc/test_reconcile_authentik_edge.py
```

```text
Ran 17 tests in 0.023s
OK
```

```bash
./with-secrets bash -c 'scripts/provision.sh --stack monitoring-stack 2>&1'
```

Result: completed successfully (`failed=0`).

```bash
./with-secrets bash -c 'curl -sS -k -H "Authorization: Bearer ${AUTHENTIK_SUPERUSER_API_TOKEN}" "https://authentik.lab.gibbsgreatly.xyz/api/v3/providers/oauth2/?name=edge-monitoring-stack-grafana-provider" | jq -r ".results[0] | {name, property_mappings, include_claims_in_id_token, sub_mode}"'
```

Result excerpt:

```json
{
  "name": "edge-monitoring-stack-grafana-provider",
  "property_mappings": [
    "7208b421-7713-45e4-a2e3-296e7231e7f6",
    "81d96ff1-efe6-4a8b-b3de-d3e6591e6bc9",
    "d2905f2a-c6e6-4e77-8a17-9bbc84a2126c"
  ],
  "include_claims_in_id_token": true,
  "sub_mode": "hashed_user_id"
}
```

User-confirmed live result after final deploy: Grafana login via Authentik works.
