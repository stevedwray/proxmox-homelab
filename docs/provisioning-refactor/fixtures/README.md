# EdgeManifest Fixture Notes

Task 04 fixtures are split into valid and invalid examples for validator
implementation and unit test coverage.

## Directory Layout

- `valid/`: manifests that must pass validation
- `invalid/`: manifests that must fail validation
- `error-catalog.md`: stable machine-readable error code mapping

## Valid Fixtures

- `valid/authentik.yaml`
- `valid/harbor.yaml`
- `valid/grafana.yaml`
- `valid/portainer.yaml`
- `valid/netbox.yaml`
- `valid/traefik-dashboard.yaml`

All valid fixtures use:

- `apiVersion: homelab.gibbsgreatly.xyz/v1alpha1`
- `kind: EdgeManifest`
- hostnames under `*.lab.gibbsgreatly.xyz`
- `dns.target: 192.168.30.10`

## Invalid Fixtures

- `invalid/duplicate-host-a.yaml`
- `invalid/duplicate-host-b.yaml`
- `invalid/bad-domain.yaml`
- `invalid/missing-backend.yaml`
- `invalid/bad-auth-mode.yaml`
- `invalid/authentik-self-forward-auth.yaml`
- `invalid/harbor-forward-auth.yaml`
- `invalid/bad-url-scheme.yaml`
- `invalid/invalid-traefik-service.yaml`

The duplicate-host case is intentional and requires loading both files in the
same validation run to trigger the cross-manifest uniqueness error.

## Validator Expectations

- Valid fixtures pass with no errors.
- Invalid fixtures fail with stable codes from `error-catalog.md`.
- Validation is side-effect free and does not perform deployment actions.
