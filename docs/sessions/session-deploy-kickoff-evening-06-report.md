# Session Report: deploy-kickoff-evening-06

## 1. Session Metadata

| Field | Value |
|---|---|
| Session ID | deploy-kickoff-evening-06 |
| Branch | work/portainer-oidc-runtime-fix-06 |
| HEAD SHA | e51029b836c26c9a4eb0dc27f0f2a314eda9e78a |
| Baseline anchor | 028d37798cd8c633de43ffcefb84e5f1d7656dc7 |
| Runtime validated SHA | e51029b836c26c9a4eb0dc27f0f2a314eda9e78a |
| Delta type (none / metadata-only / runtime-change) | runtime-change |
| Lineage check | PASS |
| Target guard | PASS |
| Working tree | clean |
| Open issues at start | none |

## 2. Gate Results

`guard-target` - PASS

```bash
$ cd /home/steve/git/proxmox-homelab && ./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
pve-test
exit: 0
```

`repro-redirect-uri-error` - PASS

```bash
$ cd /home/steve/git/proxmox-homelab && mkdir -p docs/sessions/evidence/deploy-kickoff-evening-06 && curl -skI --resolve portainer.lab.gibbsgreatly.xyz:443:10.57.2.10 https://portainer.lab.gibbsgreatly.xyz/ | tr -d '\r' | tee docs/sessions/evidence/deploy-kickoff-evening-06/portainer-route-headers-before.log
HTTP/2 302
location: https://authentik.lab.gibbsgreatly.xyz/application/o/authorize/?client_id=portainer&redirect_uri=https%3A%2F%2Fportainer.lab.gibbsgreatly.xyz%2Foutpost.goauthentik.io%2Fcallback%3FX-authentik-auth-callback%3Dtrue&response_type=code...
exit: 0
```

Additional browser-equivalent evidence:

```bash
$ curl -skL --resolve portainer.lab.gibbsgreatly.xyz:443:10.57.2.10 https://portainer.lab.gibbsgreatly.xyz/ -o docs/sessions/evidence/deploy-kickoff-evening-06/portainer-browserlike-before.html
$ rg -n "Redirect URI Error|redirect_uri" docs/sessions/evidence/deploy-kickoff-evening-06/portainer-browserlike-before.html
92:Redirect URI Error
99:    <p>The request fails due to a missing, invalid, or mismatching redirection URI (redirect_uri).</p>
exit: 0
```

`portainer-oauth-remediation-apply` - PASS

```bash
$ cd /home/steve/git/proxmox-homelab && ./with-secrets ./scripts/provision.sh --stack portainer-stack | tee docs/sessions/evidence/deploy-kickoff-evening-06/provision-portainer-stack-pass.log
[provision] PORTAINER_OAUTH_CLIENT_SECRET is already present
[provision] Reconcile edge apply for Portainer route publication
... "status": "passed" ...
[provision] Publish generated Traefik files for Portainer route
PLAY RECAP *********************************************************************
proxy-stack                : ok=29   changed=1    unreachable=0    failed=0
...
PLAY RECAP *********************************************************************
portainer-stack            : ok=31   changed=0    unreachable=0    failed=0
[provision] Completed provision orchestration
exit: 0
```

`portainer-auth-settings-after` - PASS

```bash
$ cd /home/steve/git/proxmox-homelab && ./with-secrets bash -lc 'set -euo pipefail; mkdir -p docs/sessions/evidence/deploy-kickoff-evening-06; pw="${PORTAINER_ADMIN_PASSWORD:-${TF_VAR_portainer_admin_password:-}}"; payload="{"username":"admin","password":"${pw}"}"; token=$(curl -sS --max-time 15 http://10.57.1.20:9000/api/auth -H "Content-Type: application/json" -d "$payload" | jq -r ".jwt"); curl -sS --max-time 15 http://10.57.1.20:9000/api/settings -H "Authorization: Bearer $token" | jq "{AuthenticationMethod, OAuthSettings}" | tee docs/sessions/evidence/deploy-kickoff-evening-06/portainer-settings-auth-summary-after.json'
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
exit: 0
```

`portainer-route-health-after` - PASS

```bash
$ cd /home/steve/git/proxmox-homelab && curl -skI --resolve portainer.lab.gibbsgreatly.xyz:443:10.57.2.10 https://portainer.lab.gibbsgreatly.xyz/ | tr -d '\r' | tee docs/sessions/evidence/deploy-kickoff-evening-06/portainer-route-headers-after.log
HTTP/2 200
content-type: text/html; charset=utf-8
exit: 0
```

`env-template-portainer-oidc` - PASS

```bash
$ cd /home/steve/git/proxmox-homelab && rg -n 'PORTAINER_.*(OIDC|OAUTH).*' .env.template | tee docs/sessions/evidence/deploy-kickoff-evening-06/env-template-portainer-oidc.log
106:export PORTAINER_OAUTH_ENABLED=true
108:export PORTAINER_OAUTH_CLIENT_ID='portainer'
109:export PORTAINER_OAUTH_AUTH_URL='https://authentik.lab.gibbsgreatly.xyz/application/o/authorize/'
110:export PORTAINER_OAUTH_TOKEN_URL='https://authentik.lab.gibbsgreatly.xyz/application/o/token/'
111:export PORTAINER_OAUTH_RESOURCE_URL='https://authentik.lab.gibbsgreatly.xyz/application/o/userinfo/'
112:export PORTAINER_OAUTH_LOGOUT_URL='https://authentik.lab.gibbsgreatly.xyz/application/o/edge-portainer-stack-portainer/end-session/'
113:export PORTAINER_OAUTH_USER_IDENTIFIER='preferred_username'
114:export PORTAINER_OAUTH_SCOPES='openid profile email'
115:export PORTAINER_OAUTH_CLIENT_SECRET='__FROM_BITWARDEN__'       # Authentik OIDC client secret for Portainer SSO
exit: 0
```

## 3. Changes Made

- scripts/provision.sh
  - Added `ensure_portainer_edge_publish` to reconcile/publish Portainer edge route during `--stack portainer-stack` runs.
  - Invoked helper in the main stack loop so Portainer deploy updates proxy dynamic config before app deploy.
  - Commit: e51029b836c26c9a4eb0dc27f0f2a314eda9e78a

## 4. Blockers

None.

## 5. Recommendation

Focus architect review on the new provision flow step that republishes Portainer route config via proxy stack; this session materially advances to go/no-go and should be treated as GO for the redirect_uri regression.
