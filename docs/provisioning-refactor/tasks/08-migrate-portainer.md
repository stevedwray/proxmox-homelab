# Task 08: Migrate Portainer

## Type

Deployment

## Objective

Move `portainer.lab.gibbsgreatly.xyz` to stack-owned provisioning.

## Expected Manifest

- Stack: `portainer-stack`
- Host: `portainer.lab.gibbsgreatly.xyz`
- Backend: `http://10.57.1.20:9000`
- DNS target: `10.57.2.10`
- TLS resolver: `letsencrypt`
- Auth mode: `forwardAuth`

## Steps

1. Verify pve-test targeting with `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'`.
2. Add `terraform/lxc/stacks/portainer-stack/edge.yaml`.
3. Run manifest validator.
4. Render Traefik config.
5. Render DNS config.
6. Reconcile Authentik if required.
7. Publish generated state.
8. Validate route and auth redirect.
9. Remove only the legacy central Portainer route and service.
10. Re-run validation.

## Validation

- DNS resolves to `10.57.2.10`.
- HTTPS route responds through Traefik.
- Unauthenticated request redirects to Authentik.
- Portainer API/agent behavior is not broken.

## Stop Conditions

- Stop if Authentik redirect does not work.
- Stop if Portainer non-browser/API behavior regresses.
