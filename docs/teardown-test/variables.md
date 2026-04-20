# Variables And Open Questions

This file is intentionally a gate. Any value marked `REQUIRES_OPERATOR_INPUT`
must be answered before destructive execution. Values marked `VERIFY` have a
default expectation but still require confirmation during preflight.

## Execution Window

| Variable | Value |
|---|---|
| Operator approving destructive test | REQUIRES_OPERATOR_INPUT |
| Planned start time | REQUIRES_OPERATOR_INPUT |
| Planned stop/rollback deadline | REQUIRES_OPERATOR_INPUT |
| Communication channel/status notes location | REQUIRES_OPERATOR_INPUT |
| Maximum acceptable pve-test outage | REQUIRES_OPERATOR_INPUT |

## Git And Targeting

| Variable | Value |
|---|---|
| Branch to test | `dev/pve-test` |
| Commit SHA to test | REQUIRES_OPERATOR_INPUT |
| Target guard expected value | `pve-test` |
| Command for target guard | `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` |
| SOPS/age key confirmed present | VERIFY |
| `./with-secrets` confirmed working | VERIFY |

## Scope

| Stack group | Include? | Notes |
|---|---:|---|
| Platform stacks listed in README | yes | Default scope |
| Disposable `net-*` validation stacks | no | Excluded from platform rebuild unless explicitly enabled later |
| `test-docker` and `test-lxc` | no | Excluded from platform rebuild unless explicitly enabled later |
| `.hold/` stacks | no | Out of scope unless explicitly moved active |
| `headscale-stack` inventory without active `stack.yaml` | no | Orphaned inventory/state only; out of scope until active `stack.yaml` or cleanup plan exists |

## Persistent Data Policy

| Service | Backup source | Restore test done? | Data loss acceptable? |
|---|---|---:|---:|
| Portainer | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT |
| Harbor | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT |
| Authentik | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT |
| NetBox | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT |
| Monitoring/Grafana/Loki/VictoriaMetrics | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT |
| Traefik ACME/cert storage | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT |
| step-ca authority material | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT |
| CI runner registration/state | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT |
| apt-cacher cache | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT | REQUIRES_OPERATOR_INPUT |

## Bootstrap Inputs

| Variable | Value |
|---|---|
| LXC template available | VERIFY `storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz` |
| Harbor bootstrap image source policy | REQUIRES_OPERATOR_INPUT |
| Docker Hub fallback allowed for Stage 1/2 | REQUIRES_OPERATOR_INPUT |
| Harbor robot credentials available through SOPS | VERIFY |
| Cloudflare DNS token available through SOPS | VERIFY |
| Authentik superuser/API token bootstrap procedure | REQUIRES_OPERATOR_INPUT |
| step-ca bootstrap password/authority material available | REQUIRES_OPERATOR_INPUT |
| GitHub runner token/registration procedure | REQUIRES_OPERATOR_INPUT |
| Local lab CA bundle installed for Authentik API TLS | no; use `--no-verify-tls` for this rehearsal unless fixed first |
| Proxy wildcard/default certificate resolver policy | current state: `letsencrypt`; changing to `step-ca` is out of scope |

## Network And Resolver Contract

| Variable | Value |
|---|---|
| Traefik IP | `10.57.2.10` |
| CoreDNS authoritative IP | `10.57.1.13` |
| Delegated resolver IP | `10.57.1.1` |
| Expected browser DNS target | `10.57.2.10` |
| Resolver command for authoritative checks | `dig @10.57.1.13 +short <host>` |
| Resolver command for delegated checks | `dig @10.57.1.1 +short <host>` |
| MikroTik conditional forwarder confirmed | VERIFY |

## Rebuild Order Approval

The final stack order must be confirmed in Task 02 before execution. The
candidate below reflects the current bootstrap model after removing the
`proxy-stack` dependency on `authentik-stack`.

| Order | Stack | Command owner | Notes |
|---:|---|---|---|
| 1 | `portainer-stack` | REQUIRES_OPERATOR_INPUT | Stage 1/2 foundation |
| 2 | `apt-cacher-stack` | REQUIRES_OPERATOR_INPUT | Independent foundation utility for later apt-backed deploys |
| 3 | `harbor-stack` | REQUIRES_OPERATOR_INPUT | Stage 1/2 registry foundation; depends on Portainer |
| 4 | `ci-runner-01` | REQUIRES_OPERATOR_INPUT | Stage 1/2 foundation if included |
| 5 | `dns-stack` | REQUIRES_OPERATOR_INPUT | Stage 3a CoreDNS seed authority |
| 6 | `proxy-stack` | REQUIRES_OPERATOR_INPUT | Stage 3a Traefik runtime; no Authentik dependency |
| 7 | `step-ca-stack` | REQUIRES_OPERATOR_INPUT | Stage 3a internal CA |
| 8 | `authentik-stack` | REQUIRES_OPERATOR_INPUT | Stage 3a direct first boot/API token |
| 9 | edge reconciliation activation | REQUIRES_OPERATOR_INPUT | Not a Terraform stack; publish generated DNS/Traefik/Auth state |
| 10 | `monitoring-stack` | REQUIRES_OPERATOR_INPUT | Stage 3b |
| 11 | `netbox-stack` | REQUIRES_OPERATOR_INPUT | Stage 3b |

## Success Criteria

| Criterion | Expected value |
|---|---|
| Edge manifest validation | pass |
| Full edge reconciler final dry-run | pass/no-op |
| Browser records | all six resolve to `10.57.2.10` |
| Authentik route | no forward-auth recursion |
| Harbor registry path | `/v2/` returns native registry auth challenge |
| Grafana | native login/OIDC flow, no Traefik forward-auth |
| Portainer | forward-auth browser gate, agent/API behavior usable |
| NetBox | forward-auth browser gate, API credential flow understood |
| Traefik dashboard | `api@internal` route with forward-auth |
