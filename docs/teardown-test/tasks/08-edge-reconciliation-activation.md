# Task 08: Edge Reconciliation Activation

## Type

Deployment

## Objective

Activate stack-owned edge state after Stage 3a is healthy.

## Files

- `terraform/lxc/reconcile-edge.py`
- `terraform/lxc/render-edge-traefik.py`
- `terraform/lxc/render-edge-coredns.py`
- `terraform/lxc/ansible/playbooks/deploy-coredns.yml`
- `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`
- `docs/teardown-test/runbook.md`

## Preconditions

- Task 07 complete.

## Operations

1. Regenerate edge artifacts from current manifests.
2. Run edge reconciler apply to create/update Authentik-owned objects.
3. Publish generated CoreDNS zone.
4. Publish generated Traefik files.
5. Validate all six browser DNS records and routes.

## Postconditions

- Browser edge state is active and generated from manifests.

## Validation

- All six browser hosts resolve to `${lab_ip_proxy}`.
- Generated Traefik files are loaded from `/opt/proxy-stack/dynamic`.
- Full baseline reconciler dry-run passes after apply.

## Stop Conditions

- Stop if generated DNS, Traefik, or Authentik state cannot converge.
