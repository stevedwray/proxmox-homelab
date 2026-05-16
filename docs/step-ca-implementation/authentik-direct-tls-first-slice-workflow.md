# Authentik Direct TLS First Slice Operator Workflow

## Scope

This runbook captures the implemented first slice:

- keep `certs/homelab-root.crt` as trust anchor source
- issue/present a step-ca-backed cert on a dedicated internal Authentik hostname
- move Grafana Authentik token/API backchannel to verified HTTPS direct endpoint

This workflow started with Authentik plus Grafana, and now also records the
completed follow-on migrations for Portainer OAuth/resource and Traefik
forward-auth runtime paths. It does not cover Harbor registry TLS
normalization.

## Implemented Behavior

- `deploy-authentik-stack.yml` now:
  - ensures `step` CLI exists on Authentik host
  - issues/renews `tls.crt` and `tls.key` from step-ca for internal Authentik hostname
  - uses the `homelab-admin` provisioner by default unless overridden with
    `STEP_CA_PROVISIONER_NAME`
  - writes nginx config and exposes direct TLS on `:9443`
  - verifies direct TLS with root trust and hostname validation
- `deploy-monitoring-stack.yml` now defaults Grafana OAuth token/API backchannel to:
  - `https://authentik-int.<lab-domain>:9443/...`
  - `GF_AUTH_GENERIC_OAUTH_TLS_SKIP_VERIFY_INSECURE=false`
  - bind-mounts the host CA trust store into the Grafana container so the
    homelab root CA is trusted at runtime
- Portainer Authentik OAuth/resource backchannel now uses the internal direct
  TLS Authentik path with verification enabled (completed migration).
- Traefik forward-auth runtime backchannel now uses the internal direct TLS
  Authentik path (completed migration).
- `authentik-bg.<lab-domain>` remains a separate breakglass direct-access name and
  is no longer the intended machine-to-machine TLS endpoint for this slice

## Prerequisites

1. `step-ca-stack` is deployed and healthy.
2. Local root trust anchor exists in repo: `certs/homelab-root.crt`.
3. Managed host trust distribution path has run (`lxc_base` or `trust-homelab-ca.yml`).
4. Required env values are available via `./with-secrets`, including:
   - `LAB_IP_STEP_CA`
   - `LAB_FQDN_AUTHENTIK_INTERNAL` if overriding the default `authentik-int.<lab-domain>`
   - `STEP_CA_PROVISIONER_PASSWORD`
   - Authentik and Grafana existing secrets used by deploy playbooks

## Deployment Workflow

1. Deploy Authentik stack:

```bash
./with-secrets scripts/provision.sh --stack authentik-stack
```

2. Deploy Monitoring stack:

```bash
./with-secrets scripts/provision.sh --stack monitoring-stack
```

## Validation Workflow

1. Verify Authentik direct TLS endpoint presents a cert chaining to homelab root:

```bash
./with-secrets ansible-playbook terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml \
  -i terraform/lxc/stacks/authentik-stack/inventory.yml
```

Expected result: play includes successful direct TLS check against
`https://authentik-int.<lab-domain>:9443/-/health/live/` with certificate
verification enabled.

2. Verify Grafana OAuth runtime uses HTTPS backchannel values:

```bash
./with-secrets ansible-playbook terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml \
  -i terraform/lxc/stacks/monitoring-stack/inventory.yml
```

Expected result: rendered compose config includes:

- `GF_AUTH_GENERIC_OAUTH_TOKEN_URL=https://authentik-int.<lab-domain>:9443/application/o/token/`
- `GF_AUTH_GENERIC_OAUTH_API_URL=https://authentik-int.<lab-domain>:9443`
- `GF_AUTH_GENERIC_OAUTH_TLS_SKIP_VERIFY_INSECURE=false`

3. Optional host-level direct endpoint check from monitoring host:

```bash
./with-secrets ansible -i terraform/lxc/stacks/monitoring-stack/inventory.yml all -u root -m shell -a \
"curl --silent --show-error --fail https://authentik-int.${LAB_DOMAIN}:9443/-/health/live/"
```

## Day-2 Renewal Workflow

Certificate renewal is handled during Authentik stack reconcile:

- cert is reissued if missing
- cert is reissued when expiry is within 30 days
- nginx service continues serving renewed cert after compose reconcile

Recommended operator action:

```bash
./with-secrets scripts/provision.sh --stack authentik-stack
```

Then re-run monitoring reconcile to ensure Grafana config remains aligned:

```bash
./with-secrets scripts/provision.sh --stack monitoring-stack
```

## Notes And Known Boundaries

- This slice keeps existing planning truth: trust anchor remains `certs/homelab-root.crt`.
- This slice separates machine-to-machine trust from browser breakglass access:
  `authentik-int.<lab-domain>` is the step-ca-backed internal endpoint, while
  `authentik-bg.<lab-domain>` can remain a manual/self-signed operator path.
- Harbor Authentik backchannel migration remains intentionally deferred.
- Defer rationale: Harbor derives token and userinfo behavior from OIDC
  discovery and does not expose the same independent endpoint override pattern
  used by Grafana and Portainer.
- Authentik API reconcile helpers in some workflows still use existing HTTP or `--no-verify-tls`
  conventions and are out of scope for this first slice.
