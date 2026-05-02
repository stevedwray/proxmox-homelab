# Session Report: deploy-kickoff-evening-05

## 1. Session Metadata

| Field | Value |
|---|---|
| Session ID | deploy-kickoff-evening-05 |
| Branch | work/teardown-validate-post-netbox-sso-01 |
| HEAD SHA (start) | e9758bb23cf6a58ba84516e66341d1eff4e82b52 |
| Baseline anchor | 028d37798cd8c633de43ffcefb84e5f1d7656dc7 |
| Runtime validated SHA (pre-commit) | e9758bb23cf6a58ba84516e66341d1eff4e82b52 |
| Delta type | runtime-change |

## 2. Gate Results

### `guard-target` - PASS

```bash
$ ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
pve-test
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-02/guard-target.log`

### `portainer-oidc-mapping` - PASS

```bash
$ rg -n 'portainer|OIDC_ROUTE_CLIENT_IDS|OIDC_ROUTE_CLIENT_SECRETS|_oidc_redirect_uris' terraform/lxc/discover-authentik-edge.py terraform/lxc/reconcile-authentik-edge.py
... portainer-stack mapping entries present ...
```

Raw evidence:
- `terraform/lxc/discover-authentik-edge.py`

### `portainer-oauth-config-apply` - FAIL

```bash
$ ./with-secrets ./scripts/provision.sh --stack portainer-stack
FAILED: Set PORTAINER_OAUTH_CLIENT_SECRET before running deploy-portainer-stack when PORTAINER_OAUTH_ENABLED=true.
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-05/portainer-oauth-config-apply-fail.log`

### `portainer-auth-method-check` - SKIP

Skipped for gate accounting because the required apply gate failed under standard environment injection.

Diagnostic evidence (non-gating):
- `docs/sessions/evidence/deploy-kickoff-evening-05/portainer-settings-auth-summary.json`

### `portainer-route-health` - SKIP

Skipped for gate accounting because the required apply gate failed under standard environment injection.

Diagnostic evidence (non-gating):
- `docs/sessions/evidence/deploy-kickoff-evening-05/portainer-route-headers.log`

### `env-template-portainer-oidc` - PASS

```bash
$ rg -n 'PORTAINER_.*(OIDC|OAUTH).*' .env.template
... PORTAINER_OAUTH_* entries present ...
```

Raw evidence:
- `.env.template`

## 3. Changes Made

- `terraform/lxc/discover-authentik-edge.py`
  - Added Portainer repo-managed OIDC mapping:
    - `OIDC_ROUTE_CLIENT_IDS[('portainer-stack','portainer')]`
    - `OIDC_ROUTE_CLIENT_SECRETS[('portainer-stack','portainer')]`
    - Portainer redirect URI in `_oidc_redirect_uris`

- `terraform/lxc/stacks/portainer-stack/edge.yaml`
  - Switched route `auth.mode` from `forwardAuth` to `oidc`

- `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml`
  - Added Portainer OAuth variables from environment
  - Added assertion for `PORTAINER_OAUTH_CLIENT_SECRET` when OAuth is enabled
  - Added settings GET/merge/PUT flow for `AuthenticationMethod` and `OAuthSettings`

- `.env.template`
  - Added `PORTAINER_OAUTH_*` placeholders and secret placeholder

## 4. Blocker

`./with-secrets` in this environment does not inject `PORTAINER_OAUTH_CLIENT_SECRET`, so standard provisioning fails.

## 5. Recommendation

Add `PORTAINER_OAUTH_CLIENT_SECRET` to the secrets source consumed by `./with-secrets`
(SOPS-backed `terraform/secrets.enc.yaml` in this workflow), then rerun gates:

1. `portainer-oauth-config-apply`
2. `portainer-auth-method-check`
3. `portainer-route-health`
