# Authentik SSO Rollout Plan

## Goal

Roll browser-facing services onto Authentik-backed SSO in controlled waves while preserving non-browser automation paths, especially Docker, Helm, CI robot, and API-token workflows.

## Branch

- Working branch: `feat/harbor-authentik-oidc-01`
- Base branch: `baseline/teardown-validated`
- Session issue: `#166`

## Design Constraints

- Use native OIDC for services that support it directly; do not force Traefik forward-auth where the service already has a better native browser flow.
- Keep service-owned API tokens, robot accounts, and machine credentials outside browser SSO.
- Treat Harbor browser SSO and Harbor CLI authentication as separate user journeys. Harbor OIDC still requires each user to generate a Harbor CLI secret after initial browser login.
- Do not run destructive infrastructure actions in this session.

## Wave 1: Harbor

Harbor is the first wave because the edge validator already models Harbor as `native` or `oidc`, and Harbor exposes OIDC settings through its configuration API. The rollout for Harbor is:

1. Change Harbor edge intent to `auth.mode: oidc` so edge discovery treats Harbor as service-native authentication instead of Traefik forward-auth.
2. Keep `harbor.yml` focused on installer/bootstrap settings and configure OIDC in the existing `harbor_postconfigure` role via Harbor's `/api/v2.0/configurations` endpoint.
3. Inject Harbor OIDC settings from `HARBOR_OIDC_*` environment variables so secrets stay in SOPS-backed secret flow.
4. Preserve admin and robot automation paths. Browser users go through Authentik; CI and headless registry clients continue to use Harbor robot credentials or per-user CLI secrets.

## Future Waves

- Wave 2: Grafana. Existing OAuth secret handling is already present; align the remaining provider metadata and validation.
- Wave 3: NetBox. Prefer native social auth or OIDC plugin wiring over proxy-only auth if stable for the deployed version.
- Wave 4: Portainer and any remaining browser-first apps. Validate whether service-native OIDC is mature enough before replacing proxy-auth patterns.

## Validation

- Validate edge manifests with `python3 terraform/lxc/validate-edge-manifests.py terraform/lxc/stacks/*/edge.yaml`.
- Validate Harbor playbook syntax with `ANSIBLE_ROLES_PATH='terraform/lxc/ansible/roles' ANSIBLE_CONFIG='terraform/lxc/ansible/ansible.cfg' ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`.
- Validate Authentik discovery still succeeds with the internal HTTPS endpoint:
  `AUTHENTIK_EXTRA_CA=certs/homelab-root.crt ./with-secrets python3 terraform/lxc/reconcile-edge.py --authentik-url "https://authentik-int.${LAB_DOMAIN}:9443" --json`.
- Defer any live Harbor OIDC apply until Authentik client details are populated and browser smoke testing is scheduled.

## Rollback

- Set Harbor edge intent back to `auth.mode: native` if Authentik integration is not ready.
- Leave Harbor running on local DB auth until the OIDC provider metadata and client secret are verified.
- If Harbor OIDC config is applied and needs to be reverted, switch `auth_mode` back to `db_auth` through the Harbor configuration API before onboarding additional local users.

## Commit

- Commit only after manifest validation, playbook syntax check, and Authentik discovery pass.
- Keep the commit focused on Harbor wave-1 OIDC wiring, rollout documentation, and repository hygiene for `certs/homelab-root.crt`.
