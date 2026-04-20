# Backup And Restore Policy (OP-03)

This file records persistent-data policy for the pve-test teardown rehearsal.

This step does not approve destructive execution. It determines whether the
rehearsal can later proceed to a destructive approval packet.

Current OP-03 outcome: APPROVED FOR LATER DESTRUCTIVE APPROVAL PACKET.

Approval scope note:
This is a policy approval only. It does not authorize destroy/apply/live
publish. Those remain gated by OP-04/OP-05 completion and explicit operator
approval at the destructive window.

Rule for all services:
Stop if backup path is missing and accepted data-loss is not documented. For
services marked data-loss not acceptable, stop if restore confidence is missing
or restore test plan evidence is missing.

Expected evidence root during live window:
`docs/teardown-test/evidence/${STAMP}/backups/`

## Portainer

State:
- Portainer data volume and runtime state

Backup Source:
- LXC-level backup for VMID 120 captured in the live window (`vzdump`/PBS job).
- Capture `/opt/portainer` and compose/runtime config snapshot in evidence.

Restore Readiness:
- Restore confidence: medium.
- Restore test plan: restore LXC 120 to test host, verify Portainer service
  health and login/API access, then verify expected endpoints are present.

Data-Loss Policy:
- Accepted data loss: yes, if restore path fails.
- Rationale: service is recreatable, but preserving endpoint/settings state is
  preferred for faster recovery.

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/portainer/`

Post-Restore Validation:
- Portainer service starts and API/UI login works
- Existing endpoints and stacks appear as expected, or approved-loss posture is documented

Stop Conditions:
- Stop if no LXC-level backup artifact is recorded in evidence.

## Harbor

State:
- Registry blobs
- PostgreSQL data
- Redis/cache as applicable
- Trivy cache if retained

Backup Source:
- LXC-level backup for VMID 121 captured in the live window (`vzdump`/PBS job).
- Capture Harbor config and compose/runtime files from `/opt/harbor-stack`.
- Capture project/robot policy export evidence (API or CLI output snapshot).

Restore Readiness:
- Restore confidence: medium.
- Restore test plan: restore LXC 121, verify Harbor service, verify `/v2/`
  auth challenge, and run sample image pull/push against restored registry.

Data-Loss Policy:
- Accepted data loss: no for registry blobs and Harbor configuration metadata.
- Accepted data loss: yes for Trivy cache only.

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/harbor/`

Post-Restore Validation:
- Harbor starts successfully
- Registry API returns expected auth challenge at /v2/
- Sample image pull/push path is validated, or approved-loss posture is documented

Stop Conditions:
- Stop if no LXC-level backup artifact is recorded.
- Stop if registry data backup scope excludes Harbor persistent storage.

## Authentik

State:
- Database state
- Media/configuration state
- Bootstrap/admin API token handling state

Backup Source:
- LXC-level backup for VMID 150 captured in the live window (`vzdump`/PBS job).
- Capture Authentik compose/configuration files from `/opt/authentik-stack`.
- Capture documented bootstrap/admin recovery procedure and API-token recovery
  procedure in evidence.

Restore Readiness:
- Restore confidence: medium.
- Restore test plan: restore LXC 150, verify health endpoint and admin login,
  verify provider/application objects required by browser routes.

Data-Loss Policy:
- Accepted data loss: no.
- Rationale: identity state loss has high blast radius across browser routes.

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/authentik/`

Post-Restore Validation:
- Authentik health endpoint returns healthy
- Admin login/API token workflow is validated
- Existing providers/applications are present, or approved-loss posture is documented

Stop Conditions:
- Stop if no LXC-level backup artifact is recorded.
- Stop if bootstrap/admin recovery procedure is not documented in evidence.

## NetBox

State:
- NetBox database state
- Uploaded media/static runtime state as applicable

Backup Source:
- LXC-level backup for VMID 143 captured in the live window (`vzdump`/PBS job).
- Capture NetBox compose/runtime configuration files from `/opt/netbox-stack`.

Restore Readiness:
- Restore confidence: medium.
- Restore test plan: restore LXC 143, verify NetBox service and API auth,
  verify key object counts or known reference objects.

Data-Loss Policy:
- Accepted data loss: no.

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/netbox/`

Post-Restore Validation:
- NetBox service starts and responds
- API auth and key workflows function
- Key objects are present, or approved-loss posture is documented

Stop Conditions:
- Stop if no LXC-level backup artifact is recorded.

## Monitoring/Grafana/Loki/VictoriaMetrics

State:
- Grafana data/config state
- Loki data
- VictoriaMetrics data

