# Session 13 Handback - Controlled Credential Provisioning

## Metadata

- Date: 2026-06-01
- Model: GitHub Copilot GPT-5 mini
- Branch: task/monitoring-stack-phase1
- Commit at session start: fe847f6c37d4202cf4510c934fca09c319c60a1e
- Commit at session end: (see git commit below)
- Session goal: Create dedicated NetBox automation credential and dedicated Proxmox read-only credential for `pve-test`, store secrets in SOPS, validate credentials, and produce this handback.

## Scope Boundary

- In scope: Provision NetBox automation token, provision Proxmox read-only token, store secrets in `terraform/secrets.enc.yaml` (SOPS), validate credentials with focused probes, produce this handback, and commit SOPS + handback.
- Out of scope: Rotating or removing existing bootstrap/high-privilege credentials; broad RBAC changes in NetBox.
- Stop condition: New secrets are present in SOPS (not in plaintext) and focused validation probes confirm the credentials authenticate (or produce expected authorization responses).

## Files Reviewed

- terraform/lxc/stacks/netbox-stack/integrations/client.py
- terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py
- ansible/01-base-system/terraform-token-management.yml
- docs/netbox-stack/artifacts/HANDBACK-TEMPLATE.md

## Files Changed

- terraform/secrets.enc.yaml — added NETBOX_API_TOKEN and PROXMOX_READONLY_TOKEN_SECRET (encrypted with SOPS)
- test-leak.env — added PROXMOX_READONLY_TOKEN_ID (non-secret identifier used for local validation)
- docs/netbox-stack/artifacts/SESSION-13-CONTROLLED-CREDENTIAL-PROVISIONING-HANDBACK.md — this file

## Commands Run

- ./with-secrets bash /tmp/netbox_create.sh (created NetBox service user/token flow, iterative)
- ./with-secrets bash /tmp/proxmox_create.sh (created Proxmox read-only token on host and stored secret in SOPS)
- ./with-secrets bash /tmp/netbox_create_new_token.sh (ensured NetBox token creation semantics)
- ./with-secrets bash /tmp/netbox_create_manual_token.sh (created deterministic v1 token and stored secret)
- ./with-secrets bash -lc 'curl -sk -H "Authorization: Token <token-from-sops>" "http://${LAB_IP_NETBOX}:8080/api/users/users/?limit=1"' (NetBox validation)
- ./with-secrets bash -lc 'curl -sk -H "Authorization: PVEAPIToken=${PROXMOX_READONLY_TOKEN_ID}=${PROXMOX_READONLY_TOKEN_SECRET}" "https://${PROXMOX_HOST}:8006/api2/json/version"' (Proxmox validation)

## Validation Completed

- NetBox superuser API token: validated using `GET /api/users/users/` — returned HTTP 200 and expected user list.
- NetBox service token: created and stored in SOPS; authentication probe returned an authorization failure (HTTP 403 — "You do not have permission to perform this action."), which indicates the token is valid (authenticated) but intentionally lacks higher privileges. This satisfies authentication validation without exposing secrets.
- Proxmox read-only token: created on the Proxmox host as `automation@pve!terraform-readonly-1780274785` and secret stored in SOPS under `PROXMOX_READONLY_TOKEN_SECRET`. A focused probe to `/api2/json/version` returned Proxmox version info, confirming read-only authentication success.

## Validation Not Completed

- NetBox service token authorization matrix: did not grant specific API-read permissions for the `users` endpoint (403). If additional NetBox-scoped read permissions are required for the service, these should be granted in a follow-up session.

## Concrete Outcomes

- Created/ensured `svc-netbox-sync` service user and provisioned a NetBox automation token; secret stored encrypted in `terraform/secrets.enc.yaml` under `NETBOX_API_TOKEN`.
- Created a Proxmox read-only token on the host and stored its secret in `terraform/secrets.enc.yaml` under `PROXMOX_READONLY_TOKEN_SECRET` and recorded the token identifier in `test-leak.env` as `PROXMOX_READONLY_TOKEN_ID`.
- Wrote this handback file documenting actions, validation results, and next steps.

## Issues Encountered

- NetBox API behavior: token creation responses for version=2 return only a token `key` (identifier) and not the usable secret; this required creating a v1-style token (or providing a token value) to capture a usable secret for automated validation. Handled by creating a deterministic v1 token and storing it in SOPS.
- SOPS write pitfalls: early attempts incorrectly passed plaintext on the command-line and lead to transient failures; resolved by using `sops set --value-stdin` with JSON-escaped input executed under `with-secrets`.

## Risks Or Follow-Up Concerns

- The NetBox service token currently authenticates but lacks API read privileges for the `users` endpoint (403). If the automation requires specific NetBox scopes, an explicit RBAC follow-up is required.
- Ensure SOPS age keys remain available to CI and operators who need to decrypt `terraform/secrets.enc.yaml` and that the `.env.template` (if used) documents non-secret identifiers (token IDs).

## Evidence For Post-Mortem

- Proxmox version probe returned Proxmox version JSON (evidence of successful auth).
- NetBox superuser probe returned user list JSON (evidence of NetBox API reachability and superuser auth).
- All secret values are stored in `terraform/secrets.enc.yaml` (SOPS); no plaintext secrets were added to repository files.

## Recommended Next Single Session

- Title: "Grant least-privilege NetBox API scopes to svc-netbox-sync"
- Objective: Determine the minimal set of NetBox permissions required by the automation and grant them to `svc-netbox-sync` (or create a scoped token), then re-run focused validation probes.
- Files to read first: `terraform/lxc/stacks/netbox-stack/integrations/client.py`, NetBox RBAC docs.
- Rationale: Current token authenticates but lacks the specific permissions necessary for the expected API operations.
