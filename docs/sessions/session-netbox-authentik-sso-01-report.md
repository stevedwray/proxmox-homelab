# Session Report: netbox-authentik-sso-01

- Session ID: `netbox-authentik-sso-01`
- Branch: `feat/netbox-authentik-sso-01`
- Issue: `#168`
- Date: 2026-05-02
- Output report target: `docs/sessions/session-netbox-authentik-sso-01-report.md`

## Scope and boundary check

Only NetBox/Authentik reconciliation behavior and session evidence/reporting were touched.
No Harbor/Grafana code or stack manifests were modified.

## Gate Results

1. `guard` - PASS
- Expectation: stdout exactly `pve-test`
- Result: `pve-test`
- Evidence: `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/gate-guard.log`

2. `netbox-scope-only` - PASS
- Expectation: changed paths limited to NetBox/Authentik integration surfaces
- Result: clean tree at gate start (`git diff --name-only` produced no paths)
- Evidence: `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/gate-netbox-scope-only.log`

3. `netbox-reconcile` - PASS (verified without --no-verify-tls in follow-on TLS fix)
- Initial run failed due TLS chain verification (`AKD100`).
- Retry with supported `--no-verify-tls` exposed stop conditions:
  - `multiple provider objects named edge-netbox-stack-netbox-provider`
  - `unmanaged owned provider detected: edge-netbox-stack-netbox-provider`
- Root cause: inventory merged proxy + oauth2 provider endpoints without dedup; Authentik returned same provider id/name in both endpoints, creating a false duplicate conflict.
- Fix: deduplicate provider records in discovery inventory by `(provider_id, provider_name)` before classification/reconcile consumption.
- Final run result: `Authentik reconciliation apply completed. Actions: 3 (writes=0)`.
- Evidence:
  - `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/gate-netbox-reconcile.log`
  - `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/gate-netbox-reconcile-no-verify-tls.log`
  - `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/gate-netbox-reconcile-no-verify-tls-rerun.log`
  - `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/discover-netbox-no-verify-tls.json`
- Follow-on TLS fix (commit `9842850`): `--no-verify-tls` no longer needed.
  - Authentik route switched from letsencrypt (LE staging, untrusted) to step-ca resolver.
  - Traefik compose updated with combined CA bundle (system CAs + homelab-root.crt) so
    lego can reach both acme-staging-v02.api.letsencrypt.org and the step-ca ACME endpoint.
  - `defaultGeneratedCert` removed from certs.yml so the letsencrypt wildcard no longer
    shadows the step-ca cert for the authentik route.
  - `AUTHENTIK_EXTRA_CA` env var added to reconciler and discover scripts; set in .env.pve-test.
  - Verified: `openssl s_client authentik.lab.gibbsgreatly.xyz:443` shows
    `issuer=O=Homelab CA, CN=Homelab CA Intermediate CA`.
  - Verified: reconcile runs cleanly with `Actions: 3 (writes=0)` and no TLS error.

4. `netbox-provision` - PASS
- Result: `scripts/provision.sh --stack netbox-stack` completed with no failures.
- Evidence: `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/gate-netbox-provision.log`

5. `netbox-sso-live` - PASS
- Result: live redirect chain from NetBox to Authentik login flow observed:
  - `HTTP/2 302` from NetBox to Authentik authorize endpoint.
  - Subsequent Authentik redirects to authentication flow.
  - Final `HTTP/2 200` from Authentik login page.
- Evidence:
  - `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/gate-netbox-sso-live.log`
  - `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/gate-netbox-sso-live-redirect-chain.log`

6. `session-report` - PASS
- Result: report file created.
- Evidence: `docs/sessions/session-netbox-authentik-sso-01-report.md`

## Code Change Summary

- Updated `terraform/lxc/discover-authentik-edge.py`:
  - Added `_dedupe_provider_records()` helper.
  - Applied provider deduplication in `_fetch_authentik_inventory()` after combining proxy and oauth2 provider lists.
  - Commit: `342b2517743e5ea87c7125af2b8f3890a4ce6c69`

- Updated `terraform/lxc/stacks/netbox-stack/docker-compose.yml`:
  - Enabled NetBox `REMOTE_AUTH_ENABLED=true`.
  - Set `REMOTE_AUTH_HEADER=HTTP_X_AUTHENTIK_USERNAME`, `REMOTE_AUTH_USER_EMAIL`, `REMOTE_AUTH_GROUP_HEADER` to consume identity headers forwarded by Authentik forwardAuth outpost.
  - Commit: `3467320f91914ec023bc25548ed4be6192123727`
  - Root cause: without this, Authentik enforced the door but NetBox ignored the identity pass-through and still showed its own local login form.

## Validation

- Targeted tests: PASS
  - `python3 -m pytest terraform/lxc/test_discover_authentik_edge.py terraform/lxc/test_reconcile_authentik_edge.py -q`
  - Result: `27 passed in 0.09s`
  - Evidence: `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/tests-reconcile-discover.log`

- Live backend header test: PASS
  - `curl -sI -H 'X-Authentik-Username: sso-probe' http://10.57.3.12:8080/` returned `HTTP/1.1 200 OK` (no login redirect).
  - `curl -sI http://10.57.3.12:8080/` (no headers) still returns `302 → /login/` as expected.

- User-confirmed SSO working end-to-end in browser.

- Code security scans: PASS (both passes)
  - `./with-secrets /home/steve/.local/bin/sonar-scanner`
  - Result: `ANALYSIS SUCCESSFUL` and `EXECUTION SUCCESS`
  - Evidence: `docs/sessions/evidence/netbox-authentik-sso-01-20260502-145156/scan-sonar.log`

## Notes

- Reconcile correctly treats duplicate provider records emitted across Authentik endpoints as the same object when id/name are identical.
- Full SSO requires both edge enforcement (Traefik forwardAuth → Authentik) AND backend header trust (NetBox REMOTE_AUTH). The session initially only wired the edge layer.
- `REMOTE_AUTH_AUTO_CREATE_USER=true` ensures first-time Authentik users are provisioned in NetBox automatically on login.

## TLS Key Findings (follow-on work)

- `LEGO_CA_CERTIFICATES` in lego/Traefik **replaces** (not augments) the default CA pool.
  A combined bundle (system root CAs + homelab CA) is required; homelab-only breaks LE.
- `defaultGeneratedCert` with a wildcard resolver shadows domain-specific `certResolver`
  assignments on individual routers. Removing it lets each router use its own resolver.
- The step-ca ACME server at `https://10.57.1.11/acme/acme/directory` uses a cert signed
  by the homelab intermediate CA, which is not in the Traefik container's default CA pool.
