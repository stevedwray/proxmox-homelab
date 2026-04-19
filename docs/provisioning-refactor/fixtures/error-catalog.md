# EdgeManifest v1alpha1 Error Catalog

This catalog defines stable validator error codes for invalid fixture coverage.
Task 05 should assert these codes in unit tests.

## Error Codes

| Code | Condition | Example Message |
| --- | --- | --- |
| `EMV001` | duplicate host across manifests | `host duplicate.lab.gibbsgreatly.xyz is defined by multiple manifests` |
| `EMV002` | host is outside `*.lab.gibbsgreatly.xyz` | `host bad.example.com must end with .lab.gibbsgreatly.xyz` |
| `EMV003` | route backend object missing | `route missing-backend is missing required backend object` |
| `EMV004` | unsupported auth mode | `auth.mode saml is invalid; allowed: none, forwardAuth, native, oidc` |
| `EMV005` | authentik stack with forwardAuth | `authentik-stack cannot use auth.mode forwardAuth; use none` |
| `EMV006` | harbor stack with forwardAuth | `harbor-stack cannot use auth.mode forwardAuth; use native or oidc` |
| `EMV007` | backend.type=url with non-http(s) URL | `backend.url ftp://10.57.1.34:8080 must use http or https` |
| `EMV008` | backend.type=traefikService with invalid service ref | `backend.service api-internal must match <service>@<provider>` |

## Fixture Mapping

| Fixture | Expected Code |
| --- | --- |
| `invalid/duplicate-host-a.yaml` + `invalid/duplicate-host-b.yaml` | `EMV001` |
| `invalid/bad-domain.yaml` | `EMV002` |
| `invalid/missing-backend.yaml` | `EMV003` |
| `invalid/bad-auth-mode.yaml` | `EMV004` |
| `invalid/authentik-self-forward-auth.yaml` | `EMV005` |
| `invalid/harbor-forward-auth.yaml` | `EMV006` |
| `invalid/bad-url-scheme.yaml` | `EMV007` |
| `invalid/invalid-traefik-service.yaml` | `EMV008` |

## Notes for Validator Implementation

- Use these codes as machine-readable outputs and in test assertions.
- Keep human-readable messages stable enough for operator troubleshooting.
- Validation should be side-effect free and should not require service health checks.
