# Task 07: Edge Foundation Redeploy

## Type

Deployment

## Objective

Rebuild Stage 3a: CoreDNS seed zone, Traefik runtime, step-ca, and Authentik
direct first boot/API token.

## Files

- `docs/design/bootstrap.md`
- `docs/teardown-test/runbook.md`
- `terraform/lxc/stacks/dns-stack/stack.yaml`
- `terraform/lxc/stacks/proxy-stack/stack.yaml`
- `terraform/lxc/stacks/step-ca-stack/stack.yaml`
- `terraform/lxc/stacks/authentik-stack/stack.yaml`

## Preconditions

- Task 06 complete.
- Stage 3a dependency conflicts from Task 02 resolved.

## Operations

1. Deploy CoreDNS seed zone.
2. Deploy Traefik runtime without relying on generated per-service routes.
3. Deploy step-ca and validate ACME prerequisites.
4. Deploy Authentik via direct IP.
5. Complete Authentik first boot if needed.
6. Store or verify the automation API token in SOPS.

## Postconditions

- Edge reconciler prerequisites are healthy.

## Validation

- CoreDNS authoritative and delegated resolver checks pass.
- Traefik accepts HTTPS on `${lab_ip_proxy}:443`.
- Authentik direct health endpoint passes.
- Authentik API token is available through `./with-secrets`.

## Stop Conditions

- Stop if any Stage 3a service requires generated edge state before the
  reconciler is allowed to run.
