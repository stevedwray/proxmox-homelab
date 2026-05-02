# Session Report: deploy-kickoff-evening-04

## 1. Session Metadata

| Field | Value |
|---|---|
| Session ID | deploy-kickoff-evening-04 |
| Branch | work/teardown-validate-post-netbox-sso-01 |
| HEAD SHA | e93db3a4b8e073a7d1badca05389c81f113a0551 |
| Baseline anchor | 028d37798cd8c633de43ffcefb84e5f1d7656dc7 |
| Runtime validated SHA | 8744429de243f120f79895bee0c4e4bfbca26999 |
| Delta type (`none` / `metadata-only` / `runtime-change`) | metadata-only |
| Target guard | PASS |

## 2. Gate Results

### `guard-target` - PASS

```bash
$ ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
pve-test
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-02/guard-target.log`

### `portainer-auth-discovery-precheck` - PASS

```bash
$ ./with-secrets python3 terraform/lxc/reconcile-edge.py --authentik-url http://10.57.1.10:9000 --no-verify-tls --json
status: passed
portainer route classification: matching
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-04/reconcile-edge-pre.json`

### `portainer-remediation` - PASS

```bash
$ ./with-secrets ./scripts/provision.sh --stack portainer-stack
[provision] Completed provision orchestration
PLAY RECAP ... failed=0
```

Raw evidence:
- `docs/teardown-test/evidence/20260502-evening-deploy-01/logs/provision-portainer-stack.log`

### `portainer-auth-discovery-postcheck` - PASS

```bash
$ ./with-secrets python3 terraform/lxc/reconcile-edge.py --authentik-url http://10.57.1.10:9000 --no-verify-tls --json
status: passed
portainer route classification: matching
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-04/reconcile-edge-post.json`

### `portainer-route-health` - PASS

```bash
$ curl -skI --resolve portainer.lab.gibbsgreatly.xyz:443:10.57.2.10 https://portainer.lab.gibbsgreatly.xyz/
HTTP/2 302
location: https://authentik.lab.gibbsgreatly.xyz/application/o/authorize/?...
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-04/portainer-route-headers.log`

## 3. Diagnostic Finding (Root Cause)

Portainer is still configured for local application authentication, not native OAuth/OIDC login.

```bash
$ Portainer settings summary
AuthenticationMethod: 1
OAuthSettings.ClientID: ""
OAuthSettings.AuthorizationURI: ""
OAuthSettings.AccessTokenURI: ""
OAuthSettings.ResourceURI: ""
OAuthSettings.RedirectURI: ""
```

Raw evidence:
- `docs/sessions/evidence/deploy-kickoff-evening-04/portainer-settings-auth-summary.json`

Supporting repo evidence:
- `terraform/lxc/stacks/portainer-stack/edge.yaml` uses `auth.mode: forwardAuth`
- `terraform/lxc/discover-authentik-edge.py` has repo-managed OIDC mappings only for Harbor/Grafana, not Portainer
- `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml` does not configure Portainer OAuth settings

## 4. Blockers

- Opened blocker issue: #183 (`[deploy-kickoff-evening-04] Portainer not configured for native OIDC SSO`)

## 5. Recommendation

Run a focused remediation session that:
1. Adds repo-managed Portainer OIDC mapping in `discover-authentik-edge.py` (client id, client secret env var, redirect URIs).
2. Adds Portainer OAuth configuration tasks in `deploy-portainer-stack.yml` and sets Portainer authentication mode to OAuth/SSO.
3. Extends `.env.template` with Portainer OIDC secret placeholders (no hardcoded secrets).
4. Validates end-to-end Portainer SSO login and captures updated evidence.
