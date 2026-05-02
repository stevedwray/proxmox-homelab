# Session Report: deploy-kickoff-evening-05

## 1. Session Metadata

| Field | Value |
|---|---|
| Session ID | deploy-kickoff-evening-05 |
| Branch | work/teardown-validate-post-netbox-sso-01 |
| Issue | #183 |
| HEAD SHA (start) | e9758bb23cf6a58ba84516e66341d1eff4e82b52 |
| Baseline anchor | 028d37798cd8c633de43ffcefb84e5f1d7656dc7 |
| Runtime validated SHA | 391f2cd7779e3c9c5a37481ad469d9a815c3ff42 |
| Delta type | runtime-change |
| Final outcome | PASS (all required gates) |

## 2. Executive Summary

Portainer now authenticates with Authentik using native OIDC and is deployable via the standard
`./with-secrets ./scripts/provision.sh --stack portainer-stack` workflow.

The original blocker was missing `PORTAINER_OAUTH_CLIENT_SECRET` injection. That gap was closed by:

1. Implementing native Portainer OIDC mapping and playbook-side OAuth configuration.
2. Adding deploy preflight bootstrap logic for missing Portainer OAuth secret.
3. Persisting `PORTAINER_OAUTH_CLIENT_SECRET` in SOPS (`terraform/secrets.enc.yaml`).

Blocker issue #183 is closed.

## 3. Gate Results

### `guard-target` - PASS

```bash
$ ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
pve-test
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-05/guard-target.log`

### `portainer-oidc-mapping` - PASS

```bash
$ rg -n 'portainer|OIDC_ROUTE_CLIENT_IDS|OIDC_ROUTE_CLIENT_SECRETS|_oidc_redirect_uris' terraform/lxc/discover-authentik-edge.py terraform/lxc/reconcile-authentik-edge.py
... portainer mapping + secret env + redirect URI hooks present ...
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-05/portainer-oidc-mapping.log`

### `portainer-oauth-config-apply` - PASS

```bash
$ ./with-secrets ./scripts/provision.sh --stack portainer-stack
[provision] PORTAINER_OAUTH_CLIENT_SECRET is already present
...
PLAY RECAP ... failed=0
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-05/provision-portainer-stack-pass.log`

### `portainer-auth-method-check` - PASS

```json
{
  "AuthenticationMethod": 3,
  "OAuthSettings": {
    "ClientID": "portainer",
    "AuthorizationURI": "https://authentik.lab.gibbsgreatly.xyz/application/o/authorize/",
    "AccessTokenURI": "https://authentik.lab.gibbsgreatly.xyz/application/o/token/",
    "ResourceURI": "https://authentik.lab.gibbsgreatly.xyz/application/o/userinfo/",
    "RedirectURI": "https://portainer.lab.gibbsgreatly.xyz"
  }
}
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-05/portainer-settings-auth-summary.json`

### `portainer-route-health` - PASS

```bash
$ curl -skI --resolve portainer.lab.gibbsgreatly.xyz:443:10.57.2.10 https://portainer.lab.gibbsgreatly.xyz/
HTTP/2 302
location: https://authentik.lab.gibbsgreatly.xyz/application/o/authorize/?client_id=portainer...
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-05/portainer-route-headers.log`

### `env-template-portainer-oidc` - PASS

```bash
$ rg -n 'PORTAINER_.*(OIDC|OAUTH).*' .env.template
... PORTAINER_OAUTH_* entries present ...
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-05/env-template-portainer-oidc.log`

## 4. Changes Delivered

- `terraform/lxc/discover-authentik-edge.py`
  - Added Portainer repo-managed OIDC mapping and redirect URI support.

- `terraform/lxc/stacks/portainer-stack/edge.yaml`
  - Switched Portainer auth mode from `forwardAuth` to `oidc`.

- `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml`
  - Added OAuth variables, assertion, and idempotent settings reconciliation via Portainer API.

- `scripts/provision.sh`
  - Added Portainer-specific preflight to bootstrap missing OAuth secret for deploy flow.
  - Added Authentik reconcile call for Portainer manifest before stack apply.

- `.env.template`
  - Added Portainer OIDC/OAuth placeholders including secret key placeholder.

- `terraform/secrets.enc.yaml`
  - Persisted `PORTAINER_OAUTH_CLIENT_SECRET` in SOPS-backed secrets.

## 5. Commits in This Resolution Path

1. `704b772de3f6bce0e40f75c9159b92a914aebf6f` - feat: wire portainer native oidc configuration
2. `15f8c549f61737c00282b3028eac84bfb17dbb32` - fix: bootstrap portainer oauth secret in provision workflow
3. `391f2cd7779e3c9c5a37481ad469d9a815c3ff42` - chore: persist portainer oauth secret in sops

## 6. Risks and Follow-up

1. During validation, an attempted automated SOPS mutation path was removed after proving unsafe in this environment.
2. Current workflow is stable because the secret is now persisted in SOPS and loaded via `with-secrets`.
3. Optional follow-up: add a dedicated, tested secret-rotation helper with explicit operator opt-in.