Backup Source:
- LXC-level backup for VMID 154 captured in the live window (`vzdump`/PBS job).
- Capture Grafana provisioning/configuration files and dashboard export if
  needed for rapid rebuild.

Restore Readiness:
- Restore confidence: medium for service restoration, low for perfect
  historical continuity.
- Restore test plan: restore LXC 154, verify Grafana login/dashboard loading,
  Loki and VictoriaMetrics health endpoints.

Data-Loss Policy:
- Accepted data loss: yes for historical metrics/logs.
- Accepted data loss: no for core monitoring service configuration required for
  platform observability.

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/monitoring/`

Post-Restore Validation:
- Grafana login path works
- Loki and VictoriaMetrics data paths are healthy
- Baseline dashboards/data availability validated, or approved-loss posture is documented

Stop Conditions:
- Stop if no LXC-level backup artifact is recorded and configuration preservation
  is not otherwise evidenced.

## Traefik ACME/Cert Storage

State:
- ACME/certificate store and related runtime cert material

Backup Source:
- LXC-level backup for VMID 153 captured in the live window (`vzdump`/PBS job).
- Capture cert storage files under `/opt/proxy-stack/certs` in evidence.

Restore Readiness:
- Restore confidence: high for re-issuance path, medium for exact cert state
  restoration.
- Restore test plan: verify proxy stack starts, validate TLS handshake on core
  browser routes, and re-issuance path if cert store is replaced.

Data-Loss Policy:
- Accepted data loss: yes for ACME cache/state if re-issuance path is working.
- Accepted data loss: no for inability to restore TLS on required routes.

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/traefik-certs/`

Post-Restore Validation:
- Certificate store is present after restore
- Browser routes serve expected certificates and TLS handshake succeeds

Stop Conditions:
- Stop if cert re-issuance path is not validated and cert backup is missing.

## step-ca Authority Material

State:
- step-ca authority configuration and key material

Backup Source:
- LXC-level backup for VMID 152 captured in the live window (`vzdump`/PBS job).
- Capture explicit backup of step-ca authority material and configuration
  (including root/intermediate material and password recovery references).

Restore Readiness:
- Restore confidence: required high.
- Restore test plan: restore LXC 152, verify CA and ACME endpoints, issue a
  smoke-test certificate, and validate dependent service trust path.

Data-Loss Policy:
- Accepted data loss: no.
- Rationale: CA authority loss is high blast radius and not acceptable.

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/step-ca/`

Post-Restore Validation:
- step-ca starts and serves expected endpoints
- CA/ACME issuance path works at least for a smoke check

Stop Conditions:
- Stop if authority-material backup is missing.
- Stop if restore confidence is below high or restore test plan evidence is absent.

## CI Runner Registration/State

State:
- Runner registration state and token handling procedure
- Local runner configuration/runtime state as needed

Backup Source:
- Capture runner registration procedure and token generation procedure in
  evidence (playbook and secret reference path).
- Optional LXC-level backup for VMID 141.

Restore Readiness:
- Restore confidence: high for re-registration path.
- Restore test plan: redeploy runner via stack apply and runner playbook,
  verify runner online and execute a test workflow.

Data-Loss Policy:
- Accepted data loss: yes.
- Rationale: runner node is intentionally recreatable if registration workflow
  is documented and tested.

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/ci-runner/`

Post-Restore Validation:
- Runner registers or re-registers successfully
- Runner picks up and executes a test workflow job

Stop Conditions:
- Stop if re-registration procedure is not captured and validated.

## apt-cacher Cache

State:
- apt-cacher-ng cache and configuration

Backup Source:
- Optional LXC-level backup for VMID 142.
- Capture apt-cacher configuration files if customized.

Restore Readiness:
- Restore confidence: high for rebuild.
- Restore test plan: redeploy apt-cacher stack, verify service response on
  port 3142, and verify cache use from a client.

Data-Loss Policy:
- Accepted data loss: yes.
- Rationale: cache content is disposable and repopulates naturally.

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/apt-cacher/`

Post-Restore Validation:
- apt-cacher service starts
- Proxy endpoint responds and apt clients can use cache path

Stop Conditions:
- Stop if apt-cacher redeploy and functional smoke check cannot be performed.

## OP-03 Decision Gate

Use this simple rule to classify readiness:

- Approved for later destructive approval packet: every service has either
  approved backup plus restore confidence, or explicit accepted data loss.
- Blocked: one or more services do not satisfy that requirement.

Current result for this branch revision: Approved for later destructive
approval packet.
