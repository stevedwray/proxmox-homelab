# Backup And Restore Policy (OP-03)

This file records persistent-data policy for the pve-test teardown rehearsal.

This step does not approve destructive execution. It determines whether the
rehearsal can later proceed to a destructive approval packet.

Current OP-03 outcome: BLOCKED.

Rule for all services:
Stop if backup path is missing or restore confidence is not explicitly approved,
unless explicit accepted data loss is documented for that service.

Expected evidence root during live window:
`docs/teardown-test/evidence/${STAMP}/backups/`

## Portainer

State:
- Portainer data volume and runtime state

Backup Source:
- Not approved yet

Restore Readiness:
- Not approved yet

Data-Loss Policy:
- Not approved yet

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/portainer/`

Post-Restore Validation:
- Portainer service starts and API/UI login works
- Existing endpoints and stacks appear as expected, or approved-loss posture is documented

Stop Conditions:
- Stop if backup source is missing and data-loss policy is not explicitly accepted.
- Stop if restore confidence is missing and no approved restore test plan exists.

## Harbor

State:
- Registry blobs
- PostgreSQL data
- Redis/cache as applicable
- Trivy cache if retained

Backup Source:
- Not approved yet

Restore Readiness:
- Not approved yet

Data-Loss Policy:
- Not approved yet

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/harbor/`

Post-Restore Validation:
- Harbor starts successfully
- Registry API returns expected auth challenge at /v2/
- Sample image pull/push path is validated, or approved-loss posture is documented

Stop Conditions:
- Stop if backup source is missing and data-loss policy is not explicitly accepted.
- Stop if restore confidence is missing and no approved restore test plan exists.

## Authentik

State:
- Database state
- Media/configuration state
- Bootstrap/admin API token handling state

Backup Source:
- Not approved yet

Restore Readiness:
- Not approved yet

Data-Loss Policy:
- Not approved yet

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/authentik/`

Post-Restore Validation:
- Authentik health endpoint returns healthy
- Admin login/API token workflow is validated
- Existing providers/applications are present, or approved-loss posture is documented

Stop Conditions:
- Stop if backup source is missing and data-loss policy is not explicitly accepted.
- Stop if restore confidence is missing and no approved restore test plan exists.

## NetBox

State:
- NetBox database state
- Uploaded media/static runtime state as applicable

Backup Source:
- Not approved yet

Restore Readiness:
- Not approved yet

Data-Loss Policy:
- Not approved yet

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/netbox/`

Post-Restore Validation:
- NetBox service starts and responds
- API auth and key workflows function
- Key objects are present, or approved-loss posture is documented

Stop Conditions:
- Stop if backup source is missing and data-loss policy is not explicitly accepted.
- Stop if restore confidence is missing and no approved restore test plan exists.

## Monitoring/Grafana/Loki/VictoriaMetrics

State:
- Grafana data/config state
- Loki data
- VictoriaMetrics data

Backup Source:
- Not approved yet

Restore Readiness:
- Not approved yet

Data-Loss Policy:
- Not approved yet

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/monitoring/`

Post-Restore Validation:
- Grafana login path works
- Loki and VictoriaMetrics data paths are healthy
- Baseline dashboards/data availability validated, or approved-loss posture is documented

Stop Conditions:
- Stop if backup source is missing and data-loss policy is not explicitly accepted.
- Stop if restore confidence is missing and no approved restore test plan exists.

## Traefik ACME/Cert Storage

State:
- ACME/certificate store and related runtime cert material

Backup Source:
- Not approved yet

Restore Readiness:
- Not approved yet

Data-Loss Policy:
- Not approved yet

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/traefik-certs/`

Post-Restore Validation:
- Certificate store is present after restore
- Browser routes serve expected certificates and TLS handshake succeeds

Stop Conditions:
- Stop if backup source is missing and data-loss policy is not explicitly accepted.
- Stop if restore confidence is missing and no approved restore test plan exists.

## step-ca Authority Material

State:
- step-ca authority configuration and key material

Backup Source:
- Not approved yet

Restore Readiness:
- Not approved yet

Data-Loss Policy:
- Not approved yet

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/step-ca/`

Post-Restore Validation:
- step-ca starts and serves expected endpoints
- CA/ACME issuance path works at least for a smoke check

Stop Conditions:
- Stop if backup source is missing and data-loss policy is not explicitly accepted.
- Stop if restore confidence is missing and no approved restore test plan exists.

## CI Runner Registration/State

State:
- Runner registration state and token handling procedure
- Local runner configuration/runtime state as needed

Backup Source:
- Not approved yet

Restore Readiness:
- Not approved yet

Data-Loss Policy:
- Not approved yet

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/ci-runner/`

Post-Restore Validation:
- Runner registers or re-registers successfully
- Runner picks up and executes a test workflow job

Stop Conditions:
- Stop if backup source is missing and data-loss policy is not explicitly accepted.
- Stop if restore confidence is missing and no approved restore test plan exists.

## apt-cacher Cache

State:
- apt-cacher-ng cache and configuration

Backup Source:
- Not approved yet

Restore Readiness:
- Not approved yet

Data-Loss Policy:
- Not approved yet

Pre-Destroy Evidence:
- `docs/teardown-test/evidence/${STAMP}/backups/apt-cacher/`

Post-Restore Validation:
- apt-cacher service starts
- Proxy endpoint responds and apt clients can use cache path

Stop Conditions:
- Stop if backup source is missing and data-loss policy is not explicitly accepted.
- Stop if restore confidence is missing and no approved restore test plan exists.

## OP-03 Decision Gate

Use this simple rule to classify readiness:

- Approved for later destructive approval packet: every service has either
  approved backup plus restore confidence, or explicit accepted data loss.
- Blocked: one or more services do not satisfy that requirement.

Current result for this branch revision: Blocked.
